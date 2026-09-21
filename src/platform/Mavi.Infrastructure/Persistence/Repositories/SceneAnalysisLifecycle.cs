using System.Data;
using System.Security.Cryptography;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Common;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The transactional lifecycle of an analysis unit, against PostgreSQL.
/// </summary>
/// <remarks>
/// <para>
/// Every transaction here is short and takes its row lock explicitly, because the one
/// rule that governs all of them is that <b>no transaction is open while analytics
/// compute</b>. A claim commits before the engine starts; the facts arrive in a second
/// transaction that revalidates ownership before its first write.
/// </para>
/// <para>
/// The clock is <see cref="TimeProvider"/> throughout, never <c>DateTime.UtcNow</c>, so
/// lease expiry, the reclaim grace and terminal exhaustion are all drivable in a test
/// without waiting for real time to pass.
/// </para>
/// </remarks>
public sealed class SceneAnalysisLifecycle(MaviDbContext db, TimeProvider timeProvider)
    : ISceneAnalysisLifecycle
{
    // --- Creation ----------------------------------------------------------

    public async Task<int> QueueEligibleUnitsAsync(
        string algorithmVersion,
        string parametersSha256,
        string? sourceCommit,
        DateTimeOffset earliestRunCompletedAtUtc,
        int batchSize,
        CancellationToken cancellationToken)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(batchSize, 1);

        var eligible = await EligibleIdentitiesAsync(
            algorithmVersion,
            earliestRunCompletedAtUtc,
            batchSize,
            cancellationToken);

        var created = 0;
        foreach (var (runId, revisionId) in eligible)
        {
            var identity = new SceneAnalysisIdentity(
                runId,
                revisionId,
                algorithmVersion,
                parametersSha256,
                sourceCommit);
            var result = await RequestAnalysisAsync(identity, cancellationToken);
            if (result.Outcome == SceneAnalysisQueueOutcome.Created)
            {
                created++;
            }
        }

        return created;
    }

    /// <summary>
    /// The runs that should have a unit and do not.
    /// </summary>
    /// <remarks>
    /// A camera with no scene configuration, no active revision, or an active revision
    /// with nothing enabled simply produces no rows: "never configured" and "deliberately
    /// disabled" are the absence of a match, not a branch in the code. Only runs that are
    /// complete <i>and</i> visible are eligible, so analytics can never precede the
    /// evidence they are derived from.
    /// </remarks>
    private Task<List<(Guid RunId, Guid RevisionId)>> EligibleIdentitiesAsync(
        string algorithmVersion,
        DateTimeOffset earliestRunCompletedAtUtc,
        int batchSize,
        CancellationToken cancellationToken) =>
        (from run in db.ProcessingRuns.AsNoTracking()
         where run.Status == ProcessingRunStatus.Completed
               && run.VisibilitySequence != null
               && run.CompletedAtUtc != null
               && run.CompletedAtUtc >= earliestRunCompletedAtUtc
         join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
         join configuration in db.SceneConfigurations.AsNoTracking()
             on video.CameraId equals configuration.CameraId
         join revision in db.SceneConfigurationRevisions.AsNoTracking()
             on configuration.ActiveRevisionId equals revision.Id
         where (revision.Zones.Any(zone => zone.Enabled) || revision.TripLines.Any(line => line.Enabled))
               // A geometry edit never reaches backwards on its own: runs that finished
               // before this revision was activated are explicit re-analysis, not
               // automatic work.
               && run.CompletedAtUtc >= revision.CreatedAtUtc
               && !db.SceneAnalyses.Any(unit =>
                   unit.ProcessingRunId == run.Id
                   && unit.RevisionId == revision.Id
                   && unit.AlgorithmVersion == algorithmVersion)
         orderby run.CompletedAtUtc, run.Id
         select new ValueTuple<Guid, Guid>(run.Id, revision.Id))
        .Take(batchSize)
        .ToListAsync(cancellationToken);

    public async Task<SceneAnalysisQueueResult> RequestAnalysisAsync(
        SceneAnalysisIdentity identity,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(identity);

        var unit = SceneAnalysis.Queue(
            identity.ProcessingRunId,
            identity.RevisionId,
            identity.AlgorithmVersion,
            identity.ParametersSha256,
            identity.SourceCommit,
            timeProvider.GetUtcNow());

        try
        {
            db.ChangeTracker.Clear();
            db.SceneAnalyses.Add(unit);
            await db.SaveChangesAsync(cancellationToken);
            return new SceneAnalysisQueueResult(SceneAnalysisQueueOutcome.Created, unit.Id);
        }
        catch (DbUpdateException exception) when (IsIdentityConflict(exception))
        {
            // The unique index is the arbiter, not a check-then-insert: two concurrent
            // requests for one identity both attempt the insert, one wins, and the loser
            // reports what the winner created rather than creating a second unit.
            db.ChangeTracker.Clear();
            var existing = await db.SceneAnalyses
                .AsNoTracking()
                .SingleAsync(
                    x => x.ProcessingRunId == identity.ProcessingRunId
                         && x.RevisionId == identity.RevisionId
                         && x.AlgorithmVersion == identity.AlgorithmVersion,
                    cancellationToken);

            return new SceneAnalysisQueueResult(Classify(existing.Status), existing.Id);
        }
    }

    private static SceneAnalysisQueueOutcome Classify(SceneAnalysisStatus status) => status switch
    {
        SceneAnalysisStatus.Queued => SceneAnalysisQueueOutcome.AlreadyQueued,
        SceneAnalysisStatus.Running => SceneAnalysisQueueOutcome.AlreadyRunning,
        SceneAnalysisStatus.Completed => SceneAnalysisQueueOutcome.AlreadyAnalysed,
        SceneAnalysisStatus.Failed => SceneAnalysisQueueOutcome.FailedRequiresRetry,
        SceneAnalysisStatus.Superseded => SceneAnalysisQueueOutcome.AlreadySuperseded,
        _ => throw new InvalidOperationException($"Unhandled analysis status '{status}'.")
    };

    // --- Claim and reclaim -------------------------------------------------

    public async Task<SceneAnalysisClaim?> ClaimNextAsync(
        SceneAnalysisLeasePolicy policy,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);

        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var reclaimCutoffUtc = nowUtc - policy.ReclaimGrace;

        // SKIP LOCKED is what makes two hosts safe: they cannot select the same row, so
        // they cannot both claim it. The attempt bound is in the predicate as well as in
        // CanClaim so that an exhausted unit is never selected and then skipped, which
        // would return the same row on every call.
        var unit = await db.SceneAnalyses.FromSqlInterpolated($"""
            SELECT * FROM scene_analyses
            WHERE attempt_count < {policy.MaximumAttempts}
              AND (status = 'Queued'
                   OR (status = 'Running'
                       AND lease_expires_at_utc IS NOT NULL
                       AND lease_expires_at_utc < {reclaimCutoffUtc}))
            ORDER BY queued_at_utc, id
            FOR UPDATE SKIP LOCKED LIMIT 1
            """).SingleOrDefaultAsync(cancellationToken);

        if (unit is null)
        {
            await transaction.CommitAsync(cancellationToken);
            return null;
        }

        // 32 random bytes that exist here and nowhere else. Only the hash is persisted.
        var claimToken = RandomNumberGenerator.GetBytes(SceneAnalysis.ClaimTokenByteLength);
        unit.Claim(
            SHA256.HashData(claimToken),
            nowUtc,
            policy.LeaseDuration,
            policy.MaximumAttempts,
            policy.ReclaimGrace);

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);

        // The engine starts only after this commit.
        return new SceneAnalysisClaim(
            unit.Id,
            new SceneAnalysisIdentity(
                unit.ProcessingRunId,
                unit.RevisionId,
                unit.AlgorithmVersion,
                unit.ParametersSha256,
                unit.SourceCommit),
            unit.AttemptCount,
            claimToken,
            unit.LeaseExpiresAtUtc!.Value);
    }

    public async Task<int> ExhaustAbandonedUnitsAsync(
        SceneAnalysisLeasePolicy policy,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);

        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var reclaimCutoffUtc = nowUtc - policy.ReclaimGrace;

        // SKIP LOCKED again, and for the same reason it matters here: a unit whose owner
        // is committing its success right now is locked, and skipping it is exactly the
        // behaviour wanted. Completion wins; the next pass will find nothing to do.
        var abandoned = await db.SceneAnalyses.FromSqlInterpolated($"""
            SELECT * FROM scene_analyses
            WHERE status = 'Running'
              AND attempt_count >= {policy.MaximumAttempts}
              AND lease_expires_at_utc IS NOT NULL
              AND lease_expires_at_utc < {reclaimCutoffUtc}
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            """).ToListAsync(cancellationToken);

        foreach (var unit in abandoned)
        {
            // Clears the claim-token hash, which is what makes the overrunning attempt
            // stale — exactly as a reclaim would.
            unit.Exhaust(nowUtc, policy.ReclaimGrace);
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return abandoned.Count;
    }

    // --- Terminal transitions ----------------------------------------------

    public async Task<SceneAnalysisTransitionResult> CommitFactsAsync(
        SceneAnalysisClaim claim,
        SceneAnalysisFacts facts,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);
        ArgumentNullException.ThrowIfNull(facts);

        await using var transaction = await BeginFreshAsync(cancellationToken);

        // Every unit of this run is locked here, in id order, not just the one being
        // completed. Superseding needs the siblings anyway, and taking them in one
        // deterministic order is what stops two concurrent completions of the same run
        // deadlocking against each other.
        var runUnits = await db.SceneAnalyses.FromSqlInterpolated($"""
            SELECT * FROM scene_analyses
            WHERE processing_run_id = {claim.Identity.ProcessingRunId}
            ORDER BY id
            FOR UPDATE
            """).ToListAsync(cancellationToken);

        var unit = runUnits.SingleOrDefault(x => x.Id == claim.AnalysisId);
        if (unit is null)
        {
            return await RollbackAsync(
                transaction,
                SceneAnalysisTransitionResult.Failure(SceneAnalyticsErrorCodes.TransitionInvalid),
                cancellationToken);
        }

        // An early exit, not the fence. Complete() revalidates ownership and the whole
        // transaction rolls back if it throws, so correctness does not rest here; what
        // this avoids is a stale attempt doing the delete-and-insert work and then taking
        // the completion barrier's exclusive lock — briefly blocking every other
        // completion — only to be rejected a few lines later.
        if (!unit.OwnedBy(claim.AttemptCount, claim.ClaimToken.Span))
        {
            return await RollbackAsync(transaction, SceneAnalysisTransitionResult.Stale, cancellationToken);
        }

        // Scoped to this unit id alone, which is what makes a repeated attempt idempotent
        // without touching another revision's or algorithm's facts.
        await DeleteFactsAsync(claim.AnalysisId, cancellationToken);

        db.TrackAnalysisOutcomes.AddRange(facts.Outcomes);
        db.TrackZoneVisits.AddRange(facts.ZoneVisits);
        db.TrackZoneSummaries.AddRange(facts.ZoneSummaries);
        db.TrackLineCrossings.AddRange(facts.LineCrossings);
        db.TrackMotionSummaries.AddRange(facts.MotionSummaries);

        // The facts and the successful unit become observable in the same commit, so no
        // search snapshot can see one without the other.
        await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, cancellationToken);
        var visibilitySequence =
            await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);

        var analysed = 0;
        var unavailable = 0;
        foreach (var outcome in facts.Outcomes)
        {
            if (outcome.Outcome == TrackAnalysisOutcomeKind.Analysed) analysed++;
            else unavailable++;
        }

        try
        {
            unit.Complete(
                claim.AttemptCount,
                claim.ClaimToken.Span,
                visibilitySequence,
                analysed,
                unavailable,
                timeProvider.GetUtcNow());
        }
        catch (SceneAnalysisStaleAttemptException)
        {
            return await RollbackAsync(transaction, SceneAnalysisTransitionResult.Stale, cancellationToken);
        }
        catch (DomainValidationException exception)
        {
            return await RollbackAsync(
                transaction,
                SceneAnalysisTransitionResult.Failure(exception.Code),
                cancellationToken);
        }

        // Currency changes; nothing else does. A superseded unit keeps its facts, counts,
        // timestamps and visibility sequence exactly as committed.
        foreach (var sibling in runUnits)
        {
            if (sibling.Id != unit.Id && sibling.Status == SceneAnalysisStatus.Completed)
            {
                sibling.Supersede();
            }
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return SceneAnalysisTransitionResult.Success;
    }

    public async Task<SceneAnalysisTransitionResult> ReportFailureAsync(
        SceneAnalysisClaim claim,
        string failureCode,
        string? failureDetails,
        int maximumAttempts,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);

        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(claim.AnalysisId, cancellationToken);
        if (unit is null)
        {
            return await RollbackAsync(
                transaction,
                SceneAnalysisTransitionResult.Failure(SceneAnalyticsErrorCodes.TransitionInvalid),
                cancellationToken);
        }

        try
        {
            // A stale attempt stops here and writes nothing — in particular it cannot
            // mark the current owner failed.
            unit.FailAttempt(
                claim.AttemptCount,
                claim.ClaimToken.Span,
                failureCode,
                failureDetails,
                maximumAttempts,
                timeProvider.GetUtcNow());
        }
        catch (SceneAnalysisStaleAttemptException)
        {
            return await RollbackAsync(transaction, SceneAnalysisTransitionResult.Stale, cancellationToken);
        }
        catch (DomainValidationException exception)
        {
            return await RollbackAsync(
                transaction,
                SceneAnalysisTransitionResult.Failure(exception.Code),
                cancellationToken);
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return SceneAnalysisTransitionResult.Success;
    }

    public async Task<SceneAnalysisTransitionResult> RetryAsync(
        Guid analysisId,
        CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null)
        {
            return await RollbackAsync(
                transaction,
                SceneAnalysisTransitionResult.Failure(SceneAnalyticsErrorCodes.TransitionInvalid),
                cancellationToken);
        }

        try
        {
            // The same row, the same identity — never a second unit — and no fact is
            // deleted here. Replacement happens only inside a later successful commit.
            unit.Retry(timeProvider.GetUtcNow());
        }
        catch (DomainValidationException exception)
        {
            return await RollbackAsync(
                transaction,
                SceneAnalysisTransitionResult.Failure(exception.Code),
                cancellationToken);
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return SceneAnalysisTransitionResult.Success;
    }

    public Task<SceneAnalysis?> GetAsync(Guid analysisId, CancellationToken cancellationToken) =>
        db.SceneAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);

    // --- Helpers -----------------------------------------------------------

    /// <summary>
    /// Starts a transaction on state read fresh from the database.
    /// </summary>
    /// <remarks>
    /// The clear is the load-bearing part. EF returns an already-tracked instance for a
    /// row a raw query re-reads, so without it a second transaction on this context would
    /// lock the row, receive the values this context remembered, and decide ownership
    /// from them. That is precisely the state another host may have changed underneath —
    /// the fence would then be checked against a stale copy of the thing it fences.
    /// </remarks>
    private async Task<IDbContextTransaction> BeginFreshAsync(CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        return await db.Database.BeginTransactionAsync(cancellationToken);
    }

    private Task<SceneAnalysis?> LockAsync(Guid analysisId, CancellationToken cancellationToken) =>
        db.SceneAnalyses
            .FromSqlInterpolated($"SELECT * FROM scene_analyses WHERE id = {analysisId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);

    private async Task DeleteFactsAsync(Guid analysisId, CancellationToken cancellationToken)
    {
        await db.TrackAnalysisOutcomes.Where(x => x.AnalysisId == analysisId)
            .ExecuteDeleteAsync(cancellationToken);
        await db.TrackZoneVisits.Where(x => x.AnalysisId == analysisId)
            .ExecuteDeleteAsync(cancellationToken);
        await db.TrackZoneSummaries.Where(x => x.AnalysisId == analysisId)
            .ExecuteDeleteAsync(cancellationToken);
        await db.TrackLineCrossings.Where(x => x.AnalysisId == analysisId)
            .ExecuteDeleteAsync(cancellationToken);
        await db.TrackMotionSummaries.Where(x => x.AnalysisId == analysisId)
            .ExecuteDeleteAsync(cancellationToken);
    }

    private async Task<SceneAnalysisTransitionResult> RollbackAsync(
        IDbContextTransaction transaction,
        SceneAnalysisTransitionResult result,
        CancellationToken cancellationToken)
    {
        await transaction.RollbackAsync(cancellationToken);
        db.ChangeTracker.Clear();
        return result;
    }

    private static bool IsIdentityConflict(DbUpdateException exception) =>
        exception.InnerException is PostgresException
        {
            SqlState: PostgresErrorCodes.UniqueViolation,
            ConstraintName: "ux_scene_analyses_identity"
        };
}
