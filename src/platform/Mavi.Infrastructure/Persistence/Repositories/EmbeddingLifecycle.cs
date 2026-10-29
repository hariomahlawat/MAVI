using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Abstractions.Security;
using Mavi.Application.Modules.Embeddings;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Embeddings;
using Mavi.Domain.Common;
using Mavi.Domain.Embeddings;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence.Configurations;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Npgsql;
using Pgvector;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The embedding lifecycle against PostgreSQL (PoC S4; ADR-021 §3–§4), on the plate lifecycle's transaction
/// discipline: every transaction is short and locks its rows explicitly; none is open while a worker infers or
/// reads evidence. Person and Vehicle Tracks are leased. Nothing here locks, reads for update or writes a
/// ProcessingRun, Track, Observation or another role's unit: an embedding failure is confined to its unit.
/// </summary>
public sealed class EmbeddingLifecycle(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities) : IEmbeddingLifecycle
{
    // Serialises activation bookkeeping across hosts; distinct from every other advisory key ("MAVIEMBD").
    private const long ActivationLockKey = 0x4D415649_454D4244;

    public const string AnalysisNotFoundCode = "embedding_analysis_not_found";
    public const string EvidenceForbiddenCode = "embedding_evidence_forbidden";
    public const string CompletionInvalidCode = "embedding_completion_invalid";
    public const string CompletionConflictCode = "embedding_completion_conflict";
    public const string IdentityMismatchCode = "embedding_identity_mismatch";

    private static readonly JsonSerializerOptions ProvenanceJson = new(JsonSerializerDefaults.Web);

    // --- Activation and queueing ------------------------------------------------------

    public async Task<DateTimeOffset> EnsureActivationAsync(EmbeddingReleaseDefinition definition, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        await using var transaction = await BeginFreshAsync(cancellationToken);
        await db.Database.ExecuteSqlInterpolatedAsync($"SELECT pg_advisory_xact_lock({ActivationLockKey})", cancellationToken);
        var latest = await db.EmbeddingIdentityActivations.AsNoTracking()
            .OrderByDescending(x => x.ActivatedAtUtc).ThenByDescending(x => x.Id)
            .FirstOrDefaultAsync(cancellationToken);
        if (latest is not null && latest.Fingerprint == definition.Identity.Fingerprint)
        {
            await transaction.CommitAsync(cancellationToken);
            return latest.ActivatedAtUtc;
        }

        var activation = EmbeddingIdentityActivation.Create(definition.Identity.Fingerprint, definition.CanonicalIdentity, timeProvider.GetUtcNow());
        db.EmbeddingIdentityActivations.Add(activation);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return activation.ActivatedAtUtc;
    }

    public async Task<int> QueueEligibleAsync(
        EmbeddingReleaseDefinition definition, DateTimeOffset activatedAtUtc, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentOutOfRangeException.ThrowIfLessThan(batchSize, 1);
        var fingerprint = definition.Identity.Fingerprint;
        db.ChangeTracker.Clear();
        var classes = Classes(definition);
        var runIds = await EligibleRuns(classes)
            .Where(run => run.CompletedAtUtc >= activatedAtUtc)
            .Where(run => !db.EmbeddingAnalyses.Any(unit => unit.ProcessingRunId == run.Id && unit.IdentityFingerprint == fingerprint))
            .OrderBy(run => run.CompletedAtUtc).ThenBy(run => run.Id)
            .Select(run => run.Id)
            .Take(batchSize)
            .ToListAsync(cancellationToken);
        var (created, _) = await QueueRunsAsync(runIds, definition.Identity, cancellationToken);
        return created;
    }

    public async Task<EmbeddingReanalysisResult> RequestReanalysisAsync(
        EmbeddingReleaseDefinition definition, EmbeddingReanalysisRequest request, int maximumRuns, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(request);
        var ids = request.ProcessingRunIds;
        if (ids is null || ids.Count == 0 || ids.Count > maximumRuns || ids.Distinct().Count() != ids.Count || ids.Contains(Guid.Empty))
            return EmbeddingReanalysisResult.Refused("embedding_reanalysis_scope_invalid");

        db.ChangeTracker.Clear();
        var known = await db.ProcessingRuns.AsNoTracking().Where(run => ids.Contains(run.Id)).Select(run => run.Id).ToListAsync(cancellationToken);
        if (known.Count != ids.Count) return EmbeddingReanalysisResult.Refused("processing_run_not_found");
        var eligible = await EligibleRuns(Classes(definition)).Where(run => ids.Contains(run.Id)).Select(run => run.Id).ToListAsync(cancellationToken);
        var ordered = ids.Where(eligible.Contains).ToList();
        var (queued, already) = await QueueRunsAsync(ordered, definition.Identity, cancellationToken);
        return new EmbeddingReanalysisResult(ids.Count, queued, already, ids.Count - ordered.Count, null);
    }

    private static ObjectClass[] Classes(EmbeddingReleaseDefinition definition) =>
        definition.ObjectClasses.Select(name => Enum.Parse<ObjectClass>(name)).ToArray();

    /// <summary>Completed, visible runs with at least one Track of an embedded class.</summary>
    private IQueryable<ProcessingRun> EligibleRuns(ObjectClass[] classes) =>
        db.ProcessingRuns.AsNoTracking()
            .Where(run => run.Status == ProcessingRunStatus.Completed && run.VisibilitySequence != null && run.CompletedAtUtc != null)
            .Where(run => db.Tracks.Any(track => track.ProcessingRunId == run.Id && classes.Contains(track.ObjectClass)));

    private async Task<(int Created, int AlreadyQueued)> QueueRunsAsync(
        IReadOnlyList<Guid> runIds, EmbeddingIdentityFields identity, CancellationToken cancellationToken)
    {
        var created = 0;
        var already = 0;
        foreach (var runId in runIds)
        {
            db.ChangeTracker.Clear();
            if (await db.EmbeddingAnalyses.AsNoTracking().AnyAsync(unit => unit.ProcessingRunId == runId && unit.IdentityFingerprint == identity.Fingerprint, cancellationToken))
            {
                already++;
                continue;
            }

            db.EmbeddingAnalyses.Add(EmbeddingAnalysis.Queue(runId, identity, timeProvider.GetUtcNow()));
            try
            {
                await db.SaveChangesAsync(cancellationToken);
                created++;
            }
            catch (DbUpdateException exception) when (IsUniqueViolation(exception, "ux_embedding_analyses_identity"))
            {
                already++;
            }
        }

        db.ChangeTracker.Clear();
        return (created, already);
    }

    // --- Claim ----------------------------------------------------------------------------

    public async Task<EmbeddingLeaseGrant?> ClaimNextAsync(
        string workerId, EmbeddingReleaseDefinition definition, EmbeddingLeasePolicy policy, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(policy);
        var fingerprint = definition.Identity.Fingerprint;
        EmbeddingAnalysis unit;
        LeaseCapability capability;
        await using (var transaction = await BeginFreshAsync(cancellationToken))
        {
            var nowUtc = timeProvider.GetUtcNow();
            var deadlineCutoffUtc = nowUtc - policy.MaximumAnalysisDuration;
            var candidate = await db.EmbeddingAnalyses.FromSqlInterpolated($"""
                SELECT * FROM embedding_analyses
                WHERE identity_fingerprint = {fingerprint}
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

        var tracks = await LeaseTracksAsync(unit.ProcessingRunId, Classes(definition), cancellationToken);
        return new EmbeddingLeaseGrant(unit.Id, unit.ProcessingRunId, workerId, capability.Token, unit.AttemptCount,
            unit.LeaseExpiresAtUtc!.Value, unit.Deadline(policy.MaximumAnalysisDuration)!.Value, unit.Identity, tracks);
    }

    /// <summary>Every embedded-class Track of the run in local-number order, with its accepted crops in rank order.</summary>
    internal async Task<IReadOnlyList<EmbeddingLeaseTrack>> LeaseTracksAsync(Guid runId, ObjectClass[] classes, CancellationToken cancellationToken)
    {
        var tracks = await db.Tracks.AsNoTracking()
            .Where(track => track.ProcessingRunId == runId && classes.Contains(track.ObjectClass))
            .OrderBy(track => track.LocalTrackNumber).ThenBy(track => track.Id)
            .Select(track => new { track.Id, track.ObjectClass })
            .ToListAsync(cancellationToken);
        var crops = await (
                from track in db.Tracks.AsNoTracking()
                where track.ProcessingRunId == runId && classes.Contains(track.ObjectClass)
                join observation in db.Observations.AsNoTracking() on track.Id equals observation.TrackId
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                orderby observation.EvidenceRank, observation.Id
                select new { observation.TrackId, observation.Id, observation.ObservationType, observation.EvidenceRank, artifact.SizeBytes, artifact.Sha256 })
            .ToListAsync(cancellationToken);
        var byTrack = crops.ToLookup(item => item.TrackId);
        return tracks
            .Select(track => new EmbeddingLeaseTrack(track.Id, track.ObjectClass.ToString(), byTrack[track.Id]
                .Select(crop => new EmbeddingLeaseObservation(crop.Id, PlateLifecycle.RoleToken(crop.ObservationType), crop.EvidenceRank, crop.SizeBytes, crop.Sha256))
                .ToList()))
            .ToList();
    }

    // --- Heartbeat and failure --------------------------------------------------------------

    public async Task<EmbeddingHeartbeatOutcome> HeartbeatAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, EmbeddingLeasePolicy policy, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return new(null, new EmbeddingRefusal(AnalysisNotFoundCode));
        try
        {
            unit.Heartbeat(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow(), policy);
        }
        catch (DomainValidationException exception)
        {
            return new(null, new EmbeddingRefusal(exception.Code));
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(unit.LeaseExpiresAtUtc, null);
    }

    public async Task<EmbeddingFailureOutcome> FailAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable,
        string? failureMessage, EmbeddingLeasePolicy policy, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return new(null, new EmbeddingRefusal(AnalysisNotFoundCode));
        if (unit.IsRecordedFailureReplay(workerId, TokenMatches(leaseToken, unit.LastFailedTokenHash), attemptCount, failureCode, failureMessage))
        {
            await transaction.CommitAsync(cancellationToken);
            return new(unit.LastFailedOutcome, null);
        }

        EmbeddingFailOutcome outcome;
        try
        {
            outcome = unit.FailAttempt(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, failureCode, retryable,
                failureMessage, timeProvider.GetUtcNow(), policy);
        }
        catch (DomainValidationException exception)
        {
            return new(null, new EmbeddingRefusal(exception.Code));
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(outcome, null);
    }

    // --- Platform authority ------------------------------------------------------------------

    public async Task<EmbeddingSweepResult> SweepAsync(EmbeddingLeasePolicy policy, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var deadlineCutoffUtc = nowUtc - policy.MaximumAnalysisDuration;
        var overdue = await db.EmbeddingAnalyses.FromSqlInterpolated($"""
            SELECT * FROM embedding_analyses
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

        var abandoned = await db.EmbeddingAnalyses.FromSqlInterpolated($"""
            SELECT * FROM embedding_analyses
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

        var texts = await db.AppearanceQueryEmbeddings.FromSqlInterpolated($"""
            SELECT * FROM appearance_query_embeddings
            WHERE status = 'Running' AND attempt_count >= {AppearanceQueryEmbedding.MaximumAttempts}
              AND lease_expires_at_utc <= {nowUtc}
            ORDER BY lease_expires_at_utc, id
            FOR UPDATE SKIP LOCKED LIMIT {batchSize}
            """).ToListAsync(cancellationToken);
        foreach (var query in texts)
            query.FailExhausted(nowUtc);

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new EmbeddingSweepResult(overdue.Count, exhausted, texts.Count);
    }

    // --- Evidence --------------------------------------------------------------------------

    public async Task<EmbeddingEvidenceAuthorization> AuthorizeEvidenceReadAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, Guid observationId, CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        var unit = await db.EmbeddingAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        if (unit is null) return new(null, new EmbeddingRefusal(AnalysisNotFoundCode));
        if (unit.Status != EmbeddingAnalysisStatus.Running) return new(null, new EmbeddingRefusal(EmbeddingAnalysis.NotRunningCode));
        if (!unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow()))
            return new(null, new EmbeddingRefusal(EmbeddingAnalysis.LeaseInvalidCode));

        // The IDOR fence: an accepted EvidenceCrop of an Observation of a Person or Vehicle Track of this unit's run.
        var crop = await (
                from observation in db.Observations.AsNoTracking()
                where observation.Id == observationId
                join track in db.Tracks.AsNoTracking() on observation.TrackId equals track.Id
                where track.ProcessingRunId == unit.ProcessingRunId &&
                      (track.ObjectClass == ObjectClass.Person || track.ObjectClass == ObjectClass.Vehicle)
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                select new { artifact.StorageKey, artifact.MimeType, artifact.SizeBytes })
            .SingleOrDefaultAsync(cancellationToken);
        if (crop is null || !crop.StorageKey.StartsWith("evidence/", StringComparison.Ordinal))
            return new(null, new EmbeddingRefusal(EvidenceForbiddenCode));
        return new(new EmbeddingEvidenceGrant(crop.StorageKey, crop.MimeType, crop.SizeBytes, unit.LeaseExpiresAtUtc!.Value), null);
    }

    public async Task<DateTimeOffset?> RevalidateLeaseAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken)
    {
        var unit = await db.EmbeddingAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        return unit is not null &&
               unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow())
            ? unit.LeaseExpiresAtUtc
            : null;
    }

    // --- Completion ----------------------------------------------------------------------------

    /// <summary>
    /// One fenced publication (ADR-021 §3): under the unit's row lock, the exact-replay check, the active lease,
    /// the identity, the Track set and every vector are validated; the rows are written; then, under the
    /// exclusive visibility barrier, the sequence is allocated, the unit completes and — when its identity is the
    /// preferred one — the run's previous completed unit is superseded. Everything commits together.
    /// </summary>
    public async Task<EmbeddingCompletionResult> CompleteAsync(
        Guid analysisId, string leaseToken, byte[] body, EmbeddingCompleteRequest request, EmbeddingReleaseDefinition? preferred,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(body);
        ArgumentNullException.ThrowIfNull(request);
        if (request.AnalysisId != analysisId || !WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId) ||
            request.AttemptCount is not ({ } attempt and >= 1) || request.Provenance is not { } provenance || request.Tracks is not { } results ||
            results.Count > EmbeddingContractRules.MaximumAnalysisTracks || !IsValidProvenance(provenance))
            return EmbeddingCompletionResult.Refused(400, CompletionInvalidCode);

        var digest = Convert.ToHexString(SHA256.HashData(body)).ToLowerInvariant();
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return EmbeddingCompletionResult.Refused(404, AnalysisNotFoundCode);
        var tokenMatches = TokenMatches(leaseToken, unit.LeaseTokenHash);

        if (unit.IsFactBearing)
        {
            await transaction.RollbackAsync(cancellationToken);
            if (!unit.CanAuthenticateCompletionReplay(workerId, tokenMatches, attempt))
                return EmbeddingCompletionResult.Refused(409, EmbeddingAnalysis.StaleAttemptCode);
            return string.Equals(unit.CompletionDigest, digest, StringComparison.Ordinal)
                ? Published(unit)
                : EmbeddingCompletionResult.Refused(409, CompletionConflictCode);
        }

        var nowUtc = timeProvider.GetUtcNow();
        if (unit.Status != EmbeddingAnalysisStatus.Running) return EmbeddingCompletionResult.Refused(409, EmbeddingAnalysis.NotRunningCode);
        if (!unit.HoldsActiveLease(workerId, tokenMatches, attempt, nowUtc))
            return EmbeddingCompletionResult.Refused(409, unit.IsOwnedBy(workerId, tokenMatches, attempt)
                ? EmbeddingAnalysis.LeaseInvalidCode
                : EmbeddingAnalysis.StaleAttemptCode);
        if (!string.Equals(provenance.IdentityFingerprint, unit.IdentityFingerprint, StringComparison.Ordinal))
            return EmbeddingCompletionResult.Refused(422, IdentityMismatchCode);
        // Units are only leased under the running release's identity, whose profile names the leased classes. A
        // release changed between lease and completion cannot reproduce the lease: the attempt is refused and the
        // unit ends by lease expiry and exhaustion, never by publishing a Track set it cannot verify.
        if (preferred is null || !string.Equals(preferred.Identity.Fingerprint, unit.IdentityFingerprint, StringComparison.Ordinal))
            return EmbeddingCompletionResult.Refused(409, IdentityMismatchCode);

        var leased = await LeaseTracksAsync(unit.ProcessingRunId, Classes(preferred), cancellationToken);
        var rows = BuildRows(unit, leased, results);
        if (rows is null) return EmbeddingCompletionResult.Refused(422, CompletionInvalidCode);

        try
        {
            db.TrackEmbeddings.AddRange(rows);
            await db.SaveChangesAsync(cancellationToken);

            // The run's other units, in id order, before the barrier: supersession must see a stable set.
            var siblings = await db.EmbeddingAnalyses.FromSqlInterpolated($"""
                SELECT * FROM embedding_analyses WHERE processing_run_id = {unit.ProcessingRunId} AND id <> {unit.Id}
                ORDER BY id FOR UPDATE
                """).ToListAsync(cancellationToken);
            await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, cancellationToken);
            var sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
            var embedded = rows.Count(row => row.Outcome == "Embedded");
            unit.Complete(workerId, tokenMatches, attempt, nowUtc, new EmbeddingCompletion(digest, sequence,
                JsonSerializer.Serialize(provenance, ProvenanceJson), embedded, rows.Count - embedded), isPreferred: true);
            // Currency moves only on a successful completion of the preferred identity; superseded facts stay as committed.
            foreach (var sibling in siblings.Where(x => x.Status == EmbeddingAnalysisStatus.Completed))
                sibling.Supersede();

            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            return Published(unit);
        }
        catch (DomainValidationException exception)
        {
            await transaction.RollbackAsync(CancellationToken.None);
            return EmbeddingCompletionResult.Refused(409, exception.Code);
        }
        catch (Exception exception) when (exception is DbUpdateException or PostgresException)
        {
            await transaction.RollbackAsync(CancellationToken.None);
            return EmbeddingCompletionResult.Refused(503, "embedding_persistence_failed");
        }
    }

    /// <summary>
    /// The rows of one completion, or null when it does not describe exactly the leased Tracks in lease order with
    /// valid outcomes: an embedded Track names only its own leased Observations and a valid vector of the unit's
    /// dimension; <c>no_evidence</c> only for a Track with no accepted crop, the other reasons only for one with crops.
    /// </summary>
    internal static List<TrackEmbeddingRow>? BuildRows(
        EmbeddingAnalysis unit, IReadOnlyList<EmbeddingLeaseTrack> leased, IReadOnlyList<EmbeddingTrackResultContract> results)
    {
        if (results.Count != leased.Count) return null;
        var rows = new List<TrackEmbeddingRow>(results.Count);
        for (var index = 0; index < results.Count; index++)
        {
            var result = results[index];
            var track = leased[index];
            if (result is null || result.TrackId != track.TrackId) return null;
            var observations = track.Observations.Select(item => item.ObservationId).ToHashSet();
            if (result.Outcome == EmbeddingContractRules.OutcomeEmbedded)
            {
                if (result.Reason is not null || result.SourceObservationIds is not { Count: >= 1 } sources ||
                    sources.Distinct().Count() != sources.Count || !sources.All(observations.Contains) ||
                    EmbeddingContractRules.TryDecodeVector(result.Embedding, unit.Dimension) is not { } vector)
                    return null;
                rows.Add(new TrackEmbeddingRow
                {
                    AnalysisId = unit.Id,
                    TrackId = track.TrackId,
                    ProcessingRunId = unit.ProcessingRunId,
                    Outcome = "Embedded",
                    Embedding = new Vector(vector),
                    SourceObservationIds = [.. sources],
                });
            }
            else if (result.Outcome == EmbeddingContractRules.OutcomeUnavailable)
            {
                if (result.Embedding is not null || result.SourceObservationIds is { Count: > 0 } ||
                    result.Reason is not { } reason || !EmbeddingContractRules.UnavailableReasons.Contains(reason) ||
                    (reason == EmbeddingContractRules.ReasonNoEvidence) != (observations.Count == 0))
                    return null;
                rows.Add(new TrackEmbeddingRow
                {
                    AnalysisId = unit.Id,
                    TrackId = track.TrackId,
                    ProcessingRunId = unit.ProcessingRunId,
                    Outcome = "Unavailable",
                    UnavailableReason = reason,
                    SourceObservationIds = [],
                });
            }
            else
            {
                return null;
            }
        }

        return rows;
    }

    private static bool IsValidProvenance(EmbeddingProvenanceContract provenance) =>
        provenance.RoleId == EmbeddingContractRules.RoleId &&
        EmbeddingContractRules.IsCanonicalSha256(provenance.IdentityFingerprint) &&
        provenance.RuntimeProfileId is { Length: >= 1 and <= 64 } &&
        provenance.RuntimeVariant is { Length: >= 1 and <= 64 } &&
        provenance.ExecutionProvider is { } provider && EmbeddingContractRules.ExecutionProviders.Contains(provider) &&
        provenance.ActualDevice is { Length: >= 3 and <= 8 } device && (device == "cpu" || device.StartsWith("cuda:", StringComparison.Ordinal)) &&
        provenance.DeviceResolutionReason is { Length: >= 1 and <= 64 } &&
        provenance.OnnxRuntimeVersion is { Length: >= 1 and <= 32 } &&
        provenance.WorkerVersion is { Length: >= 1 and <= 64 };

    private static EmbeddingCompletionResult Published(EmbeddingAnalysis unit) => new(
        unit.Status == EmbeddingAnalysisStatus.Completed ? "completed" : "superseded", 200, null, unit.ProcessingRunId,
        unit.CompletedAtUtc, unit.TracksEmbedded, unit.TracksUnavailable);

    // --- Appearance text queries ------------------------------------------------------------

    public async Task<AppearanceQueryEmbedding> RequestTextAsync(string identityFingerprint, string normalisedText, CancellationToken cancellationToken)
    {
        var textSha = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(normalisedText))).ToLowerInvariant();
        db.ChangeTracker.Clear();
        var existing = await db.AppearanceQueryEmbeddings.AsNoTracking()
            .SingleOrDefaultAsync(x => x.IdentityFingerprint == identityFingerprint && x.TextSha256 == textSha, cancellationToken);
        if (existing is not null) return existing;

        var created = AppearanceQueryEmbedding.Request(identityFingerprint, normalisedText, textSha, timeProvider.GetUtcNow());
        db.AppearanceQueryEmbeddings.Add(created);
        try
        {
            await db.SaveChangesAsync(cancellationToken);
            return created;
        }
        catch (DbUpdateException exception) when (IsUniqueViolation(exception, "ux_appearance_query_embeddings_text"))
        {
            db.ChangeTracker.Clear();
            return await db.AppearanceQueryEmbeddings.AsNoTracking()
                .SingleAsync(x => x.IdentityFingerprint == identityFingerprint && x.TextSha256 == textSha, cancellationToken);
        }
    }

    public Task<AppearanceQueryEmbedding?> GetTextAsync(Guid queryId, CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        return db.AppearanceQueryEmbeddings.AsNoTracking().SingleOrDefaultAsync(x => x.Id == queryId, cancellationToken);
    }

    public async Task<EmbeddingTextLeaseGrant?> ClaimTextAsync(
        string workerId, string identityFingerprint, TimeSpan leaseDuration, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var candidate = await db.AppearanceQueryEmbeddings.FromSqlInterpolated($"""
            SELECT * FROM appearance_query_embeddings
            WHERE identity_fingerprint = {identityFingerprint}
              AND attempt_count < {AppearanceQueryEmbedding.MaximumAttempts}
              AND (status = 'Pending' OR (status = 'Running' AND lease_expires_at_utc <= {nowUtc}))
            ORDER BY requested_at_utc, id
            FOR UPDATE SKIP LOCKED LIMIT 1
            """).SingleOrDefaultAsync(cancellationToken);
        if (candidate is null || !candidate.CanClaim(nowUtc))
        {
            await transaction.CommitAsync(cancellationToken);
            return null;
        }

        var capability = leaseCapabilities.Create();
        candidate.Claim(workerId, capability.Hash, nowUtc, leaseDuration);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new EmbeddingTextLeaseGrant(candidate.Id, workerId, capability.Token, candidate.AttemptCount,
            candidate.LeaseExpiresAtUtc!.Value, candidate.IdentityFingerprint, candidate.Text);
    }

    public async Task<EmbeddingRefusal?> CompleteTextAsync(
        Guid queryId, string workerId, string leaseToken, int attemptCount, float[] embedding, int dimension, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var query = await db.AppearanceQueryEmbeddings
            .FromSqlInterpolated($"SELECT * FROM appearance_query_embeddings WHERE id = {queryId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);
        if (query is null) return new EmbeddingRefusal(AppearanceQueryEmbedding.NotFoundCode);
        var tokenMatches = TokenMatches(leaseToken, query.LeaseTokenHash);
        if (query.IsCompletionReplay(workerId, tokenMatches, attemptCount))
        {
            await transaction.CommitAsync(cancellationToken);
            return query.Embedding is { } stored && stored.AsSpan().SequenceEqual(embedding) ? null : new EmbeddingRefusal(CompletionConflictCode);
        }

        try
        {
            query.Complete(workerId, tokenMatches, attemptCount, embedding, dimension, timeProvider.GetUtcNow());
        }
        catch (DomainValidationException exception)
        {
            return new EmbeddingRefusal(exception.Code);
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return null;
    }

    public async Task<EmbeddingFailureOutcome> FailTextAsync(
        Guid queryId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var query = await db.AppearanceQueryEmbeddings
            .FromSqlInterpolated($"SELECT * FROM appearance_query_embeddings WHERE id = {queryId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);
        if (query is null) return new(null, new EmbeddingRefusal(AppearanceQueryEmbedding.NotFoundCode));
        try
        {
            query.Fail(workerId, TokenMatches(leaseToken, query.LeaseTokenHash), attemptCount, failureCode, retryable, timeProvider.GetUtcNow());
        }
        catch (DomainValidationException exception)
        {
            return new(null, new EmbeddingRefusal(exception.Code));
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(query.Status == AppearanceQueryStatus.Pending ? EmbeddingFailOutcome.Requeued : EmbeddingFailOutcome.Failed, null);
    }

    // --- Helpers ---------------------------------------------------------------------------

    private bool TokenMatches(string leaseToken, byte[]? expectedHash) =>
        expectedHash is not null && leaseCapabilities.Matches(leaseToken, expectedHash);

    private Task<EmbeddingAnalysis?> LockAsync(Guid analysisId, CancellationToken cancellationToken) =>
        db.EmbeddingAnalyses
            .FromSqlInterpolated($"SELECT * FROM embedding_analyses WHERE id = {analysisId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);

    private async Task<IDbContextTransaction> BeginFreshAsync(CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        return await db.Database.BeginTransactionAsync(cancellationToken);
    }

    private static bool IsUniqueViolation(DbUpdateException exception, string constraint) =>
        exception.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation } postgres &&
        postgres.ConstraintName == constraint;
}
