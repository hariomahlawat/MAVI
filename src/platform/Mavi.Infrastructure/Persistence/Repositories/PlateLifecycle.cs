using Mavi.Application.Abstractions.Security;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.Plates.Release;
using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Plates;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The plate lifecycle against PostgreSQL (ADR-013 implementation amendment 2026-10-13, item 11).
/// </summary>
/// <remarks>
/// The attribute plane's transaction discipline, applied to plate units: every transaction is short and
/// locks its rows explicitly; none is open while a worker infers, reads evidence or uploads. Only Vehicle
/// Tracks are leased. Automatic queueing covers runs completed after the identity's activation; history
/// is queued only by an explicit, bounded re-analysis request (plan §2.2; ADR-013 §9).
/// </remarks>
public sealed class PlateLifecycle(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities) : IPlateLifecycle
{
    // Serialises activation bookkeeping across hosts; distinct from every other advisory key ("MAVIPLAT").
    private const long ActivationLockKey = 0x4D415649_504C4154;

    public const string AnalysisNotFoundCode = "plate_analysis_not_found";
    public const string EvidenceForbiddenCode = "plate_evidence_forbidden";

    // --- Activation and queueing ------------------------------------------------------

    public async Task<DateTimeOffset> EnsureActivationAsync(PlateReleaseDefinition definition, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        await using var transaction = await BeginFreshAsync(cancellationToken);
        await db.Database.ExecuteSqlInterpolatedAsync($"SELECT pg_advisory_xact_lock({ActivationLockKey})", cancellationToken);
        var latest = await db.PlateIdentityActivations.AsNoTracking()
            .OrderByDescending(x => x.ActivatedAtUtc).ThenByDescending(x => x.Id)
            .FirstOrDefaultAsync(cancellationToken);
        if (latest is not null && latest.Fingerprint == definition.Identity.Fingerprint)
        {
            await transaction.CommitAsync(cancellationToken);
            return latest.ActivatedAtUtc;
        }

        var activation = PlateIdentityActivation.Create(definition.Identity.Fingerprint, definition.Identity.Canonical,
            definition.ParametersJson, definition.SummaryPolicyJson, timeProvider.GetUtcNow());
        db.PlateIdentityActivations.Add(activation);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return activation.ActivatedAtUtc;
    }

    public async Task<int> QueueEligibleAsync(
        PlateReleaseDefinition definition, DateTimeOffset activatedAtUtc, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentOutOfRangeException.ThrowIfLessThan(batchSize, 1);
        var fingerprint = definition.Identity.Fingerprint;
        db.ChangeTracker.Clear();
        // Visible, completed within the current activation, with a Vehicle Track and no unit for this
        // identity yet. A run without a Vehicle Track never gets a unit (NotApplicable consumes nothing);
        // a run from before the activation is history (no automatic backfill).
        var runIds = await EligibleRuns()
            .Where(run => run.CompletedAtUtc >= activatedAtUtc)
            .Where(run => !db.PlateAnalyses.Any(unit => unit.ProcessingRunId == run.Id && unit.IdentityFingerprint == fingerprint))
            .OrderBy(run => run.CompletedAtUtc).ThenBy(run => run.Id)
            .Select(run => run.Id)
            .Take(batchSize)
            .ToListAsync(cancellationToken);
        var (created, _) = await QueueRunsAsync(runIds, definition.IdentityFields, cancellationToken);
        return created;
    }

    public async Task<PlateReanalysisResult> RequestReanalysisAsync(
        PlateReleaseDefinition definition, PlateReanalysisRequest request, int maximumRuns, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(request);
        ArgumentOutOfRangeException.ThrowIfLessThan(maximumRuns, 1);
        var byRuns = request.ProcessingRunIds is not null;
        var byWindow = request.CameraId is not null || request.FromUtc is not null || request.ToUtc is not null;
        if (byRuns == byWindow) return PlateReanalysisResult.Refused("plate_reanalysis_scope_invalid");

        db.ChangeTracker.Clear();
        List<Guid> matched;
        if (byRuns)
        {
            var ids = request.ProcessingRunIds!;
            if (ids.Count == 0 || ids.Count > maximumRuns || ids.Distinct().Count() != ids.Count || ids.Contains(Guid.Empty))
                return PlateReanalysisResult.Refused("plate_reanalysis_scope_invalid");
            var known = await db.ProcessingRuns.AsNoTracking().Where(run => ids.Contains(run.Id)).Select(run => run.Id).ToListAsync(cancellationToken);
            if (known.Count != ids.Count) return PlateReanalysisResult.Refused("processing_run_not_found");
            matched = [.. ids];
        }
        else
        {
            if (request.CameraId is not { } cameraId || cameraId == Guid.Empty ||
                request.FromUtc is not { } fromUtc || request.ToUtc is not { } toUtc || fromUtc >= toUtc)
                return PlateReanalysisResult.Refused("plate_reanalysis_scope_invalid");
            matched = await LatestRunsInWindowAsync(cameraId, fromUtc.ToUniversalTime(), toUtc.ToUniversalTime(), maximumRuns + 1, cancellationToken);
            // The bound applies after the per-video selection, and a request over it queues nothing.
            if (matched.Count > maximumRuns) return PlateReanalysisResult.Refused("plate_reanalysis_too_many_runs");
        }

        var eligible = await EligibleRuns().Where(run => matched.Contains(run.Id)).Select(run => run.Id).ToListAsync(cancellationToken);
        var ordered = matched.Where(eligible.Contains).ToList();
        var (queued, already) = await QueueRunsAsync(ordered, definition.IdentityFields, cancellationToken);
        return new PlateReanalysisResult(definition.Identity.Fingerprint, matched.Count, queued, already, matched.Count - ordered.Count, null)
        {
            SelectedRunIds = matched,
        };
    }

    /// <summary>
    /// Window mode's selection: for every VideoAsset of the camera whose recording overlaps
    /// <c>[windowFrom, windowTo)</c>, exactly its latest completed, visible ProcessingRun — the one with the highest
    /// visibility sequence (the order publication made them visible, which is also how Track search picks
    /// a video's current run). Visibility sequences are unique (<c>ux_processing_runs_visibility_sequence</c>),
    /// so the order has no ties. Older or superseded runs of the same video are never selected. The result
    /// is ordered by recording start, then video id; at most
    /// <paramref name="take"/> are returned.
    /// </summary>
    internal async Task<List<Guid>> LatestRunsInWindowAsync(Guid cameraId, DateTimeOffset windowFrom, DateTimeOffset windowTo, int take,
        CancellationToken cancellationToken)
    {
        var visible = db.ProcessingRuns.AsNoTracking()
            .Where(run => run.Status == ProcessingRunStatus.Completed && run.CompletedAtUtc != null && run.VisibilitySequence != null);
        var latest =
            from run in visible
            join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
            where video.CameraId == cameraId && video.RecordingStartUtc < windowTo && video.RecordingEndUtc > windowFrom
            where !visible.Any(other => other.VideoAssetId == run.VideoAssetId && other.VisibilitySequence > run.VisibilitySequence)
            orderby video.RecordingStartUtc, video.Id
            select run.Id;
        return await latest.Take(take).ToListAsync(cancellationToken);
    }

    /// <summary>Completed, visible runs with at least one Vehicle Track.</summary>
    private IQueryable<ProcessingRun> EligibleRuns() =>
        db.ProcessingRuns.AsNoTracking()
            .Where(run => run.Status == ProcessingRunStatus.Completed && run.VisibilitySequence != null && run.CompletedAtUtc != null)
            .Where(run => db.Tracks.Any(track => track.ProcessingRunId == run.Id && track.ObjectClass == ObjectClass.Vehicle));

    private async Task<(int Created, int AlreadyQueued)> QueueRunsAsync(
        IReadOnlyList<Guid> runIds, PlateIdentityFields fields, CancellationToken cancellationToken)
    {
        var created = 0;
        var already = 0;
        foreach (var runId in runIds)
        {
            db.ChangeTracker.Clear();
            if (await db.PlateAnalyses.AsNoTracking().AnyAsync(unit => unit.ProcessingRunId == runId && unit.IdentityFingerprint == fields.Fingerprint, cancellationToken))
            {
                already++;
                continue;
            }

            db.PlateAnalyses.Add(PlateAnalysis.Queue(runId, fields, timeProvider.GetUtcNow()));
            try
            {
                await db.SaveChangesAsync(cancellationToken);
                created++;
            }
            catch (DbUpdateException exception) when (IsIdentityConflict(exception))
            {
                // The unique index is the arbiter: a concurrent reconciler or request won this run.
                already++;
            }
        }

        db.ChangeTracker.Clear();
        return (created, already);
    }

    // --- Claim ----------------------------------------------------------------------------

    public async Task<PlateLeaseGrant?> ClaimNextAsync(
        string workerId, string identityFingerprint, PlateLeasePolicy policy, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (!CanonicalSha256.IsCanonical(identityFingerprint)) return null;
        if (await ParametersJsonAsync(identityFingerprint, cancellationToken) is null) return null;

        PlateAnalysis unit;
        LeaseCapability capability;
        await using (var transaction = await BeginFreshAsync(cancellationToken))
        {
            var nowUtc = timeProvider.GetUtcNow();
            var deadlineCutoffUtc = nowUtc - policy.MaximumAnalysisDuration;
            // The identity fence is in the predicate: a worker composed from another binding never takes
            // ownership of, or consumes an attempt of, a unit it cannot reproduce.
            var candidate = await db.PlateAnalyses.FromSqlInterpolated($"""
                SELECT * FROM plate_analyses
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
        var tracks = await LeaseTracksAsync(unit.ProcessingRunId, cancellationToken);
        return new PlateLeaseGrant(unit.Id, unit.ProcessingRunId, workerId, capability.Token, unit.AttemptCount,
            unit.LeaseExpiresAtUtc!.Value, unit.Deadline(policy.MaximumAnalysisDuration)!.Value, unit.Identity, tracks);
    }

    /// <summary>Every Vehicle Track of the run, in local-number order, with its accepted crops in rank order.</summary>
    internal async Task<IReadOnlyList<PlateLeaseTrack>> LeaseTracksAsync(Guid runId, CancellationToken cancellationToken)
    {
        var tracks = await db.Tracks.AsNoTracking()
            .Where(track => track.ProcessingRunId == runId && track.ObjectClass == ObjectClass.Vehicle)
            .OrderBy(track => track.LocalTrackNumber).ThenBy(track => track.Id)
            .Select(track => track.Id)
            .ToListAsync(cancellationToken);
        var crops = await (
                from track in db.Tracks.AsNoTracking()
                where track.ProcessingRunId == runId && track.ObjectClass == ObjectClass.Vehicle
                join observation in db.Observations.AsNoTracking() on track.Id equals observation.TrackId
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                orderby observation.EvidenceRank, observation.Id
                select new { observation.TrackId, observation.Id, observation.ObservationType, observation.EvidenceRank, artifact.SizeBytes, artifact.Sha256 })
            .ToListAsync(cancellationToken);
        var byTrack = crops.ToLookup(item => item.TrackId);
        return tracks
            .Select(trackId => new PlateLeaseTrack(trackId, byTrack[trackId]
                .Select(crop => new PlateLeaseObservation(crop.Id, RoleToken(crop.ObservationType), crop.EvidenceRank, crop.SizeBytes, crop.Sha256))
                .ToList()))
            .ToList();
    }

    // --- Heartbeat and failure --------------------------------------------------------------

    public async Task<PlateHeartbeatOutcome> HeartbeatAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, PlateLeasePolicy policy, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return new(null, new PlateRefusal(AnalysisNotFoundCode));
        try
        {
            unit.Heartbeat(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow(), policy);
        }
        catch (DomainValidationException exception)
        {
            return new(null, new PlateRefusal(exception.Code));
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(unit.LeaseExpiresAtUtc, null, unit.IdentityFingerprint);
    }

    public async Task<PlateFailureOutcome> FailAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable,
        string? failureMessage, PlateLeasePolicy policy, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return new(null, new PlateRefusal(AnalysisNotFoundCode));

        // An exact duplicate of the recorded transition answers with its recorded outcome and writes nothing.
        if (unit.IsRecordedFailureReplay(workerId, TokenMatches(leaseToken, unit.LastFailedTokenHash), attemptCount, failureCode, failureMessage))
        {
            await transaction.CommitAsync(cancellationToken);
            return new(unit.LastFailedOutcome, null);
        }

        PlateFailResult result;
        try
        {
            result = unit.FailAttempt(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, failureCode, retryable,
                failureMessage, timeProvider.GetUtcNow(), policy);
        }
        catch (DomainValidationException exception)
        {
            return new(null, new PlateRefusal(exception.Code));
        }

        db.PlateAttemptFailures.Add(result.Record);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(result.Outcome, null);
    }

    // --- Platform authority ------------------------------------------------------------------

    public async Task<PlateSweepResult> SweepAsync(PlateLeasePolicy policy, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var deadlineCutoffUtc = nowUtc - policy.MaximumAnalysisDuration;

        // Neither transition overtakes a live lease, including a publication window.
        var overdue = await db.PlateAnalyses.FromSqlInterpolated($"""
            SELECT * FROM plate_analyses
            WHERE status IN ('Queued', 'Running')
              AND first_claimed_at_utc IS NOT NULL
              AND first_claimed_at_utc <= {deadlineCutoffUtc}
              AND (lease_expires_at_utc IS NULL OR lease_expires_at_utc <= {nowUtc})
            ORDER BY first_claimed_at_utc, id
            FOR UPDATE SKIP LOCKED LIMIT {batchSize}
            """).ToListAsync(cancellationToken);
        overdue = overdue.Where(unit => unit.IsDeadlineEnforceable(nowUtc, policy)).ToList();
        foreach (var unit in overdue)
            unit.FailDeadlineExceeded(nowUtc, policy);

        var abandoned = await db.PlateAnalyses.FromSqlInterpolated($"""
            SELECT * FROM plate_analyses
            WHERE status IN ('Queued', 'Running')
              AND attempt_count >= {policy.MaximumAttempts}
              AND (lease_expires_at_utc IS NULL OR lease_expires_at_utc <= {nowUtc})
            ORDER BY lease_expires_at_utc NULLS FIRST, id
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
        return new PlateSweepResult(overdue.Count, exhausted);
    }

    // --- Evidence and upload authorisation ---------------------------------------------------

    public async Task<PlateEvidenceAuthorization> AuthorizeEvidenceReadAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, Guid observationId, CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        var unit = await db.PlateAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        if (unit is null) return new(null, new PlateRefusal(AnalysisNotFoundCode));
        if (unit.Status != PlateAnalysisStatus.Running) return new(null, new PlateRefusal(PlateAnalysis.NotRunningCode));
        if (!unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow()))
            return new(null, new PlateRefusal(PlateAnalysis.LeaseInvalidCode));

        // The IDOR fence: an accepted EvidenceCrop of an Observation of a Vehicle Track of this unit's run.
        var crop = await (
                from observation in db.Observations.AsNoTracking()
                where observation.Id == observationId
                join track in db.Tracks.AsNoTracking() on observation.TrackId equals track.Id
                where track.ProcessingRunId == unit.ProcessingRunId && track.ObjectClass == ObjectClass.Vehicle
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                select new { artifact.Id, artifact.StorageKey, artifact.MimeType, artifact.SizeBytes, artifact.Sha256 })
            .SingleOrDefaultAsync(cancellationToken);
        if (crop is null || !crop.StorageKey.StartsWith("evidence/", StringComparison.Ordinal))
            return new(null, new PlateRefusal(EvidenceForbiddenCode));

        return new(new PlateEvidenceGrant(unit.Id, unit.AttemptCount, observationId, crop.Id, crop.StorageKey, crop.MimeType,
            crop.SizeBytes, crop.Sha256, unit.LeaseExpiresAtUtc!.Value), null);
    }

    public async Task<PlateRefusal?> AuthorizeUploadAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        var unit = await db.PlateAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        if (unit is null) return new PlateRefusal(AnalysisNotFoundCode);
        if (unit.Status != PlateAnalysisStatus.Running) return new PlateRefusal(PlateAnalysis.NotRunningCode);
        return unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow())
            ? null
            : new PlateRefusal(PlateAnalysis.LeaseInvalidCode);
    }

    public async Task<DateTimeOffset?> RevalidateLeaseAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken)
    {
        var unit = await db.PlateAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        return unit is not null &&
               unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow())
            ? unit.LeaseExpiresAtUtc
            : null;
    }

    public Task<string?> ParametersJsonAsync(string identityFingerprint, CancellationToken cancellationToken) =>
        db.PlateIdentityActivations.AsNoTracking()
            .Where(x => x.Fingerprint == identityFingerprint)
            .OrderByDescending(x => x.ActivatedAtUtc)
            .Select(x => x.ParametersJson)
            .FirstOrDefaultAsync(cancellationToken);

    // --- Helpers ---------------------------------------------------------------------------

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

    private Task<PlateAnalysis?> LockAsync(Guid analysisId, CancellationToken cancellationToken) =>
        db.PlateAnalyses
            .FromSqlInterpolated($"SELECT * FROM plate_analyses WHERE id = {analysisId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);

    private async Task<IDbContextTransaction> BeginFreshAsync(CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        return await db.Database.BeginTransactionAsync(cancellationToken);
    }

    private static bool IsIdentityConflict(DbUpdateException exception) =>
        exception.InnerException is PostgresException
        {
            SqlState: PostgresErrorCodes.UniqueViolation,
            ConstraintName: "ux_plate_analyses_identity",
        };
}

public sealed class PlateReadinessReader(MaviDbContext db) : IPlateReadinessReader
{
    public async Task<PlateRunFacts?> ReadAsync(Guid processingRunId, string? preferredFingerprint, CancellationToken cancellationToken)
    {
        var run = await db.ProcessingRuns.AsNoTracking()
            .Where(x => x.Id == processingRunId)
            .Select(x => new { x.Status, x.VisibilitySequence, x.CompletedAtUtc })
            .SingleOrDefaultAsync(cancellationToken);
        if (run is null) return null;

        var hasVehicles = await db.Tracks.AsNoTracking()
            .AnyAsync(track => track.ProcessingRunId == processingRunId && track.ObjectClass == ObjectClass.Vehicle, cancellationToken);
        var analyses = await db.PlateAnalyses.AsNoTracking()
            .Where(x => x.ProcessingRunId == processingRunId)
            .Select(x => new PlateAnalysisFacts(x.Id, x.IdentityFingerprint, x.Status, x.AttemptCount, x.QueuedAtUtc, x.CompletedAtUtc, x.FailureCode))
            .ToListAsync(cancellationToken);
        DateTimeOffset? activatedAt = null;
        if (preferredFingerprint is not null)
        {
            var latest = await db.PlateIdentityActivations.AsNoTracking()
                .OrderByDescending(x => x.ActivatedAtUtc).ThenByDescending(x => x.Id)
                .Select(x => new { x.Fingerprint, x.ActivatedAtUtc })
                .FirstOrDefaultAsync(cancellationToken);
            if (latest?.Fingerprint == preferredFingerprint) activatedAt = latest.ActivatedAtUtc;
        }

        return new PlateRunFacts(run.Status == ProcessingRunStatus.Completed && run.VisibilitySequence != null, run.CompletedAtUtc,
            hasVehicles, activatedAt, analyses);
    }
}
