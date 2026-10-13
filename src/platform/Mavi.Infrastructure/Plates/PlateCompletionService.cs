using Mavi.Application.Abstractions.Security;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.Plates.Completion;
using Mavi.Application.Modules.Plates.Release;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Media;
using Mavi.Domain.Plates;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.Logging;

namespace Mavi.Infrastructure.Plates;

/// <summary>
/// The three-phase publication protocol of one plate completion (ADR-013 implementation amendment
/// 2026-09-28, item 4, applied to plates by item 11).
/// </summary>
/// <remarks>
/// <list type="number">
/// <item><b>Phase A — fenced validation.</b> Under the unit's row lock: committed replay first, then
/// Running + worker + capability + attempt + unexpired lease, the typed rules and digest, and the staged
/// descriptor; the unit is held for one publication window. The artefact is then validated, streamed and
/// lock-free, against the validated completion.</item>
/// <item><b>Phase B — idempotent seal</b> of the staged bytes to a content-addressed accepted key, outside
/// every transaction. Nothing sealed is ever deleted as compensation (ADR-006 §5).</item>
/// <item><b>Phase C — re-fence and publish.</b> The run's plate units are re-locked in id order; the unit
/// must still be owned by the same attempt and capability. Rows are written before the visibility
/// barrier; the barrier is held only for the sequence, the completion and supersession.</item>
/// </list>
/// </remarks>
public sealed partial class PlateCompletionService(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities,
    IPlateRelease release,
    IPlateStagingStore staging,
    IAcceptedEvidenceStore acceptedEvidence,
    PlateIntegrityMonitor integrity,
    Microsoft.Extensions.Options.IOptions<PlateOptions> options,
    ILogger<PlateCompletionService> logger) : IPlateCompletionService
{
    /// <summary>Test seam: runs between Phase B and Phase C (the reclaim race).</summary>
    internal Func<CancellationToken, Task>? BeforePhaseC { get; init; }

    /// <summary>Test seam: runs in place of the Phase C commit's success (the ambiguous commit).</summary>
    internal Func<Task>? BeforeCommit { get; init; }

    public async Task<PlateCompletionResult> CompleteAsync(
        Guid analysisId, string leaseToken, PlateCompleteRequest request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId) || request.AttemptCount is not ({ } attempt and >= 1))
            return PlateCompletionResult.Refused(400, PlateCompletionValidator.InvalidCode);

        // --- Phase A ---------------------------------------------------------------------
        ValidatedPlateCompletion completion;
        PlateParameters parameters;
        IReadOnlyList<PlateCompletionTrackScope> scope;
        PlateIdentityFields identity;
        Guid runId;
        await using (var transaction = await BeginFreshAsync(cancellationToken))
        {
            var unit = await LockAsync(analysisId, cancellationToken);
            if (unit is null) return PlateCompletionResult.Refused(404, PlateLifecycle.AnalysisNotFoundCode);
            var tokenMatches = TokenMatches(leaseToken, unit.LeaseTokenHash);
            identity = unit.Identity;
            runId = unit.ProcessingRunId;

            var loaded = await LoadScopeAsync(unit, cancellationToken);
            if (loaded is null) return PlateCompletionResult.Refused(409, "plate_identity_not_activated");
            (parameters, scope) = loaded.Value;
            var validation = PlateCompletionValidator.Validate(analysisId, request, identity, parameters, scope);

            // Committed replay has precedence over every lease rule.
            if (unit.IsFactBearing)
            {
                if (validation.IsValid && unit.CanAuthenticateCompletionReplay(workerId, tokenMatches, attempt) &&
                    validation.Completion!.CompletionDigest == unit.CompletionDigest)
                    return Replay(unit);
                return PlateCompletionResult.Refused(409, "plate_completion_conflict");
            }

            if (unit.Status != PlateAnalysisStatus.Running) return PlateCompletionResult.Refused(409, PlateAnalysis.NotRunningCode);
            if (!unit.HoldsActiveLease(workerId, tokenMatches, attempt, timeProvider.GetUtcNow()))
                return PlateCompletionResult.Refused(409, PlateAnalysis.LeaseInvalidCode);
            if (!validation.IsValid) return PlateCompletionResult.Refused(400, validation.ErrorCode!);
            completion = validation.Completion!;

            var staged = staging.Describe(analysisId, attempt);
            if (staged is null) return PlateCompletionResult.Refused(409, "plate_prediction_not_staged");
            if (staged.SizeBytes != completion.PredictionSizeBytes)
                return PlateCompletionResult.Refused(422, PlateContractRules.ArtifactIntegrityFailedCode);

            unit.BeginPublication(workerId, tokenMatches, attempt, timeProvider.GetUtcNow(), options.Value.LeasePolicy);
            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
        }

        // --- Artefact: streamed, bounded, lock-free ----------------------------------------
        Stream predictions;
        try
        {
            predictions = await staging.OpenReadAsync(analysisId, attempt, cancellationToken);
        }
        catch (Exception exception) when (exception is FileNotFoundException or DirectoryNotFoundException)
        {
            return PlateCompletionResult.Refused(409, "plate_prediction_not_staged");
        }

        await using (var stream = predictions)
        {
            var validation = await PlatePredictionsValidator.ValidateAsync(
                stream, new PlatePredictionsValidator.Expectation(analysisId, identity, parameters, scope, completion), cancellationToken);
            if (validation.Error is not null) return PlateCompletionResult.Refused(422, validation.Error);
            if (validation.IntegrityIncidents.Count > 0)
            {
                LogIntegrityReported(logger, analysisId, attempt, validation.IntegrityIncidents.Count);
                integrity.RecordCompletionIncidents(analysisId, validation.IntegrityIncidents, timeProvider.GetUtcNow());
            }
        }

        // --- Phase B: idempotent seal, outside any transaction -----------------------------
        var publication = CancellationToken.None;
        var acceptedKey = PlateStagingLayout.AcceptedKey(analysisId, completion.PredictionSha256);
        var sealedResult = await acceptedEvidence.SealAsync(
            PlateStagingLayout.StagingKey(analysisId, attempt), acceptedKey, completion.PredictionSizeBytes, completion.PredictionSha256, publication);
        switch (sealedResult.Status)
        {
            case AcceptedEvidenceSealStatus.Sealed:
                break;
            case AcceptedEvidenceSealStatus.Missing:
                return PlateCompletionResult.Refused(409, "plate_prediction_not_staged");
            default:
                return PlateCompletionResult.Refused(422, PlateContractRules.ArtifactIntegrityFailedCode);
        }

        if (BeforePhaseC is not null) await BeforePhaseC(publication);

        // --- Phase C: re-fence and one publication transaction ------------------------------
        PlateAnalysis published;
        await using (var transaction = await BeginFreshAsync(publication))
        {
            var runUnits = await db.PlateAnalyses.FromSqlInterpolated($"""
                SELECT * FROM plate_analyses WHERE processing_run_id = {runId} ORDER BY id FOR UPDATE
                """).ToListAsync(publication);
            var unit = runUnits.Single(x => x.Id == analysisId);
            var tokenMatches = TokenMatches(leaseToken, unit.LeaseTokenHash);
            if (unit.IsFactBearing && unit.CanAuthenticateCompletionReplay(workerId, tokenMatches, attempt) &&
                unit.CompletionDigest == completion.CompletionDigest)
            {
                await transaction.RollbackAsync(publication);
                return Replay(unit);
            }

            if (!unit.IsOwnedBy(workerId, tokenMatches, attempt))
            {
                await transaction.RollbackAsync(publication);
                LogStalePublication(logger, analysisId, attempt, acceptedKey);
                return PlateCompletionResult.Refused(409, PlateAnalysis.StaleAttemptCode);
            }

            var nowUtc = timeProvider.GetUtcNow();
            var artifact = Artifact.Create(ArtifactType.PlatePredictions, acceptedKey, PlateContractRules.PredictionsMediaType,
                completion.PredictionSizeBytes, completion.PredictionSha256, createdAtUtc: nowUtc);
            db.Artifacts.Add(artifact);
            var (outcomes, observations, texts) = BuildFacts(analysisId, completion);

            try
            {
                await db.SaveChangesAsync(publication);
                await PlateFactWriter.WriteAsync(db, outcomes, observations, texts, publication);
            }
            catch (Exception exception) when (exception is DbUpdateException or Npgsql.PostgresException)
            {
                await transaction.RollbackAsync(CancellationToken.None);
                LogPersistenceFailed(logger, analysisId, attempt, exception);
                return PlateCompletionResult.Refused(503, "plate_persistence_failed");
            }

            await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, publication);
            var sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, publication);
            var preferred = release.Resolution.Definition?.Identity.Fingerprint;
            var isPreferred = string.Equals(preferred, unit.IdentityFingerprint, StringComparison.Ordinal);
            unit.Complete(workerId, tokenMatches, attempt, nowUtc, new PlateCompletion(
                completion.CompletionDigest, sequence, artifact.Id, completion.ProvenanceJson, completion.TracksAnalysed,
                completion.TracksUnavailable, completion.PlateObservationsRead, completion.PlateObservationsUnreadable), isPreferred);
            if (isPreferred)
            {
                // Currency moves only on a successful preferred completion; superseded facts stay as committed.
                foreach (var sibling in runUnits.Where(x => x.Id != analysisId && x.Status == PlateAnalysisStatus.Completed))
                    sibling.Supersede();
            }

            await db.SaveChangesAsync(publication);
            try
            {
                if (BeforeCommit is not null) await BeforeCommit();
                await transaction.CommitAsync(publication);
            }
            catch (Exception exception) when (exception is DbUpdateException or InvalidOperationException or Npgsql.NpgsqlException or IOException)
            {
                LogAmbiguousCommit(logger, analysisId, attempt, exception);
                return PlateCompletionResult.Refused(503, "plate_publication_ambiguous");
            }

            published = unit;
        }

        LogPublished(logger, analysisId, attempt, published.Status, completion.Tracks.Count);
        return new PlateCompletionResult(
            published.Status == PlateAnalysisStatus.Completed ? PlateCompletionStatus.Completed : PlateCompletionStatus.Superseded,
            null, 200, runId, published.CompletedAtUtc, completion.TracksAnalysed, completion.TracksUnavailable, false);
    }

    /// <summary>The domain rows of one validated completion; a Track text points at its best plate's row.</summary>
    internal static (List<PlateTrackOutcome> Outcomes, List<PlateObservation> Observations, List<PlateTrackText> Texts) BuildFacts(
        Guid analysisId, ValidatedPlateCompletion completion)
    {
        var outcomes = new List<PlateTrackOutcome>(completion.Tracks.Count);
        var observations = new List<PlateObservation>();
        var texts = new List<PlateTrackText>();
        foreach (var track in completion.Tracks)
        {
            if (track.Outcome == PlateTrackOutcomeKind.Unavailable)
            {
                outcomes.Add(PlateTrackOutcome.Unavailable(analysisId, track.TrackId, track.Reason!));
                continue;
            }

            outcomes.Add(PlateTrackOutcome.Analysed(analysisId, track.TrackId, track.Observations.Count, track.Texts.Count));
            var rows = new Dictionary<(Guid, int), Guid>();
            foreach (var item in track.Observations)
            {
                var row = PlateObservation.Create(analysisId, track.TrackId, item.SourceObservationId, item.PlateIndex, item.BoxX, item.BoxY,
                    item.BoxWidth, item.BoxHeight, item.CropWidth, item.CropHeight, item.DetectorConfidence, item.Outcome, item.Readings);
                observations.Add(row);
                rows[(item.SourceObservationId, item.PlateIndex)] = row.Id;
            }

            foreach (var text in track.Texts)
            {
                texts.Add(PlateTrackText.Create(analysisId, track.TrackId, text.NormalisedText, text.SupportCount, text.MaxConfidence,
                    rows[(text.BestSourceObservationId, text.BestPlateIndex)]));
            }
        }

        return (outcomes, observations, texts);
    }

    private static PlateCompletionResult Replay(PlateAnalysis unit) => new(
        unit.Status == PlateAnalysisStatus.Completed ? PlateCompletionStatus.Completed : PlateCompletionStatus.Superseded,
        null, 200, unit.ProcessingRunId, unit.CompletedAtUtc, unit.TracksAnalysed, unit.TracksUnavailable, true);

    private async Task<(PlateParameters Parameters, IReadOnlyList<PlateCompletionTrackScope> Scope)?> LoadScopeAsync(
        PlateAnalysis unit, CancellationToken cancellationToken)
    {
        var parametersJson = await db.PlateIdentityActivations.AsNoTracking()
            .Where(x => x.Fingerprint == unit.IdentityFingerprint)
            .OrderByDescending(x => x.ActivatedAtUtc)
            .Select(x => x.ParametersJson)
            .FirstOrDefaultAsync(cancellationToken);
        if (parametersJson is null) return null;
        var parameters = PlateReleaseParser.ParseStoredParameters(parametersJson, unit.ParametersSha256);
        var lease = await new PlateLifecycle(db, timeProvider, leaseCapabilities).LeaseTracksAsync(unit.ProcessingRunId, cancellationToken);
        IReadOnlyList<PlateCompletionTrackScope> scope = lease
            .Select(track => new PlateCompletionTrackScope(track.TrackId,
                track.Observations.Select(item => new PlateScopeObservation(item.ObservationId, item.Role, item.EvidenceRank)).ToList()))
            .ToList();
        return (parameters, scope);
    }

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

    [LoggerMessage(EventId = 2100, EventName = "plate_published", Level = LogLevel.Information,
        Message = "Plate analysis {AnalysisId} attempt {Attempt} published as {Status}: {Tracks} Vehicle Tracks.")]
    private static partial void LogPublished(ILogger logger, Guid analysisId, int attempt, PlateAnalysisStatus status, int tracks);

    [LoggerMessage(EventId = 2101, EventName = "plate_stale_publication", Level = LogLevel.Warning,
        Message = "Plate analysis {AnalysisId} attempt {Attempt} lost ownership after sealing; nothing was published and {AcceptedKey} is a tolerated orphan.")]
    private static partial void LogStalePublication(ILogger logger, Guid analysisId, int attempt, string acceptedKey);

    [LoggerMessage(EventId = 2102, EventName = "plate_commit_ambiguous", Level = LogLevel.Error,
        Message = "Plate analysis {AnalysisId} attempt {Attempt}: the publication commit outcome is unknown; a retry is answered by committed replay.")]
    private static partial void LogAmbiguousCommit(ILogger logger, Guid analysisId, int attempt, Exception exception);

    [LoggerMessage(EventId = 2103, EventName = "plate_persistence_failed", Level = LogLevel.Error,
        Message = "Plate analysis {AnalysisId} attempt {Attempt}: the publication rows were refused; nothing was published.")]
    private static partial void LogPersistenceFailed(ILogger logger, Guid analysisId, int attempt, Exception exception);

    [LoggerMessage(EventId = 2104, EventName = "plate_evidence_integrity_reported", Level = LogLevel.Error,
        Message = "Plate analysis {AnalysisId} attempt {Attempt}: the worker reported {Crops} accepted evidence crop(s) missing or not matching their recorded digest.")]
    private static partial void LogIntegrityReported(ILogger logger, Guid analysisId, int attempt, int crops);
}
