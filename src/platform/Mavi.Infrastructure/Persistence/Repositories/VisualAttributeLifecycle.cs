using Mavi.Application.Abstractions.Security;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The Visual Attribute lifecycle against PostgreSQL (S2b plan §8).
/// </summary>
/// <remarks>
/// Every transaction is short and locks its rows explicitly; none is open while a worker
/// infers, reads evidence or uploads. The claim query is written for this plane alone: its
/// eligibility (identity fence, attempt bound, deadline) is not VisionJob's or
/// SceneAnalysis's, which is why it is not a shared "claim helper" (plan §6).
/// </remarks>
public sealed class VisualAttributeLifecycle(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities) : IVisualAttributeLifecycle
{
    // Serialises activation bookkeeping across hosts; distinct from the visibility barrier's key.
    private const long ActivationLockKey = 0x4D415649_41545452;

    // --- Activation and queueing ------------------------------------------------------

    public async Task<DateTimeOffset> EnsureActivationAsync(VisualAttributeReleaseDefinition definition, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        await using var transaction = await BeginFreshAsync(cancellationToken);
        await db.Database.ExecuteSqlInterpolatedAsync($"SELECT pg_advisory_xact_lock({ActivationLockKey})", cancellationToken);
        var latest = await db.VisualAttributeIdentityActivations.AsNoTracking()
            .OrderByDescending(x => x.ActivatedAtUtc).ThenByDescending(x => x.Id)
            .FirstOrDefaultAsync(cancellationToken);
        if (latest is not null && latest.Fingerprint == definition.Identity.Fingerprint)
        {
            await transaction.CommitAsync(cancellationToken);
            return latest.ActivatedAtUtc;
        }

        var activation = VisualAttributeIdentityActivation.Create(
            definition.Identity.Fingerprint,
            VisualAttributeReleaseParser.CanonicalIdentity(definition.Identity),
            definition.AttributeSchemaJson,
            timeProvider.GetUtcNow());
        db.VisualAttributeIdentityActivations.Add(activation);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return activation.ActivatedAtUtc;
    }

    public async Task<int> QueueEligibleAsync(
        VisualAttributeReleaseDefinition definition, DateTimeOffset activatedAtUtc, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentOutOfRangeException.ThrowIfLessThan(batchSize, 1);
        var fingerprint = definition.Identity.Fingerprint;
        var classes = ObjectClasses(definition.Schema);

        // Visible, completed within the current activation, with at least one applicable
        // Track, and no unit for this identity yet. A run with nothing applicable never gets
        // a unit (NotApplicable consumes no attempt); a run from before the activation is
        // history (no automatic backfill, ADR-013 §9).
        db.ChangeTracker.Clear();
        var runIds = await db.ProcessingRuns.AsNoTracking()
            .Where(run => run.Status == ProcessingRunStatus.Completed &&
                          run.VisibilitySequence != null &&
                          run.CompletedAtUtc != null &&
                          run.CompletedAtUtc >= activatedAtUtc)
            .Where(run => db.Tracks.Any(track => track.ProcessingRunId == run.Id && classes.Contains(track.ObjectClass)))
            .Where(run => !db.VisualAttributeAnalyses.Any(unit => unit.ProcessingRunId == run.Id && unit.IdentityFingerprint == fingerprint))
            .OrderBy(run => run.CompletedAtUtc).ThenBy(run => run.Id)
            .Select(run => run.Id)
            .Take(batchSize)
            .ToListAsync(cancellationToken);

        var created = 0;
        var fields = definition.Identity.ToFields();
        foreach (var runId in runIds)
        {
            db.ChangeTracker.Clear();
            db.VisualAttributeAnalyses.Add(VisualAttributeAnalysis.Queue(runId, fields, timeProvider.GetUtcNow()));
            try
            {
                await db.SaveChangesAsync(cancellationToken);
                created++;
            }
            catch (DbUpdateException exception) when (IsIdentityConflict(exception))
            {
                // The unique index is the arbiter: a concurrent reconciler won this run.
            }
        }

        db.ChangeTracker.Clear();
        return created;
    }

    // --- Claim ----------------------------------------------------------------------------

    public async Task<VisualAttributeLeaseGrant?> ClaimNextAsync(
        string workerId, string identityFingerprint, VisualAttributeLeasePolicy policy, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (!CanonicalSha256.IsCanonical(identityFingerprint)) return null;
        var schemaJson = await AttributeSchemaJsonAsync(identityFingerprint, cancellationToken);
        if (schemaJson is null) return null;

        VisualAttributeAnalysis unit;
        LeaseCapability capability;
        await using (var transaction = await BeginFreshAsync(cancellationToken))
        {
            var nowUtc = timeProvider.GetUtcNow();
            var deadlineCutoffUtc = nowUtc - policy.MaximumAnalysisDuration;
            // The identity fence is in the predicate: a worker composed from another binding
            // must never take ownership of, or consume an attempt of, a unit it cannot
            // reproduce. The attempt bound and the deadline are in it too, so an exhausted or
            // expired unit is never selected and then skipped on every poll.
            var candidate = await db.VisualAttributeAnalyses.FromSqlInterpolated($"""
                SELECT * FROM visual_attribute_analyses
                WHERE identity_fingerprint = {identityFingerprint}
                  AND attempt_count < {policy.MaximumAttempts}
                  AND (first_claimed_at_utc IS NULL OR first_claimed_at_utc > {deadlineCutoffUtc})
                  AND (status = 'Queued' OR (status = 'Running' AND lease_expires_at_utc <= {nowUtc}))
                ORDER BY queued_at_utc, id
                FOR UPDATE SKIP LOCKED LIMIT 1
                """).SingleOrDefaultAsync(cancellationToken);
            if (candidate is null || !candidate.CanClaim(nowUtc, policy))
            {
                await transaction.CommitAsync(cancellationToken);
                return null;
            }

            capability = leaseCapabilities.Create();
            candidate.Claim(workerId, capability.Hash, nowUtc, policy);
            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            unit = candidate;
        }

        // Tracks and accepted crops of a completed run are immutable: read after the commit.
        var schema = VisualAttributeReleaseParser.ParseStoredSchema(schemaJson, unit.AttributeSchemaSha256);
        var tracks = await LeaseTracksAsync(unit.ProcessingRunId, ObjectClasses(schema), cancellationToken);
        return new VisualAttributeLeaseGrant(
            unit.Id,
            unit.ProcessingRunId,
            workerId,
            capability.Token,
            unit.AttemptCount,
            unit.LeaseExpiresAtUtc!.Value,
            unit.Deadline(policy.MaximumAnalysisDuration)!.Value,
            unit.Identity,
            tracks);
    }

    private async Task<IReadOnlyList<VisualAttributeLeaseTrack>> LeaseTracksAsync(
        Guid runId, IReadOnlyCollection<ObjectClass> classes, CancellationToken cancellationToken)
    {
        var tracks = await db.Tracks.AsNoTracking()
            .Where(track => track.ProcessingRunId == runId && classes.Contains(track.ObjectClass))
            .OrderBy(track => track.LocalTrackNumber)
            .Select(track => new { track.Id, track.ObjectClass })
            .ToListAsync(cancellationToken);
        var crops = await (
                from track in db.Tracks.AsNoTracking()
                where track.ProcessingRunId == runId && classes.Contains(track.ObjectClass)
                join observation in db.Observations.AsNoTracking() on track.Id equals observation.TrackId
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                orderby observation.EvidenceRank
                select new
                {
                    observation.TrackId,
                    observation.Id,
                    observation.ObservationType,
                    observation.EvidenceRank,
                    artifact.SizeBytes,
                    artifact.Sha256,
                })
            .ToListAsync(cancellationToken);
        var byTrack = crops.ToLookup(item => item.TrackId);
        return tracks
            .Select(track => new VisualAttributeLeaseTrack(
                track.Id,
                ObjectClassToken(track.ObjectClass),
                byTrack[track.Id]
                    .Select(crop => new VisualAttributeLeaseObservation(crop.Id, RoleToken(crop.ObservationType), crop.EvidenceRank, crop.SizeBytes, crop.Sha256))
                    .ToList()))
            .ToList();
    }

    // --- Heartbeat and failure --------------------------------------------------------------

    public async Task<VisualAttributeHeartbeatOutcome> HeartbeatAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, VisualAttributeLeasePolicy policy,
        CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return new(null, new VisualAttributeRefusal("visual_attribute_analysis_not_found"));
        try
        {
            unit.Heartbeat(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow(), policy);
        }
        catch (DomainValidationException exception)
        {
            return new(null, new VisualAttributeRefusal(exception.Code));
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(unit.LeaseExpiresAtUtc, null);
    }

    public async Task<VisualAttributeFailureOutcome> FailAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable,
        string? failureMessage, VisualAttributeLeasePolicy policy, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return new(null, new VisualAttributeRefusal("visual_attribute_analysis_not_found"));

        // An exact duplicate of the recorded transition answers with its recorded outcome and
        // writes nothing; it can never touch a later attempt (plan §9).
        if (unit.IsRecordedFailureReplay(workerId, TokenMatches(leaseToken, unit.LastFailedTokenHash), attemptCount, failureCode, failureMessage))
        {
            await transaction.CommitAsync(cancellationToken);
            return new(unit.LastFailedOutcome, null);
        }

        VisualAttributeFailResult result;
        try
        {
            result = unit.FailAttempt(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, failureCode, retryable,
                failureMessage, timeProvider.GetUtcNow(), policy);
        }
        catch (DomainValidationException exception)
        {
            return new(null, new VisualAttributeRefusal(exception.Code));
        }

        db.VisualAttributeAttemptFailures.Add(result.Record);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(result.Outcome, null);
    }

    // --- Platform authority ------------------------------------------------------------------

    public async Task<VisualAttributeSweepResult> SweepAsync(VisualAttributeLeasePolicy policy, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var deadlineCutoffUtc = nowUtc - policy.MaximumAnalysisDuration;

        // SKIP LOCKED: a unit whose owner is publishing right now is locked, and the
        // publication wins; the next sweep finds it no longer Running.
        var overdue = await db.VisualAttributeAnalyses.FromSqlInterpolated($"""
            SELECT * FROM visual_attribute_analyses
            WHERE status IN ('Queued', 'Running')
              AND first_claimed_at_utc IS NOT NULL
              AND first_claimed_at_utc <= {deadlineCutoffUtc}
            ORDER BY first_claimed_at_utc, id
            FOR UPDATE SKIP LOCKED LIMIT {batchSize}
            """).ToListAsync(cancellationToken);
        foreach (var unit in overdue)
            unit.FailDeadlineExceeded(nowUtc, policy);

        var abandoned = await db.VisualAttributeAnalyses.FromSqlInterpolated($"""
            SELECT * FROM visual_attribute_analyses
            WHERE status = 'Running'
              AND attempt_count >= {policy.MaximumAttempts}
              AND lease_expires_at_utc <= {nowUtc}
            ORDER BY lease_expires_at_utc, id
            FOR UPDATE SKIP LOCKED LIMIT {batchSize}
            """).ToListAsync(cancellationToken);
        var exhausted = 0;
        foreach (var unit in abandoned.Where(unit => unit.IsExhausted(nowUtc, policy)))
        {
            unit.FailAttemptsExhausted(nowUtc, policy);
            exhausted++;
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new VisualAttributeSweepResult(overdue.Count, exhausted);
    }

    // --- Evidence authorisation --------------------------------------------------------------

    public async Task<VisualAttributeEvidenceAuthorization> AuthorizeEvidenceReadAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, Guid observationId, CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        var unit = await db.VisualAttributeAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        if (unit is null)
            return new(null, new VisualAttributeRefusal("visual_attribute_analysis_not_found"));
        if (unit.Status != VisualAttributeAnalysisStatus.Running)
            return new(null, new VisualAttributeRefusal("visual_attribute_not_running"));
        if (!unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow()))
            return new(null, new VisualAttributeRefusal("visual_attribute_lease_invalid"));

        var schemaJson = await AttributeSchemaJsonAsync(unit.IdentityFingerprint, cancellationToken);
        if (schemaJson is null)
            return new(null, new VisualAttributeRefusal("visual_attribute_evidence_forbidden"));
        var classes = ObjectClasses(VisualAttributeReleaseParser.ParseStoredSchema(schemaJson, unit.AttributeSchemaSha256));

        // The IDOR fence: the Observation must belong to a Track of this unit's own run, of a
        // class the analysis applies to, and its crop must be an accepted EvidenceCrop.
        var crop = await (
                from observation in db.Observations.AsNoTracking()
                where observation.Id == observationId
                join track in db.Tracks.AsNoTracking() on observation.TrackId equals track.Id
                where track.ProcessingRunId == unit.ProcessingRunId && classes.Contains(track.ObjectClass)
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                select new { artifact.Id, artifact.StorageKey, artifact.MimeType, artifact.SizeBytes, artifact.Sha256 })
            .SingleOrDefaultAsync(cancellationToken);
        if (crop is null || !crop.StorageKey.StartsWith("evidence/", StringComparison.Ordinal))
            return new(null, new VisualAttributeRefusal("visual_attribute_evidence_forbidden"));

        return new(new VisualAttributeEvidenceGrant(unit.Id, unit.AttemptCount, observationId, crop.Id, crop.StorageKey,
            crop.MimeType, crop.SizeBytes, crop.Sha256), null);
    }

    public async Task<VisualAttributeRefusal?> AuthorizeUploadAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        var unit = await db.VisualAttributeAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        if (unit is null) return new VisualAttributeRefusal("visual_attribute_analysis_not_found");
        if (unit.Status != VisualAttributeAnalysisStatus.Running) return new VisualAttributeRefusal("visual_attribute_not_running");
        return unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow())
            ? null
            : new VisualAttributeRefusal("visual_attribute_lease_invalid");
    }

    public Task<string?> AttributeSchemaJsonAsync(string identityFingerprint, CancellationToken cancellationToken) =>
        db.VisualAttributeIdentityActivations.AsNoTracking()
            .Where(x => x.Fingerprint == identityFingerprint)
            .OrderByDescending(x => x.ActivatedAtUtc)
            .Select(x => x.AttributeSchemaJson)
            .FirstOrDefaultAsync(cancellationToken);

    // --- Helpers ---------------------------------------------------------------------------

    internal static IReadOnlyCollection<ObjectClass> ObjectClasses(AttributeSchemaDefinition schema) =>
        schema.ApplicableObjectClasses().Select(ParseObjectClass).ToList();

    internal static ObjectClass ParseObjectClass(string value) => value switch
    {
        VisualAttributeContractRules.ObjectClassPerson => ObjectClass.Person,
        VisualAttributeContractRules.ObjectClassVehicle => ObjectClass.Vehicle,
        _ => throw new InvalidOperationException("Unknown object class."),
    };

    internal static string ObjectClassToken(ObjectClass value) => value switch
    {
        ObjectClass.Person => VisualAttributeContractRules.ObjectClassPerson,
        ObjectClass.Vehicle => VisualAttributeContractRules.ObjectClassVehicle,
        _ => throw new InvalidOperationException("Unknown object class."),
    };

    internal static string RoleToken(ObservationType value) => value switch
    {
        ObservationType.Representative => "representative",
        ObservationType.NearView => "near-view",
        ObservationType.EarlyDiverse => "early-diverse",
        ObservationType.LateDiverse => "late-diverse",
        _ => throw new InvalidOperationException("Unknown observation role."),
    };

    private bool TokenMatches(string leaseToken, byte[]? expectedHash) =>
        expectedHash is not null && leaseCapabilities.Matches(leaseToken, expectedHash);

    private Task<VisualAttributeAnalysis?> LockAsync(Guid analysisId, CancellationToken cancellationToken) =>
        db.VisualAttributeAnalyses
            .FromSqlInterpolated($"SELECT * FROM visual_attribute_analyses WHERE id = {analysisId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);

    /// <summary>A transaction on state read fresh from the database (the SceneAnalysis rule).</summary>
    private async Task<IDbContextTransaction> BeginFreshAsync(CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        return await db.Database.BeginTransactionAsync(cancellationToken);
    }

    private static bool IsIdentityConflict(DbUpdateException exception) =>
        exception.InnerException is PostgresException
        {
            SqlState: PostgresErrorCodes.UniqueViolation,
            ConstraintName: "ux_visual_attribute_analyses_identity",
        };
}
