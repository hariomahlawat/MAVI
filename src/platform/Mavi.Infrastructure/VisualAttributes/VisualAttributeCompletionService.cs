using System.Diagnostics;
using Mavi.Application.Abstractions.Security;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Completion;
using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Mavi.Domain.VisualAttributes;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.Logging;

namespace Mavi.Infrastructure.VisualAttributes;

/// <summary>
/// The three-phase publication protocol of one attribute completion (S2b plan §13).
/// </summary>
/// <remarks>
/// <list type="number">
/// <item><b>Phase A — fenced validation.</b> Under the unit's row lock: committed replay first
/// (an exact duplicate of what was published is answered from the stored digest, even after
/// the lease has expired), then Running + worker + capability + attempt + unexpired lease,
/// the typed rules, the digest and the staged descriptor. The lock is released before any
/// filesystem work. The artefact is then validated structurally, streamed, lock-free.</item>
/// <item><b>Phase B — idempotent seal.</b> Outside every transaction, the staged bytes are
/// copied create-once to a content-addressed accepted key that is not attempt-scoped; an
/// identical object sealed earlier (a crash after seal, a retry) is verified and adopted.
/// Nothing sealed is ever deleted as compensation (ADR-006 §5).</item>
/// <item><b>Phase C — re-fence and publish.</b> The run's units are re-locked in id order; the
/// unit must still be Running, the same attempt and the same capability. A reclaim since
/// Phase A aborts publication and leaves the sealed object as a tolerated orphan. Rows are
/// written before the visibility barrier; the barrier is held only for the sequence, the
/// completion and supersession. Lease expiry alone does not stop Phase C: ownership does.</item>
/// </list>
/// </remarks>
public sealed partial class VisualAttributeCompletionService(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities,
    IVisualAttributeRelease release,
    IAttributeStagingStore staging,
    IAcceptedEvidenceStore acceptedEvidence,
    VisualAttributeIntegrityMonitor integrity,
    ILogger<VisualAttributeCompletionService> logger) : IVisualAttributeCompletionService
{
    /// <summary>Test seam: runs between Phase B and Phase C (the reclaim race).</summary>
    internal Func<CancellationToken, Task>? BeforePhaseC { get; init; }

    /// <summary>Test seam: runs in place of the Phase C commit's success (the ambiguous commit).</summary>
    internal Func<Task>? BeforeCommit { get; init; }

    public async Task<VisualAttributeCompletionResult> CompleteAsync(
        Guid analysisId, string leaseToken, VisualAttributeCompleteRequest request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId) || request.AttemptCount is not ({ } attempt and >= 1))
            return VisualAttributeCompletionResult.Refused(400, VisualAttributeCompletionValidator.InvalidCode);

        var clock = Stopwatch.StartNew();
        // --- Phase A ---------------------------------------------------------------------
        ValidatedAttributeCompletion completion;
        AttributeSchemaDefinition schema;
        IReadOnlyList<CompletionTrackScope> scope;
        VisualAttributeIdentityFields identity;
        Guid runId;
        await using (var transaction = await BeginFreshAsync(cancellationToken))
        {
            var unit = await LockAsync(analysisId, cancellationToken);
            if (unit is null) return VisualAttributeCompletionResult.Refused(404, "visual_attribute_analysis_not_found");
            var tokenMatches = TokenMatches(leaseToken, unit.LeaseTokenHash);
            identity = unit.Identity;
            runId = unit.ProcessingRunId;

            var loaded = await LoadScopeAsync(unit, cancellationToken);
            if (loaded is null) return VisualAttributeCompletionResult.Refused(409, "visual_attribute_identity_not_activated");
            (schema, scope) = loaded.Value;
            var validation = VisualAttributeCompletionValidator.Validate(analysisId, request, identity, schema, scope);

            // Committed replay has precedence over every lease rule: an exact duplicate after an
            // ambiguous outcome is answered from what was stored, whatever the clock says.
            if (unit.IsFactBearing)
            {
                if (validation.IsValid && unit.CanAuthenticateCompletionReplay(workerId, tokenMatches, attempt) &&
                    validation.Completion!.CompletionDigest == unit.CompletionDigest)
                    return Replay(unit);
                return VisualAttributeCompletionResult.Refused(409, "visual_attribute_completion_conflict");
            }

            if (unit.Status != VisualAttributeAnalysisStatus.Running)
                return VisualAttributeCompletionResult.Refused(409, "visual_attribute_not_running");
            if (!unit.HoldsActiveLease(workerId, tokenMatches, attempt, timeProvider.GetUtcNow()))
                return VisualAttributeCompletionResult.Refused(409, "visual_attribute_lease_invalid");
            if (!validation.IsValid)
                return VisualAttributeCompletionResult.Refused(400, validation.ErrorCode!);
            completion = validation.Completion!;

            var staged = staging.Describe(analysisId, attempt);
            if (staged is null) return VisualAttributeCompletionResult.Refused(409, "visual_attribute_prediction_not_staged");
            if (staged.SizeBytes != completion.PredictionSizeBytes)
                return VisualAttributeCompletionResult.Refused(422, VisualAttributeContractRules.ArtifactIntegrityFailedCode);
            await transaction.CommitAsync(cancellationToken);
        }

        var phaseA = clock.Elapsed;

        // --- Artefact structure: streamed, bounded, lock-free ------------------------------
        await using (var stream = await staging.OpenReadAsync(analysisId, attempt, cancellationToken))
        {
            var error = await AttributePredictionsValidator.ValidateAsync(
                stream, new AttributePredictionsValidator.Expectation(analysisId, identity, schema, scope, completion), cancellationToken);
            if (error is not null) return VisualAttributeCompletionResult.Refused(422, error);
        }

        var artefact = clock.Elapsed;

        // --- Phase B: idempotent seal, outside any transaction -----------------------------
        var acceptedKey = AttributeStagingLayout.AcceptedKey(analysisId, completion.PredictionSha256);
        var sealedResult = await acceptedEvidence.SealAsync(
            AttributeStagingLayout.StagingKey(analysisId, attempt), acceptedKey, completion.PredictionSizeBytes,
            completion.PredictionSha256, cancellationToken);
        switch (sealedResult.Status)
        {
            case AcceptedEvidenceSealStatus.Sealed:
                break;
            case AcceptedEvidenceSealStatus.Missing:
                return VisualAttributeCompletionResult.Refused(409, "visual_attribute_prediction_not_staged");
            default:
                return VisualAttributeCompletionResult.Refused(422, VisualAttributeContractRules.ArtifactIntegrityFailedCode);
        }

        var phaseB = clock.Elapsed;
        if (BeforePhaseC is not null) await BeforePhaseC(cancellationToken);

        // --- Phase C: re-fence and one publication transaction ------------------------------
        var phaseCStart = clock.Elapsed;
        TimeSpan rowsWritten, barrierAcquired;
        VisualAttributeAnalysis published;
        await using (var transaction = await BeginFreshAsync(cancellationToken))
        {
            // Every unit of the run, in id order: supersession needs the siblings, and one
            // deterministic order is what stops two completions of a run deadlocking.
            var runUnits = await db.VisualAttributeAnalyses.FromSqlInterpolated($"""
                SELECT * FROM visual_attribute_analyses WHERE processing_run_id = {runId} ORDER BY id FOR UPDATE
                """).ToListAsync(cancellationToken);
            var unit = runUnits.Single(x => x.Id == analysisId);
            var tokenMatches = TokenMatches(leaseToken, unit.LeaseTokenHash);
            if (unit.IsFactBearing && unit.CanAuthenticateCompletionReplay(workerId, tokenMatches, attempt) &&
                unit.CompletionDigest == completion.CompletionDigest)
            {
                // A concurrent exact duplicate published first.
                await transaction.RollbackAsync(cancellationToken);
                return Replay(unit);
            }

            // The re-fence: status, attempt and capability, never merely the clock.
            if (!unit.IsOwnedBy(workerId, tokenMatches, attempt))
            {
                await transaction.RollbackAsync(cancellationToken);
                LogStalePublication(logger, analysisId, attempt, acceptedKey);
                return VisualAttributeCompletionResult.Refused(409, VisualAttributeAnalysis.StaleAttemptCode);
            }

            var nowUtc = timeProvider.GetUtcNow();
            var artifact = Artifact.Create(ArtifactType.AttributePredictions, acceptedKey, VisualAttributeContractRules.PredictionsMediaType,
                completion.PredictionSizeBytes, completion.PredictionSha256, createdAtUtc: nowUtc);
            db.Artifacts.Add(artifact);
            foreach (var track in completion.Tracks)
            {
                db.VisualAttributeTrackOutcomes.Add(track.Outcome == VisualAttributeTrackOutcomeKind.Analysed
                    ? VisualAttributeTrackOutcome.Analysed(analysisId, track.TrackId)
                    : VisualAttributeTrackOutcome.Unavailable(analysisId, track.TrackId, track.Reason!));
                foreach (var row in track.Rows)
                {
                    db.VisualAttributes.Add(row.Outcome == VisualAttributeOutcome.Observed
                        ? VisualAttribute.Observed(analysisId, track.TrackId, row.AttributeType, row.Value!, row.Confidence!.Value, row.SupportingObservationId!.Value)
                        : VisualAttribute.Unknown(analysisId, track.TrackId, row.AttributeType));
                }
            }

            // Bulk rows before the barrier: the exclusive lock blocks every first-page search and
            // every other publication for as long as it is held. The rows stay uncommitted.
            try
            {
                await db.SaveChangesAsync(cancellationToken);
            }
            catch (DbUpdateException exception)
            {
                // The database refused the rows (for example, evidence removed underneath them).
                // Nothing is published; the worker may retry, and Phase A re-validates.
                await transaction.RollbackAsync(CancellationToken.None);
                LogPersistenceFailed(logger, analysisId, attempt, exception);
                return VisualAttributeCompletionResult.Refused(503, "visual_attribute_persistence_failed");
            }

            rowsWritten = clock.Elapsed;

            await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, cancellationToken);
            barrierAcquired = clock.Elapsed;
            var sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
            var preferred = release.Resolution.Definition?.Identity.Fingerprint;
            var isPreferred = string.Equals(preferred, unit.IdentityFingerprint, StringComparison.Ordinal);
            unit.Complete(workerId, tokenMatches, attempt, nowUtc, new VisualAttributeCompletion(
                completion.CompletionDigest, sequence, artifact.Id, completion.ProvenanceJson,
                completion.TracksAnalysed, completion.TracksUnavailable, completion.AttributesObserved, completion.AttributesUnknown),
                isPreferred);
            if (isPreferred)
            {
                // Currency moves only on a successful preferred completion; the facts of the
                // superseded units stay exactly as committed.
                foreach (var sibling in runUnits.Where(x => x.Id != analysisId && x.Status == VisualAttributeAnalysisStatus.Completed))
                    sibling.Supersede();
            }

            await db.SaveChangesAsync(cancellationToken);
            try
            {
                if (BeforeCommit is not null) await BeforeCommit();
                await transaction.CommitAsync(cancellationToken);
            }
            catch (Exception exception) when (exception is DbUpdateException or InvalidOperationException or Npgsql.NpgsqlException or IOException)
            {
                // Whether the commit landed is unknown. Nothing is retried here; the worker's
                // retry is answered by committed replay (Phase A) or refused and reclaimed.
                LogAmbiguousCommit(logger, analysisId, attempt, exception);
                return VisualAttributeCompletionResult.Refused(503, "visual_attribute_publication_ambiguous");
            }

            published = unit;
        }

        var end = clock.Elapsed;
        var incidents = completion.Tracks.Count(track => track.Reason is "evidence_integrity_failed" or "evidence_missing");
        if (incidents > 0) integrity.RecordCompletionIncidents(analysisId, incidents, timeProvider.GetUtcNow());
        var timings = new VisualAttributeCompletionTimings(phaseA, artefact - phaseA, phaseB - artefact, end - phaseCStart,
            rowsWritten - phaseCStart, end - barrierAcquired);
        LogPublished(logger, analysisId, attempt, published.Status, completion.Tracks.Count,
            timings.PhaseA.TotalMilliseconds, timings.PhaseB.TotalMilliseconds, timings.PhaseC.TotalMilliseconds, timings.BarrierHold.TotalMilliseconds);
        return new VisualAttributeCompletionResult(
            published.Status == VisualAttributeAnalysisStatus.Completed ? VisualAttributeCompletionStatus.Completed : VisualAttributeCompletionStatus.Superseded,
            null, 200, runId, published.CompletedAtUtc, completion.TracksAnalysed, completion.TracksUnavailable, false, timings);
    }

    private static VisualAttributeCompletionResult Replay(VisualAttributeAnalysis unit) => new(
        unit.Status == VisualAttributeAnalysisStatus.Completed ? VisualAttributeCompletionStatus.Completed : VisualAttributeCompletionStatus.Superseded,
        null, 200, unit.ProcessingRunId, unit.CompletedAtUtc, unit.TracksAnalysed, unit.TracksUnavailable, true, null);

    private async Task<(AttributeSchemaDefinition Schema, IReadOnlyList<CompletionTrackScope> Scope)?> LoadScopeAsync(
        VisualAttributeAnalysis unit, CancellationToken cancellationToken)
    {
        var schemaJson = await db.VisualAttributeIdentityActivations.AsNoTracking()
            .Where(x => x.Fingerprint == unit.IdentityFingerprint)
            .OrderByDescending(x => x.ActivatedAtUtc)
            .Select(x => x.AttributeSchemaJson)
            .FirstOrDefaultAsync(cancellationToken);
        if (schemaJson is null) return null;
        var schema = VisualAttributeReleaseParser.ParseStoredSchema(schemaJson, unit.AttributeSchemaSha256);
        var classes = VisualAttributeLifecycle.ObjectClasses(schema);
        var tracks = await db.Tracks.AsNoTracking()
            .Where(track => track.ProcessingRunId == unit.ProcessingRunId && classes.Contains(track.ObjectClass))
            .Select(track => new { track.Id, track.ObjectClass })
            .ToListAsync(cancellationToken);
        var crops = await (
                from track in db.Tracks.AsNoTracking()
                where track.ProcessingRunId == unit.ProcessingRunId && classes.Contains(track.ObjectClass)
                join observation in db.Observations.AsNoTracking() on track.Id equals observation.TrackId
                join artifact in db.Artifacts.AsNoTracking() on observation.ThumbnailArtifactId equals artifact.Id
                where artifact.ArtifactType == ArtifactType.EvidenceCrop
                select new { observation.TrackId, observation.Id })
            .ToListAsync(cancellationToken);
        var byTrack = crops.ToLookup(item => item.TrackId, item => item.Id);
        IReadOnlyList<CompletionTrackScope> scope = tracks
            .Select(track => new CompletionTrackScope(track.Id, VisualAttributeLifecycle.ObjectClassToken(track.ObjectClass),
                byTrack[track.Id].ToHashSet()))
            .ToList();
        return (schema, scope);
    }

    private bool TokenMatches(string leaseToken, byte[]? expectedHash) =>
        expectedHash is not null && leaseCapabilities.Matches(leaseToken, expectedHash);

    private Task<VisualAttributeAnalysis?> LockAsync(Guid analysisId, CancellationToken cancellationToken) =>
        db.VisualAttributeAnalyses
            .FromSqlInterpolated($"SELECT * FROM visual_attribute_analyses WHERE id = {analysisId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);

    private async Task<IDbContextTransaction> BeginFreshAsync(CancellationToken cancellationToken)
    {
        db.ChangeTracker.Clear();
        return await db.Database.BeginTransactionAsync(cancellationToken);
    }

    [LoggerMessage(EventId = 1990, EventName = "visual_attribute_published", Level = LogLevel.Information,
        Message = "Visual attribute analysis {AnalysisId} attempt {Attempt} published as {Status}: {Tracks} Tracks; phase A {PhaseAMs} ms, seal {PhaseBMs} ms, publication {PhaseCMs} ms, barrier {BarrierMs} ms.")]
    private static partial void LogPublished(ILogger logger, Guid analysisId, int attempt, VisualAttributeAnalysisStatus status, int tracks,
        double phaseAMs, double phaseBMs, double phaseCMs, double barrierMs);

    [LoggerMessage(EventId = 1991, EventName = "visual_attribute_stale_publication", Level = LogLevel.Warning,
        Message = "Visual attribute analysis {AnalysisId} attempt {Attempt} lost ownership after sealing; nothing was published and {AcceptedKey} is a tolerated orphan.")]
    private static partial void LogStalePublication(ILogger logger, Guid analysisId, int attempt, string acceptedKey);

    [LoggerMessage(EventId = 1993, EventName = "visual_attribute_persistence_failed", Level = LogLevel.Error,
        Message = "Visual attribute analysis {AnalysisId} attempt {Attempt}: the publication rows were refused; nothing was published.")]
    private static partial void LogPersistenceFailed(ILogger logger, Guid analysisId, int attempt, Exception exception);

    [LoggerMessage(EventId = 1992, EventName = "visual_attribute_commit_ambiguous", Level = LogLevel.Error,
        Message = "Visual attribute analysis {AnalysisId} attempt {Attempt}: the publication commit outcome is unknown; a retry is answered by committed replay.")]
    private static partial void LogAmbiguousCommit(ILogger logger, Guid analysisId, int attempt, Exception exception);
}
