using System.Security.Cryptography;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The finalizer's transactions against PostgreSQL (F3 plan §7). The rules that govern all of
/// them: every transaction is short, takes its row lock explicitly, starts from state read
/// fresh (never from what this context remembered), and no transaction is open while the
/// executor validates a payload, reads staging or seals evidence.
/// </summary>
/// <remarks>
/// The SQL predicates are pre-filters only. Every condition they express is re-proven by the
/// aggregate on the locked row with the same clock value and policy: the claim deadline
/// (<see cref="VisionJob.ClaimFinalization"/>), the canonical claim state
/// (<see cref="VisionJob.FinalizationClaimStateAt"/>) and exhaustion
/// (<see cref="VisionJob.ExhaustFinalization"/>). A disagreement between SQL and domain is an
/// invariant violation, never silently one side's answer.
/// </remarks>
public sealed class VisionFinalizationLifecycle(MaviDbContext db, TimeProvider timeProvider) : IVisionFinalizationLifecycle
{
    /// <summary>
    /// The canonical claim states a finalizer may act on (F3 plan §5.2): all three fields null
    /// (unclaimed), or all three present with a 32-byte hash and an expiry at or before {0}
    /// (expired). Malformed rows match neither disjunct. Shared by the claim and reconciliation
    /// queries so the two cannot drift.
    /// </summary>
    private const string CanonicalNoLiveClaimSql =
        "((finalization_claim_token_hash IS NULL AND finalization_claim_expires_at_utc IS NULL AND finalization_claim_extended_at_utc IS NULL)" +
        " OR (finalization_claim_token_hash IS NOT NULL AND octet_length(finalization_claim_token_hash) = 32" +
        " AND finalization_claim_expires_at_utc IS NOT NULL AND finalization_claim_extended_at_utc IS NOT NULL" +
        " AND finalization_claim_expires_at_utc <= {0}))";

    /// <summary>A canonical claim of either liveness: the complement (within Finalizing) is malformed.</summary>
    private const string CanonicalAnyClaimSql =
        "((finalization_claim_token_hash IS NULL AND finalization_claim_expires_at_utc IS NULL AND finalization_claim_extended_at_utc IS NULL)" +
        " OR (finalization_claim_token_hash IS NOT NULL AND octet_length(finalization_claim_token_hash) = 32" +
        " AND finalization_claim_expires_at_utc IS NOT NULL AND finalization_claim_extended_at_utc IS NOT NULL))";

    // --- Claim ---------------------------------------------------------------

    public async Task<VisionFinalizationClaim?> ClaimNextAsync(VisionFinalizationPolicy policy, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);

        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        // now < accepted_at + MaximumDuration, rearranged for the index (F3 plan §7.1).
        var deadlineCutoffUtc = nowUtc - policy.MaximumDuration;

        var job = await db.VisionJobs.FromSqlRaw(
                "SELECT * FROM vision_jobs" +
                " WHERE status = 'Finalizing'" +
                " AND finalization_attempt_count < {1}" +
                " AND finalization_accepted_at_utc > {2}" +
                " AND " + CanonicalNoLiveClaimSql +
                " ORDER BY finalization_accepted_at_utc, id" +
                " FOR UPDATE SKIP LOCKED LIMIT 1",
                nowUtc, policy.MaximumAttempts, deadlineCutoffUtc)
            .SingleOrDefaultAsync(cancellationToken);
        if (job is null)
        {
            await transaction.CommitAsync(cancellationToken);
            return null;
        }

        var run = await db.ProcessingRuns.AsNoTracking().SingleOrDefaultAsync(x => x.Id == job.ProcessingRunId, cancellationToken);
        var video = run is null
            ? null
            : await db.VideoAssets.AsNoTracking().SingleOrDefaultAsync(x => x.Id == run.VideoAssetId, cancellationToken);

        // 32 random bytes that exist here and nowhere else. Only the hash is persisted.
        var claimToken = RandomNumberGenerator.GetBytes(VisionJob.FinalizationClaimTokenByteLength);
        // The aggregate re-proves state, attempts, canonical claim and the deadline itself.
        job.ClaimFinalization(SHA256.HashData(claimToken), nowUtc, policy.ClaimDuration, policy.MaximumAttempts, policy.MaximumDuration);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);

        // A job whose run or video is gone is still claimed (the attempt is consumed) so the
        // executor fails it deterministically as context-invalid rather than the selection
        // returning the same row every cycle (F3 plan §7.1).
        return new VisionFinalizationClaim(
            job.Id,
            job.ProcessingRunId,
            video?.Id ?? Guid.Empty,
            job.AttemptCount,
            job.FinalizationAttemptCount,
            claimToken,
            job.FinalizationClaimExpiresAtUtc!.Value,
            job.FinalizationDeadline(policy.MaximumDuration)!.Value,
            job.CompletionDigest!,
            job.FinalizationAcceptedAtUtc!.Value);
    }

    public async Task<VisionFinalizationExtension> ExtendClaimAsync(
        VisionFinalizationClaim claim,
        VisionFinalizationPolicy policy,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);
        ArgumentNullException.ThrowIfNull(policy);

        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var job = await LockAsync(claim.JobId, cancellationToken);
        if (job is null)
            return await RollbackAsync(transaction, new VisionFinalizationExtension(VisionFinalizationClaimStatus.Lost, null), cancellationToken);

        try
        {
            job.ExtendFinalizationClaim(claim.ClaimToken.Span, nowUtc, policy.ClaimExtension, policy.MaximumDuration);
        }
        catch (DomainValidationException)
        {
            // The aggregate is the only place the extension rule lives; the lifecycle merely
            // names the reason for the caller, and writes nothing either way.
            var status = job.FinalizationOwnedBy(claim.ClaimToken.Span, nowUtc)
                ? VisionFinalizationClaimStatus.DeadlineReached
                : VisionFinalizationClaimStatus.Lost;
            return await RollbackAsync(transaction, new VisionFinalizationExtension(status, job.FinalizationClaimExpiresAtUtc), cancellationToken);
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new VisionFinalizationExtension(VisionFinalizationClaimStatus.Live, job.FinalizationClaimExpiresAtUtc);
    }

    // --- Inputs (no lock, no transaction) ------------------------------------

    public async Task<VisionFinalizationInputs?> LoadInputsAsync(VisionFinalizationClaim claim, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);
        db.ChangeTracker.Clear();

        var run = await db.ProcessingRuns.AsNoTracking().SingleOrDefaultAsync(x => x.Id == claim.ProcessingRunId, cancellationToken);
        if (run is null)
            return null;
        var video = await db.VideoAssets.AsNoTracking().SingleOrDefaultAsync(x => x.Id == run.VideoAssetId, cancellationToken);
        if (video is null)
            return null;

        // Immutable after the hand-off (only ever deleted, and only once the job is terminal),
        // so an unlocked read is exact; a bytea of up to the request maximum never sits under
        // a row lock (F3 plan §7.3).
        var payload = await db.VisionFinalizationPayloads.AsNoTracking()
            .SingleOrDefaultAsync(x => x.JobId == claim.JobId && x.AttemptCount == claim.AttemptCount, cancellationToken);
        return new VisionFinalizationInputs(payload, video.DurationMs, video.RecordingStartUtc);
    }

    // --- Publication (F3 plan §7.4) ------------------------------------------

    public async Task<VisionFinalizationTransition> PublishAsync(
        VisionFinalizationClaim claim,
        ValidatedVisionResult result,
        FinalizationGraphPlan graph,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);
        ArgumentNullException.ThrowIfNull(result);
        ArgumentNullException.ThrowIfNull(graph);

        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();

        // 2–5: lock, re-read, prove Finalizing, live ownership and identity. Early exits; the
        // fence proper is CompleteFinalization in step 13, on this same locked instance.
        var job = await LockAsync(claim.JobId, cancellationToken);
        if (job is null || job.Status != VisionJobStatus.Finalizing || !job.FinalizationOwnedBy(claim.ClaimToken.Span, nowUtc))
            return await RollbackAsync(transaction, VisionFinalizationTransition.Stale, cancellationToken);
        if (job.AttemptCount != claim.AttemptCount ||
            job.FinalizationAttemptCount != claim.FinalizationAttemptCount ||
            !string.Equals(job.CompletionDigest, claim.CompletionDigest, StringComparison.Ordinal) ||
            !string.Equals(job.CompletionDigest, result.CompletionDigest, StringComparison.Ordinal) ||
            result.AttemptCount != claim.AttemptCount)
            return await RollbackAsync(transaction, VisionFinalizationTransition.Stale, cancellationToken);

        // 6–7: the run and video are in the state the hand-off left them, and no graph exists.
        var run = await db.ProcessingRuns.SingleOrDefaultAsync(x => x.Id == job.ProcessingRunId, cancellationToken);
        var video = run is null ? null : await db.VideoAssets.SingleOrDefaultAsync(x => x.Id == run.VideoAssetId, cancellationToken);
        if (run is null || video is null ||
            run.Status != ProcessingRunStatus.Running || video.ProcessingStatus != VideoProcessingStatus.Processing ||
            run.Id != claim.ProcessingRunId)
            return await RollbackAsync(transaction, VisionFinalizationTransition.Failed(VisionFinalizationFailureCodes.ContextInvalid), cancellationToken);
        if (await db.Tracks.AnyAsync(x => x.ProcessingRunId == run.Id, cancellationToken))
            return await RollbackAsync(transaction, VisionFinalizationTransition.Failed(VisionFinalizationFailureCodes.ContextInvalid), cancellationToken);

        try
        {
            // 8–9: the bulk write, before the barrier: the exclusive lock blocks every
            // first-page search and every other publication for as long as it is held, so the
            // graph (proportional to the Track count) is written first. Uncommitted either way.
            await FinalizationGraphPersistence.AddAsync(db, graph, cancellationToken);

            // 10–12: barrier, sequence, publication instant.
            await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, cancellationToken);
            var visibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
            var completionNowUtc = timeProvider.GetUtcNow();

            // 13–16: the claim-fenced completion, then the run and video.
            job.CompleteFinalization(claim.ClaimToken.Span, completionNowUtc);
            run.MarkCompleted(
                result.FramesProcessed,
                result.Tracks.Count,
                result.ProcessingDurationMs,
                result.DetectorName,
                result.DetectorVersion,
                result.TrackerName,
                result.TrackerVersion,
                result.RuntimeProvenanceJson,
                completionNowUtc);
            run.AssignCompletionVisibilitySequence(visibilitySequence);
            video.MarkProcessed();

            // 17: save.
            await db.SaveChangesAsync(cancellationToken);
        }
        catch (DomainValidationException)
        {
            return await RollbackAsync(transaction, VisionFinalizationTransition.Stale, cancellationToken);
        }
        catch (Exception exception) when (exception is DbUpdateException or PostgresException or NpgsqlException or TimeoutException)
        {
            // Refused before commit: nothing is written, and the claim rules decide the retry.
            return await RollbackAsync(transaction, VisionFinalizationTransition.Retry(VisionFinalizationFailureCodes.DbTransient), cancellationToken);
        }

        // 18: commit. Whether the database committed after a failing commit call is its
        // knowledge alone (F3 plan §10.2): never retry this transaction, never compensate.
        try
        {
            await transaction.CommitAsync(cancellationToken);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            return await RollbackAsync(transaction, VisionFinalizationTransition.Ambiguous, cancellationToken);
        }

        db.ChangeTracker.Clear();
        return VisionFinalizationTransition.Published;
    }

    // --- Claimant-owned terminal failure and transient notes -----------------

    public async Task<VisionFinalizationTransition> FailAsync(
        VisionFinalizationClaim claim,
        string code,
        string? details,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);
        if (!VisionFinalizationFailureCodes.IsDeterministic(code))
            throw new ArgumentOutOfRangeException(nameof(code), "Only a deterministic finalization code ends a job through the claimant.");

        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var job = await LockAsync(claim.JobId, cancellationToken);
        if (job is null)
            return await RollbackAsync(transaction, VisionFinalizationTransition.Stale, cancellationToken);

        try
        {
            // A stale claimant stops here and writes nothing; in particular it cannot mark
            // the live owner's attempt failed.
            job.FailFinalization(claim.ClaimToken.Span, code, details, nowUtc);
            await FailRunAndVideoAsync(job, code, details, nowUtc, cancellationToken);
        }
        catch (DomainValidationException)
        {
            return await RollbackAsync(transaction, VisionFinalizationTransition.Stale, cancellationToken);
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return VisionFinalizationTransition.Failed(code);
    }

    public async Task<VisionFinalizationTransition> NoteTransientAsync(
        VisionFinalizationClaim claim,
        string code,
        bool releaseClaim,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(claim);
        if (!VisionFinalizationFailureCodes.IsTransient(code))
            throw new ArgumentOutOfRangeException(nameof(code), "Only a transient finalization code is noted.");

        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var job = await LockAsync(claim.JobId, cancellationToken);
        // NoteFinalizationError is not itself claim-fenced (F1), so ownership is proven here,
        // under the same lock, before it is called (F3 plan §8.5). On a job that in fact
        // committed (an ambiguous commit that succeeded) this finds Completed and writes nothing.
        if (job is null || !job.FinalizationOwnedBy(claim.ClaimToken.Span, nowUtc))
            return await RollbackAsync(transaction, VisionFinalizationTransition.Stale, cancellationToken);

        try
        {
            job.NoteFinalizationError(code);
            if (releaseClaim)
                job.ReleaseFinalizationClaim(claim.ClaimToken.Span, nowUtc);
        }
        catch (DomainValidationException)
        {
            return await RollbackAsync(transaction, VisionFinalizationTransition.Stale, cancellationToken);
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return VisionFinalizationTransition.Noted;
    }

    // --- Reconciliation (F3 plan §7.5) ---------------------------------------

    public async Task<VisionFinalizationReconciliation> ExhaustAbandonedAsync(
        VisionFinalizationPolicy policy,
        int batchSize,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);
        ArgumentOutOfRangeException.ThrowIfLessThan(batchSize, 1);

        // Read-only, before any lock: the rows nobody may act on, for the operator.
        db.ChangeTracker.Clear();
        var malformed = await db.VisionJobs.FromSqlRaw(
                "SELECT * FROM vision_jobs WHERE status = 'Finalizing' AND NOT " + CanonicalAnyClaimSql)
            .AsNoTracking()
            .Select(x => x.Id)
            .ToListAsync(cancellationToken);

        var exhausted = 0;
        var invariant = new List<Guid>();
        // One row per transaction, so a row whose run or video refuses the transition (an
        // invariant violation, left for the operator) cannot hold a lock over the others, and
        // is excluded from the rest of this pass rather than re-selected.
        for (var processed = 0; processed < batchSize; processed++)
        {
            await using var transaction = await BeginFreshAsync(cancellationToken);
            var nowUtc = timeProvider.GetUtcNow();
            var deadlineCutoffUtc = nowUtc - policy.MaximumDuration;
            var excluded = invariant.ToArray();

            // A job whose live claimant is publishing right now is row-locked and skipped:
            // completion wins, and the next pass finds nothing to do.
            var job = await db.VisionJobs.FromSqlRaw(
                    "SELECT * FROM vision_jobs" +
                    " WHERE status = 'Finalizing'" +
                    " AND " + CanonicalNoLiveClaimSql +
                    " AND (finalization_attempt_count >= {1} OR finalization_accepted_at_utc <= {2})" +
                    " AND NOT (id = ANY({3}))" +
                    " ORDER BY finalization_accepted_at_utc, id" +
                    " FOR UPDATE SKIP LOCKED LIMIT 1",
                    nowUtc, policy.MaximumAttempts, deadlineCutoffUtc, excluded)
                .SingleOrDefaultAsync(cancellationToken);
            if (job is null)
            {
                await transaction.CommitAsync(cancellationToken);
                break;
            }

            try
            {
                // Tokenless and failure-only; the aggregate re-proves the canonical
                // no-live-claim state and the exhausted bound from the locked row.
                job.ExhaustFinalization(nowUtc, policy.MaximumAttempts, policy.MaximumDuration);
                await FailRunAndVideoAsync(job, VisionFinalizationFailureCodes.Exhausted, null, nowUtc, cancellationToken);
            }
            catch (DomainValidationException)
            {
                invariant.Add(job.Id);
                await RollbackAsync(transaction, 0, cancellationToken);
                continue;
            }

            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            db.ChangeTracker.Clear();
            exhausted++;
        }

        return new VisionFinalizationReconciliation(exhausted, malformed, invariant);
    }

    // --- Payload cleanup (F3 plan §7.8) --------------------------------------

    public async Task<int> CleanUpPayloadsAsync(int batchSize, TimeSpan grace, CancellationToken cancellationToken)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(batchSize, 1);
        ArgumentOutOfRangeException.ThrowIfLessThan(grace, TimeSpan.Zero);

        db.ChangeTracker.Clear();
        var cutoffUtc = timeProvider.GetUtcNow() - grace;
        // Terminal jobs only: a Finalizing job's payload is never eligible, and the job row
        // itself is never touched. Idempotent and retryable; a second pass finds nothing.
        var eligible = await db.VisionFinalizationPayloads.AsNoTracking()
            .Where(payload => db.VisionJobs.Any(job =>
                job.Id == payload.JobId &&
                (job.Status == VisionJobStatus.Completed || job.Status == VisionJobStatus.Failed || job.Status == VisionJobStatus.Cancelled) &&
                job.CompletedAtUtc != null && job.CompletedAtUtc <= cutoffUtc))
            .OrderBy(payload => payload.JobId).ThenBy(payload => payload.AttemptCount)
            .Select(payload => new { payload.JobId, payload.AttemptCount })
            .Take(batchSize)
            .ToListAsync(cancellationToken);

        var deleted = 0;
        foreach (var key in eligible)
        {
            deleted += await db.VisionFinalizationPayloads
                .Where(payload => payload.JobId == key.JobId && payload.AttemptCount == key.AttemptCount)
                .ExecuteDeleteAsync(cancellationToken);
        }

        return deleted;
    }

    // --- Health counts (F3 plan §6.9) ----------------------------------------

    public async Task<VisionFinalizationCounts> CountAsync(CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        var nowUtc = timeProvider.GetUtcNow();
        var row = await db.Database.SqlQueryRaw<CountsRow>(
                "SELECT count(*)::int AS \"FinalizingJobs\"," +
                " count(*) FILTER (WHERE " + CanonicalAnyClaimSql + " AND finalization_claim_expires_at_utc > {0})::int AS \"LiveClaims\"," +
                " count(*) FILTER (WHERE NOT " + CanonicalAnyClaimSql + ")::int AS \"MalformedClaims\"," +
                " min(finalization_accepted_at_utc) AS \"OldestFinalizingAcceptedAtUtc\"" +
                " FROM vision_jobs WHERE status = 'Finalizing'",
                nowUtc)
            .SingleAsync(cancellationToken);
        return new VisionFinalizationCounts(row.FinalizingJobs, row.LiveClaims, row.MalformedClaims, row.OldestFinalizingAcceptedAtUtc);
    }

    private sealed class CountsRow
    {
        public int FinalizingJobs { get; set; }
        public int LiveClaims { get; set; }
        public int MalformedClaims { get; set; }
        public DateTimeOffset? OldestFinalizingAcceptedAtUtc { get; set; }
    }

    // --- Helpers ---------------------------------------------------------------

    private async Task FailRunAndVideoAsync(VisionJob job, string code, string? details, DateTimeOffset nowUtc, CancellationToken cancellationToken)
    {
        // The existing failed-processing transitions (B3 plan §10.8). Both hold for a Finalizing
        // job by the hand-off preconditions; if either refuses, the caller rolls everything back.
        var run = await db.ProcessingRuns.SingleOrDefaultAsync(x => x.Id == job.ProcessingRunId, cancellationToken)
            ?? throw new DomainValidationException("vision_finalization_context_invalid", "The job's run is missing.");
        var video = await db.VideoAssets.SingleOrDefaultAsync(x => x.Id == run.VideoAssetId, cancellationToken)
            ?? throw new DomainValidationException("vision_finalization_context_invalid", "The run's video is missing.");
        run.MarkFailed(code, details, nowUtc);
        video.MarkProcessingFailed();
    }

    /// <summary>Starts a transaction on state read fresh from the database (the clear is load-bearing).</summary>
    private async Task<IDbContextTransaction> BeginFreshAsync(CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        return await db.Database.BeginTransactionAsync(cancellationToken);
    }

    private Task<VisionJob?> LockAsync(Guid jobId, CancellationToken cancellationToken) =>
        db.VisionJobs
            .FromSqlInterpolated($"SELECT * FROM vision_jobs WHERE id = {jobId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);

    /// <summary>Abandons the transaction and reports why, without writing anything.</summary>
    private async Task<T> RollbackAsync<T>(IDbContextTransaction transaction, T result, CancellationToken cancellationToken)
    {
        try
        {
            await transaction.RollbackAsync(cancellationToken);
        }
        catch (Exception exception) when (exception is InvalidOperationException or NpgsqlException)
        {
            // Already completed, aborted or died during commit; there is nothing left to roll back.
        }

        db.ChangeTracker.Clear();
        return result;
    }
}
