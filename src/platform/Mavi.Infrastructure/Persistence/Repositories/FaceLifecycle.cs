using System.Security.Cryptography;
using System.Text.Json;
using Mavi.Application.Abstractions.Security;
using Mavi.Application.Modules.Faces;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Faces;
using Mavi.Domain.Common;
using Mavi.Domain.Faces;
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
/// The face lifecycle against PostgreSQL (PoC S6; ADR-022 §3–§5), on the embedding lifecycle's transaction
/// discipline: every transaction is short and locks its rows explicitly; none is open while a worker infers or
/// reads evidence. Only Person Tracks of runs of opted-in cameras are leased. Nothing here locks, reads for update or
/// writes a ProcessingRun, Track, Observation or another role's unit: a face failure is confined to its unit.
/// </summary>
public sealed class FaceLifecycle(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities) : IFaceLifecycle
{
    public const string AnalysisNotFoundCode = "face_analysis_not_found";
    public const string EvidenceForbiddenCode = "face_evidence_forbidden";
    public const string CompletionInvalidCode = "face_completion_invalid";
    public const string CompletionConflictCode = "face_completion_conflict";
    public const string IdentityMismatchCode = "face_identity_mismatch";
    public const string QueryImageMissingCode = "face_query_image_missing";

    public const string OutcomeObserved = "Observed";
    public const string OutcomeUnknown = "Unknown";

    private static readonly JsonSerializerOptions ProvenanceJson = new(JsonSerializerDefaults.Web);

    // --- Queueing -----------------------------------------------------------------------------

    public async Task<int> QueueEligibleAsync(FaceReleaseDefinition definition, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentOutOfRangeException.ThrowIfLessThan(batchSize, 1);
        var fingerprint = definition.Identity.Fingerprint;
        db.ChangeTracker.Clear();
        // Opt-in is explicit and per camera (ADR-022 §3), so every visible run of an opted-in camera is eligible,
        // not only those completed after an activation.
        var runs = await (
                from run in db.ProcessingRuns.AsNoTracking()
                join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
                join camera in db.Cameras.AsNoTracking() on video.CameraId equals camera.Id
                where camera.FaceAnalysisEnabled &&
                      run.Status == ProcessingRunStatus.Completed && run.VisibilitySequence != null && run.CompletedAtUtc != null &&
                      db.Tracks.Any(track => track.ProcessingRunId == run.Id && track.ObjectClass == ObjectClass.Person) &&
                      !db.FaceAnalyses.Any(unit => unit.ProcessingRunId == run.Id && unit.IdentityFingerprint == fingerprint)
                orderby run.CompletedAtUtc, run.Id
                select new { run.Id, CameraId = camera.Id })
            .Take(batchSize)
            .ToListAsync(cancellationToken);
        var created = 0;
        foreach (var run in runs)
        {
            db.ChangeTracker.Clear();
            db.FaceAnalyses.Add(FaceAnalysis.Queue(run.Id, run.CameraId, definition.Identity, timeProvider.GetUtcNow()));
            try
            {
                await db.SaveChangesAsync(cancellationToken);
                created++;
            }
            catch (DbUpdateException exception) when (IsUniqueViolation(exception, "ux_face_analyses_identity"))
            {
                // A concurrent host queued it first.
            }
        }

        db.ChangeTracker.Clear();
        return created;
    }

    // --- Claim ----------------------------------------------------------------------------

    public async Task<FaceLeaseGrant?> ClaimNextAsync(
        string workerId, FaceReleaseDefinition definition, FaceLeasePolicy policy, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(policy);
        var fingerprint = definition.Identity.Fingerprint;
        FaceAnalysis unit;
        LeaseCapability capability;
        await using (var transaction = await BeginFreshAsync(cancellationToken))
        {
            var nowUtc = timeProvider.GetUtcNow();
            var deadlineCutoffUtc = nowUtc - policy.MaximumAnalysisDuration;
            var candidate = await db.FaceAnalyses.FromSqlInterpolated($"""
                SELECT * FROM face_analyses
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

        var tracks = await LeaseTracksAsync(unit.ProcessingRunId, cancellationToken);
        return new FaceLeaseGrant(unit.Id, unit.ProcessingRunId, workerId, capability.Token, unit.AttemptCount,
            unit.LeaseExpiresAtUtc!.Value, unit.Deadline(policy.MaximumAnalysisDuration)!.Value, unit.Identity, tracks);
    }

    /// <summary>Every Person Track of the run in local-number order, with its accepted crops in rank order.</summary>
    internal async Task<IReadOnlyList<FaceLeaseTrack>> LeaseTracksAsync(Guid runId, CancellationToken cancellationToken)
    {
        var tracks = await db.Tracks.AsNoTracking()
            .Where(track => track.ProcessingRunId == runId && track.ObjectClass == ObjectClass.Person)
            .OrderBy(track => track.LocalTrackNumber).ThenBy(track => track.Id)
            .Select(track => track.Id)
            .ToListAsync(cancellationToken);
        var crops = await (
                from track in db.Tracks.AsNoTracking()
                where track.ProcessingRunId == runId && track.ObjectClass == ObjectClass.Person
                join observation in db.Observations.AsNoTracking() on track.Id equals observation.TrackId
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                orderby observation.EvidenceRank, observation.Id
                select new { observation.TrackId, observation.Id, observation.ObservationType, observation.EvidenceRank, artifact.SizeBytes, artifact.Sha256 })
            .ToListAsync(cancellationToken);
        var byTrack = crops.ToLookup(item => item.TrackId);
        return tracks
            .Select(trackId => new FaceLeaseTrack(trackId, byTrack[trackId]
                .Select(crop => new FaceLeaseObservation(crop.Id, PlateLifecycle.RoleToken(crop.ObservationType), crop.EvidenceRank, crop.SizeBytes, crop.Sha256))
                .ToList()))
            .ToList();
    }

    // --- Heartbeat and failure --------------------------------------------------------------

    public async Task<FaceHeartbeatOutcome> HeartbeatAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, FaceLeasePolicy policy, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return new(null, new FaceRefusal(AnalysisNotFoundCode));
        try
        {
            unit.Heartbeat(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow(), policy);
        }
        catch (DomainValidationException exception)
        {
            return new(null, new FaceRefusal(exception.Code));
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(unit.LeaseExpiresAtUtc, null);
    }

    public async Task<FaceFailureOutcome> FailAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable,
        string? failureMessage, FaceLeasePolicy policy, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return new(null, new FaceRefusal(AnalysisNotFoundCode));
        if (unit.IsRecordedFailureReplay(workerId, TokenMatches(leaseToken, unit.LastFailedTokenHash), attemptCount, failureCode, failureMessage))
        {
            await transaction.CommitAsync(cancellationToken);
            return new(unit.LastFailedOutcome, null);
        }

        FaceFailOutcome outcome;
        try
        {
            outcome = unit.FailAttempt(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, failureCode, retryable,
                failureMessage, timeProvider.GetUtcNow(), policy);
        }
        catch (DomainValidationException exception)
        {
            return new(null, new FaceRefusal(exception.Code));
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(outcome, null);
    }

    // --- Platform authority ------------------------------------------------------------------

    public async Task<FaceSweepResult> SweepAsync(FaceLeasePolicy policy, int batchSize, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(policy);
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var deadlineCutoffUtc = nowUtc - policy.MaximumAnalysisDuration;
        var overdue = await db.FaceAnalyses.FromSqlInterpolated($"""
            SELECT * FROM face_analyses
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

        var abandoned = await db.FaceAnalyses.FromSqlInterpolated($"""
            SELECT * FROM face_analyses
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

        // Transient query images (ADR-022 §5): an exhausted query fails; any image of a finished query, or older
        // than its lifetime, is erased; a query past its purge time is deleted with its faces and vectors.
        var imageCutoffUtc = nowUtc - FaceQuery.ImageLifetime;
        var queries = await db.FaceQueries.FromSqlInterpolated($"""
            SELECT * FROM face_queries
            WHERE image IS NOT NULL
              AND (status IN ('Completed', 'Failed') OR created_at_utc <= {imageCutoffUtc}
                   OR (status = 'Running' AND attempt_count >= {FaceQuery.MaximumAttempts} AND lease_expires_at_utc <= {nowUtc}))
            ORDER BY created_at_utc, id
            FOR UPDATE SKIP LOCKED LIMIT {batchSize}
            """).ToListAsync(cancellationToken);
        var queriesExhausted = 0;
        var erased = 0;
        foreach (var query in queries)
        {
            if (query.IsExhausted(nowUtc))
            {
                query.FailExhausted(nowUtc);
                queriesExhausted++;
                erased++;
            }
            else if (query.IsImageExpired(nowUtc))
            {
                query.EraseImage(nowUtc);
                erased++;
            }
        }

        await db.SaveChangesAsync(cancellationToken);
        var purged = await db.FaceQueries.Where(query => query.PurgeAfterUtc <= nowUtc).ExecuteDeleteAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new FaceSweepResult(overdue.Count, exhausted, queriesExhausted, erased, purged);
    }

    // --- Evidence --------------------------------------------------------------------------

    public async Task<FaceEvidenceAuthorization> AuthorizeEvidenceReadAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, Guid observationId, CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        var unit = await db.FaceAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        if (unit is null) return new(null, new FaceRefusal(AnalysisNotFoundCode));
        if (unit.Status != FaceAnalysisStatus.Running) return new(null, new FaceRefusal(FaceAnalysis.NotRunningCode));
        if (!unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow()))
            return new(null, new FaceRefusal(FaceAnalysis.LeaseInvalidCode));

        // The IDOR fence: an accepted EvidenceCrop of an Observation of a Person Track of this unit's run.
        var crop = await (
                from observation in db.Observations.AsNoTracking()
                where observation.Id == observationId
                join track in db.Tracks.AsNoTracking() on observation.TrackId equals track.Id
                where track.ProcessingRunId == unit.ProcessingRunId && track.ObjectClass == ObjectClass.Person
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                select new { artifact.StorageKey, artifact.MimeType, artifact.SizeBytes })
            .SingleOrDefaultAsync(cancellationToken);
        if (crop is null || !crop.StorageKey.StartsWith("evidence/", StringComparison.Ordinal))
            return new(null, new FaceRefusal(EvidenceForbiddenCode));
        return new(new FaceEvidenceGrant(crop.StorageKey, crop.MimeType, crop.SizeBytes, unit.LeaseExpiresAtUtc!.Value), null);
    }

    public async Task<DateTimeOffset?> RevalidateLeaseAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken)
    {
        var unit = await db.FaceAnalyses.AsNoTracking().SingleOrDefaultAsync(x => x.Id == analysisId, cancellationToken);
        return unit is not null &&
               unit.HoldsActiveLease(workerId, TokenMatches(leaseToken, unit.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow())
            ? unit.LeaseExpiresAtUtc
            : null;
    }

    // --- Completion ----------------------------------------------------------------------------

    /// <summary>
    /// One fenced publication: under the unit's row lock, the exact-replay check, the active lease, the identity, the
    /// Track set and every face are validated; the rows are written; then, under the exclusive visibility barrier,
    /// the sequence is allocated and the unit completes. Every other fact-bearing unit of the run is deleted in the
    /// same transaction: no face history is kept (ADR-022 §5). Everything commits together.
    /// </summary>
    public async Task<FaceCompletionResult> CompleteAsync(
        Guid analysisId, string leaseToken, byte[] body, FaceCompleteRequest request, FaceReleaseDefinition? preferred,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(body);
        ArgumentNullException.ThrowIfNull(request);
        if (request.AnalysisId != analysisId || !WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId) ||
            request.AttemptCount is not ({ } attempt and >= 1) || request.Provenance is not { } provenance || request.Tracks is not { } results ||
            results.Count > FaceContractRules.MaximumAnalysisTracks || !IsValidProvenance(provenance))
            return FaceCompletionResult.Refused(400, CompletionInvalidCode);

        var digest = Convert.ToHexString(SHA256.HashData(body)).ToLowerInvariant();
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var unit = await LockAsync(analysisId, cancellationToken);
        if (unit is null) return FaceCompletionResult.Refused(404, AnalysisNotFoundCode);
        var tokenMatches = TokenMatches(leaseToken, unit.LeaseTokenHash);

        if (unit.IsFactBearing)
        {
            await transaction.RollbackAsync(cancellationToken);
            if (!unit.CanAuthenticateCompletionReplay(workerId, tokenMatches, attempt))
                return FaceCompletionResult.Refused(409, FaceAnalysis.StaleAttemptCode);
            return string.Equals(unit.CompletionDigest, digest, StringComparison.Ordinal)
                ? await PublishedAsync(unit, cancellationToken)
                : FaceCompletionResult.Refused(409, CompletionConflictCode);
        }

        var nowUtc = timeProvider.GetUtcNow();
        if (unit.Status != FaceAnalysisStatus.Running) return FaceCompletionResult.Refused(409, FaceAnalysis.NotRunningCode);
        if (!unit.HoldsActiveLease(workerId, tokenMatches, attempt, nowUtc))
            return FaceCompletionResult.Refused(409, unit.IsOwnedBy(workerId, tokenMatches, attempt)
                ? FaceAnalysis.LeaseInvalidCode
                : FaceAnalysis.StaleAttemptCode);
        if (!string.Equals(provenance.IdentityFingerprint, unit.IdentityFingerprint, StringComparison.Ordinal))
            return FaceCompletionResult.Refused(422, IdentityMismatchCode);
        if (preferred is null || !string.Equals(preferred.Identity.Fingerprint, unit.IdentityFingerprint, StringComparison.Ordinal))
            return FaceCompletionResult.Refused(409, IdentityMismatchCode);

        var leased = await LeaseTracksAsync(unit.ProcessingRunId, cancellationToken);
        var rows = BuildRows(unit, preferred, leased, results);
        if (rows is null) return FaceCompletionResult.Refused(422, CompletionInvalidCode);

        try
        {
            db.FaceTrackOutcomes.AddRange(rows.Outcomes);
            db.FaceObservations.AddRange(rows.Faces);
            await db.SaveChangesAsync(cancellationToken);
            db.FaceEmbeddings.AddRange(rows.Embeddings);
            await db.SaveChangesAsync(cancellationToken);

            var siblings = await db.FaceAnalyses.FromSqlInterpolated($"""
                SELECT * FROM face_analyses WHERE processing_run_id = {unit.ProcessingRunId} AND id <> {unit.Id}
                ORDER BY id FOR UPDATE
                """).ToListAsync(cancellationToken);
            await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, cancellationToken);
            var sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
            var observed = rows.Outcomes.Count(row => row.Outcome == OutcomeObserved);
            unit.Complete(workerId, tokenMatches, attempt, nowUtc, new FaceCompletion(digest, sequence,
                JsonSerializer.Serialize(provenance, ProvenanceJson), observed, rows.Outcomes.Count - observed), isPreferred: true);
            // No face history (ADR-022 §5): the run's earlier published analyses go, with their faces and vectors.
            db.FaceAnalyses.RemoveRange(siblings.Where(x => x.IsFactBearing));

            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            return new FaceCompletionResult("completed", 200, null, unit.ProcessingRunId, unit.CompletedAtUtc, observed,
                rows.Outcomes.Count - observed, rows.Embeddings.Count);
        }
        catch (DomainValidationException exception)
        {
            await transaction.RollbackAsync(CancellationToken.None);
            return FaceCompletionResult.Refused(409, exception.Code);
        }
        catch (Exception exception) when (exception is DbUpdateException or PostgresException)
        {
            await transaction.RollbackAsync(CancellationToken.None);
            return FaceCompletionResult.Refused(503, "face_persistence_failed");
        }
    }

    internal sealed record FaceRows(List<FaceTrackOutcomeRow> Outcomes, List<FaceObservationRow> Faces, List<FaceEmbeddingRow> Embeddings);

    /// <summary>
    /// The rows of one completion, or null when it does not describe exactly the leased Tracks in lease order with
    /// valid faces: each face on one of its Track's leased Observations, at or above the detector threshold, usable
    /// exactly when its shorter side reaches the profile's minimum, with a vector of the unit's dimension exactly when
    /// usable; <c>observed</c> exactly when a face is usable; each Unknown reason consistent with the evidence and faces.
    /// </summary>
    internal static FaceRows? BuildRows(
        FaceAnalysis unit, FaceReleaseDefinition definition, IReadOnlyList<FaceLeaseTrack> leased, IReadOnlyList<FaceTrackResultContract> results)
    {
        if (results.Count != leased.Count) return null;
        var outcomes = new List<FaceTrackOutcomeRow>(results.Count);
        var faces = new List<FaceObservationRow>();
        var embeddings = new List<FaceEmbeddingRow>();
        for (var index = 0; index < results.Count; index++)
        {
            var result = results[index];
            var track = leased[index];
            if (result is null || result.TrackId != track.TrackId || result.Faces is not { } detections) return null;
            var observations = track.Observations.Select(item => item.ObservationId).ToHashSet();
            var trackFaces = new List<(FaceObservationRow Row, float[]? Vector)>();
            foreach (var detection in detections)
            {
                if (ParseFace(detection, definition, unit.Dimension, requireObservation: true, allowThumbnail: false) is not { } parsed ||
                    !observations.Contains(parsed.ObservationId!.Value))
                    return null;
                trackFaces.Add((new FaceObservationRow
                {
                    Id = Guid.CreateVersion7(),
                    AnalysisId = unit.Id,
                    TrackId = track.TrackId,
                    ObservationId = parsed.ObservationId.Value,
                    BoxX = (float)parsed.X,
                    BoxY = (float)parsed.Y,
                    BoxWidth = (float)parsed.Width,
                    BoxHeight = (float)parsed.Height,
                    Landmarks = parsed.Landmarks,
                    Score = (float)parsed.Score,
                    MinSide = (float)Math.Min(parsed.Width, parsed.Height),
                    Usable = parsed.Usable,
                }, parsed.Vector));
            }

            if (trackFaces.GroupBy(face => face.Row.ObservationId).Any(group => group.Count() > FaceContractRules.MaximumFacesPerCrop))
                return null;

            var anyUsable = trackFaces.Any(face => face.Row.Usable);
            if (result.Outcome == FaceContractRules.OutcomeObserved)
            {
                if (result.Reason is not null || !anyUsable) return null;
                outcomes.Add(new FaceTrackOutcomeRow { AnalysisId = unit.Id, TrackId = track.TrackId, Outcome = OutcomeObserved });
            }
            else if (result.Outcome == FaceContractRules.OutcomeUnknown)
            {
                if (anyUsable || result.Reason is not { } reason || !FaceContractRules.UnknownReasons.Contains(reason)) return null;
                var consistent = reason switch
                {
                    FaceContractRules.ReasonNoEvidence => observations.Count == 0,
                    FaceContractRules.ReasonFaceTooSmall => observations.Count > 0 && trackFaces.Count > 0,
                    _ => observations.Count > 0 && trackFaces.Count == 0,
                };
                if (!consistent) return null;
                outcomes.Add(new FaceTrackOutcomeRow { AnalysisId = unit.Id, TrackId = track.TrackId, Outcome = OutcomeUnknown, Reason = reason });
            }
            else
            {
                return null;
            }

            foreach (var (row, vector) in trackFaces)
            {
                faces.Add(row);
                if (vector is not null)
                    embeddings.Add(new FaceEmbeddingRow { FaceObservationId = row.Id, Embedding = new Vector(vector) });
            }
        }

        return new FaceRows(outcomes, faces, embeddings);
    }

    internal sealed record ParsedFace(
        Guid? ObservationId, double X, double Y, double Width, double Height, float[] Landmarks, double Score, bool Usable,
        float[]? Vector, byte[]? Thumbnail);

    /// <summary>One face, validated against the profile; null when it is not a face this release could have produced.</summary>
    internal static ParsedFace? ParseFace(
        FaceDetectionContract? detection, FaceReleaseDefinition definition, int dimension, bool requireObservation, bool allowThumbnail)
    {
        if (detection is null || detection.Box is not { } box || detection.Usable is not { } usable || detection.Score is not { } score ||
            requireObservation != (detection.ObservationId is not null) ||
            !FaceContractRules.IsCoordinate(box.X) || !FaceContractRules.IsCoordinate(box.Y) ||
            !FaceContractRules.IsCoordinate(box.Width) || !FaceContractRules.IsCoordinate(box.Height) ||
            box.Width!.Value <= 0 || box.Height!.Value <= 0 ||
            !double.IsFinite(score) || score > 1 || score < definition.DetectorScoreThreshold ||
            detection.Landmarks is not { Count: 5 } points)
            return null;

        var landmarks = new float[10];
        for (var index = 0; index < 5; index++)
        {
            if (points[index] is not { Count: 2 } point ||
                !point.All(value => double.IsFinite(value) && Math.Abs(value) <= FaceContractRules.MaximumCoordinate))
                return null;
            landmarks[2 * index] = (float)point[0];
            landmarks[2 * index + 1] = (float)point[1];
        }

        if (usable != (Math.Min(box.Width.Value, box.Height.Value) >= definition.MinimumFaceSide)) return null;
        float[]? vector = null;
        byte[]? thumbnail = null;
        if (usable)
        {
            vector = FaceContractRules.TryDecodeVector(detection.Embedding, dimension);
            if (vector is null) return null;
            if (allowThumbnail)
            {
                thumbnail = TryDecodeThumbnail(detection.Thumbnail);
                if (thumbnail is null) return null;
            }
            else if (detection.Thumbnail is not null)
            {
                return null;
            }
        }
        else if (detection.Embedding is not null || detection.Thumbnail is not null)
        {
            return null;
        }

        return new ParsedFace(detection.ObservationId, box.X!.Value, box.Y!.Value, box.Width.Value, box.Height.Value, landmarks, score, usable,
            vector, thumbnail);
    }

    /// <summary>A base64 JPEG of at most <see cref="FaceContractRules.MaximumThumbnailBytes"/> bytes, else null.</summary>
    internal static byte[]? TryDecodeThumbnail(string? encoded)
    {
        if (encoded is null || encoded.Length > (FaceContractRules.MaximumThumbnailBytes + 2) / 3 * 4) return null;
        try
        {
            var bytes = Convert.FromBase64String(encoded);
            return bytes is [0xFF, 0xD8, ..] && bytes.Length <= FaceContractRules.MaximumThumbnailBytes ? bytes : null;
        }
        catch (FormatException)
        {
            return null;
        }
    }

    private static bool IsValidProvenance(FaceProvenanceContract provenance) =>
        provenance.RoleId == FaceContractRules.RoleId &&
        FaceContractRules.IsCanonicalSha256(provenance.IdentityFingerprint) &&
        provenance.RuntimeProfileId is { Length: >= 1 and <= 64 } &&
        provenance.RuntimeVariant is { Length: >= 1 and <= 64 } &&
        provenance.ExecutionProvider is "CPUExecutionProvider" or "CUDAExecutionProvider" &&
        provenance.ActualDevice is { Length: >= 3 and <= 8 } device && (device == "cpu" || device.StartsWith("cuda:", StringComparison.Ordinal)) &&
        provenance.DeviceResolutionReason is { Length: >= 1 and <= 64 } &&
        provenance.OnnxRuntimeVersion is { Length: >= 1 and <= 32 } &&
        provenance.WorkerVersion is { Length: >= 1 and <= 64 };

    private async Task<FaceCompletionResult> PublishedAsync(FaceAnalysis unit, CancellationToken cancellationToken)
    {
        var usable = await (
                from face in db.FaceObservations.AsNoTracking()
                where face.AnalysisId == unit.Id && face.Usable
                select face.Id)
            .CountAsync(cancellationToken);
        return new(unit.Status == FaceAnalysisStatus.Completed ? "completed" : "superseded", 200, null, unit.ProcessingRunId,
            unit.CompletedAtUtc, unit.TracksObserved, unit.TracksUnknown, usable);
    }

    // --- Transient query images ------------------------------------------------------------

    public async Task<FaceQueryLeaseGrant?> ClaimQueryAsync(
        string workerId, string identityFingerprint, TimeSpan leaseDuration, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var nowUtc = timeProvider.GetUtcNow();
        var candidate = await db.FaceQueries.FromSqlInterpolated($"""
            SELECT * FROM face_queries
            WHERE identity_fingerprint = {identityFingerprint}
              AND image IS NOT NULL
              AND attempt_count < {FaceQuery.MaximumAttempts}
              AND (status = 'Pending' OR (status = 'Running' AND lease_expires_at_utc <= {nowUtc}))
            ORDER BY created_at_utc, id
            FOR UPDATE SKIP LOCKED LIMIT 1
            """).SingleOrDefaultAsync(cancellationToken);
        if (candidate is null || !candidate.CanClaim(nowUtc) || candidate.IsImageExpired(nowUtc))
        {
            await transaction.CommitAsync(cancellationToken);
            return null;
        }

        var capability = leaseCapabilities.Create();
        candidate.Claim(workerId, capability.Hash, nowUtc, leaseDuration);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new FaceQueryLeaseGrant(candidate.Id, workerId, capability.Token, candidate.AttemptCount, candidate.LeaseExpiresAtUtc!.Value,
            candidate.MimeType, candidate.SizeBytes, candidate.ImageSha256);
    }

    public async Task<FaceQueryImage> ReadQueryImageAsync(
        Guid queryId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        var query = await db.FaceQueries.AsNoTracking().SingleOrDefaultAsync(x => x.Id == queryId, cancellationToken);
        if (query is null) return new(null, null, new FaceRefusal(FaceQuery.NotFoundCode));
        if (!query.HoldsActiveLease(workerId, TokenMatches(leaseToken, query.LeaseTokenHash), attemptCount, timeProvider.GetUtcNow()))
            return new(null, null, new FaceRefusal(FaceAnalysis.LeaseInvalidCode));
        return query.Image is { } image ? new(image, query.MimeType, null) : new(null, null, new FaceRefusal(QueryImageMissingCode));
    }

    public async Task<FaceQueryCompletionResult> CompleteQueryAsync(
        Guid queryId, string leaseToken, byte[] body, FaceQueryCompleteRequest request, FaceReleaseDefinition definition,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(body);
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(definition);
        if (request.QueryId != queryId || !WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId) ||
            request.AttemptCount is not ({ } attempt and >= 1) || request.Faces is not { } detections ||
            detections.Count > FaceContractRules.MaximumQueryFaces)
            return new(400, CompletionInvalidCode, 0);

        var digest = Convert.ToHexString(SHA256.HashData(body)).ToLowerInvariant();
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var query = await db.FaceQueries
            .FromSqlInterpolated($"SELECT * FROM face_queries WHERE id = {queryId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);
        if (query is null) return new(404, FaceQuery.NotFoundCode, 0);
        var tokenMatches = TokenMatches(leaseToken, query.LeaseTokenHash);
        if (query.IsCompletionReplay(workerId, tokenMatches, attempt))
        {
            await transaction.CommitAsync(cancellationToken);
            return string.Equals(query.CompletionDigest, digest, StringComparison.Ordinal)
                ? new(200, null, detections.Count)
                : new(409, CompletionConflictCode, 0);
        }

        var nowUtc = timeProvider.GetUtcNow();
        if (!query.HoldsActiveLease(workerId, tokenMatches, attempt, nowUtc)) return new(409, FaceAnalysis.LeaseInvalidCode, 0);
        if (!string.Equals(query.IdentityFingerprint, definition.Identity.Fingerprint, StringComparison.Ordinal))
            return new(409, IdentityMismatchCode, 0);

        var parsed = new List<ParsedFace>(detections.Count);
        foreach (var detection in detections)
        {
            if (ParseFace(detection, definition, definition.Identity.Dimension, requireObservation: false, allowThumbnail: true) is not { } face)
                return new(422, CompletionInvalidCode, 0);
            parsed.Add(face);
        }

        var stored = parsed.Select((face, index) => new FaceQueryFace(index,
                new FaceBox(face.X, face.Y, face.Width, face.Height), face.Landmarks, face.Score, face.Usable))
            .ToList();
        try
        {
            query.Complete(workerId, tokenMatches, attempt, JsonSerializer.Serialize(stored, ProvenanceJson), digest, nowUtc);
            for (var index = 0; index < parsed.Count; index++)
            {
                if (parsed[index].Vector is { } vector)
                    db.FaceQueryEmbeddings.Add(new FaceQueryEmbeddingRow
                    {
                        QueryId = query.Id, FaceIndex = index, Embedding = new Vector(vector), Thumbnail = parsed[index].Thumbnail,
                    });
            }

            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            return new(200, null, parsed.Count);
        }
        catch (DomainValidationException exception)
        {
            await transaction.RollbackAsync(CancellationToken.None);
            return new(409, exception.Code, 0);
        }
    }

    public async Task<FaceFailureOutcome> FailQueryAsync(
        Guid queryId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable, CancellationToken cancellationToken)
    {
        await using var transaction = await BeginFreshAsync(cancellationToken);
        var query = await db.FaceQueries
            .FromSqlInterpolated($"SELECT * FROM face_queries WHERE id = {queryId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);
        if (query is null) return new(null, new FaceRefusal(FaceQuery.NotFoundCode));
        try
        {
            query.Fail(workerId, TokenMatches(leaseToken, query.LeaseTokenHash), attemptCount, failureCode, retryable, timeProvider.GetUtcNow());
        }
        catch (DomainValidationException exception)
        {
            return new(null, new FaceRefusal(exception.Code));
        }

        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(query.Status == FaceQueryStatus.Pending ? FaceFailOutcome.Requeued : FaceFailOutcome.Failed, null);
    }

    // --- Helpers ---------------------------------------------------------------------------

    private bool TokenMatches(string leaseToken, byte[]? expectedHash) =>
        expectedHash is not null && leaseCapabilities.Matches(leaseToken, expectedHash);

    private Task<FaceAnalysis?> LockAsync(Guid analysisId, CancellationToken cancellationToken) =>
        db.FaceAnalyses
            .FromSqlInterpolated($"SELECT * FROM face_analyses WHERE id = {analysisId} FOR UPDATE")
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
