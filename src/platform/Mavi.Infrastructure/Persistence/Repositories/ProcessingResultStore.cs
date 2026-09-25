using Mavi.Application.Abstractions.Security;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class ProcessingResultStore(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities,
    VisionResultValidator validator,
    IAcceptedEvidenceStore acceptedEvidenceStore,
    IOptions<VisionFinalizationOptions> finalizationOptions,
    ILogger<ProcessingResultStore> logger) : IProcessingResultStore
{
    private static readonly Action<ILogger, Guid, Exception?> LogRollbackConfirmationFailure =
        LoggerMessage.Define<Guid>(
            LogLevel.Error,
            new EventId(1301, nameof(LogRollbackConfirmationFailure)),
            "Unable to confirm rollback after Task-13 completion commit failure for job {JobId}; newly sealed evidence is retained for safety.");

    private static readonly Action<ILogger, Guid, string, Exception?> LogEvidenceCompensationFailure =
        LoggerMessage.Define<Guid, string>(
            LogLevel.Error,
            new EventId(1302, nameof(LogEvidenceCompensationFailure)),
            "Task-13 evidence compensation failed for job {JobId} and accepted key {AcceptedStorageKey}.");


    public async Task<VisionCompletionResult> CompleteAsync(
        Guid jobId,
        string workerId,
        string leaseToken,
        VisionJobCompleteRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        var job = await db.VisionJobs
            .FromSqlInterpolated($"SELECT * FROM vision_jobs WHERE id = {jobId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);
        if (job is null)
            return VisionCompletionResult.Failure("vision_job_not_found");

        // The synchronous path: completion 2.0 always, and 3.0 until asynchronous finalization
        // is activated (VisionFinalization:Enabled), at which point 3.0 is retired and 3.1 is
        // the durable hand-off (VisionFinalizationSubmissionStore). The v3 sealing/graph code
        // below is what the F3 finalizer lifts.
        if (request.SchemaVersion != WorkerContractRules.CompletionSchemaVersionV2 &&
            (request.SchemaVersion != WorkerContractRules.CompletionSchemaVersionV3 || finalizationOptions.Value.Enabled))
            return VisionCompletionResult.Failure("vision_result_invalid");
        if (request.JobId != jobId ||
            !string.Equals(request.WorkerId, workerId, StringComparison.Ordinal) ||
            !string.Equals(request.LeaseToken, leaseToken, StringComparison.Ordinal))
            return VisionCompletionResult.Failure("vision_result_invalid");

        // Capability/lifecycle checks are deliberately performed immediately after
        // the row lock. An invalid caller must not hold FOR UPDATE while sorting,
        // serializing, hashing, or otherwise validating a large completion body.
        var tokenMatches = job.LeaseTokenHash is { Length: 32 } &&
                           leaseCapabilities.Matches(leaseToken, job.LeaseTokenHash);

        if (job.Status == VisionJobStatus.Completed)
        {
            if (!string.Equals(job.LeaseOwner, workerId, StringComparison.Ordinal) ||
                !tokenMatches ||
                request.AttemptCount != job.AttemptCount ||
                job.CompletedAtUtc is null)
                return VisionCompletionResult.Failure("vision_job_completion_conflict");

            var completedRun = await db.ProcessingRuns
                .SingleAsync(x => x.Id == job.ProcessingRunId, cancellationToken);
            if (completedRun.Status != ProcessingRunStatus.Completed)
                return VisionCompletionResult.Failure("vision_job_completion_conflict");

            var completedVideo = await db.VideoAssets
                .SingleAsync(x => x.Id == completedRun.VideoAssetId, cancellationToken);

            ValidatedVisionResult replayResult;
            try
            {
                replayResult = validator.Validate(jobId, request, completedVideo.DurationMs);
            }
            catch (VisionResultValidationException)
            {
                return VisionCompletionResult.Failure("vision_result_invalid");
            }

            if (!string.Equals(
                    job.CompletionDigest,
                    replayResult.CompletionDigest,
                    StringComparison.Ordinal))
                return VisionCompletionResult.Failure("vision_job_completion_conflict");

            await transaction.CommitAsync(cancellationToken);
            return VisionCompletionResult.Success(
                completedRun.Id,
                completedRun.TracksCreated,
                job.CompletedAtUtc.Value);
        }

        if (job.Status != VisionJobStatus.Leased)
            return VisionCompletionResult.Failure("vision_job_not_leased");

        var authorityNowUtc = timeProvider.GetUtcNow();
        if (!string.Equals(job.LeaseOwner, workerId, StringComparison.Ordinal) ||
            !tokenMatches ||
            job.LeaseExpiresAtUtc is null ||
            job.LeaseExpiresAtUtc <= authorityNowUtc)
            return VisionCompletionResult.Failure("vision_job_lease_invalid");

        if (request.AttemptCount != job.AttemptCount)
            return VisionCompletionResult.Failure("vision_job_attempt_mismatch");

        var run = await db.ProcessingRuns
            .SingleAsync(x => x.Id == job.ProcessingRunId, cancellationToken);
        var video = await db.VideoAssets
            .SingleAsync(x => x.Id == run.VideoAssetId, cancellationToken);

        if (run.Status != ProcessingRunStatus.Running ||
            video.ProcessingStatus != VideoProcessingStatus.Processing)
            return VisionCompletionResult.Failure("vision_job_completion_conflict");

        ValidatedVisionResult result;
        try
        {
            result = validator.Validate(jobId, request, video.DurationMs);
        }
        catch (VisionResultValidationException)
        {
            return VisionCompletionResult.Failure("vision_result_invalid");
        }

        var acceptedStorageKeys = new Dictionary<string, string>(StringComparer.Ordinal);
        var newlySealedKeys = new List<string>();
        var databaseCommitAttempted = false;
        var databaseCommitSucceeded = false;
        var compensationSafe = true;

        try
        {
            // Defence in depth: the validator already bounds admitted crop bytes;
            // the store refuses to seal past the run quota even if it were bypassed.
            if (EvidenceSealingPlan.ExceedsAdmittedCropQuota(result))
                return VisionCompletionResult.Failure("vision_result_invalid");

            // The shared plan: crops in rank order, then the trajectory, track by track.
            // Compensation below removes every newly sealed object in reverse on failure.
            foreach (var unit in EvidenceSealingPlan.Build(jobId, result))
            {
                var failure = await SealAsync(unit, newlySealedKeys, acceptedStorageKeys, cancellationToken);
                if (failure is not null)
                    return VisionCompletionResult.Failure(failure);
            }

        var createdAtUtc = timeProvider.GetUtcNow();
        var graph = FinalizationGraphBuilder.Build(result, acceptedStorageKeys, run.Id, video.Id, video.RecordingStartUtc, createdAtUtc);
        await FinalizationGraphPersistence.AddAsync(db, graph, cancellationToken);

        // Publish completion through a database-owned monotonic visibility
        // sequence. Completion takes the exclusive advisory lock immediately
        // before allocation and retains it through final save/commit. First-page
        // searches take the shared counterpart, so readers remain concurrent
        // while no later completion can receive a sequence inside their snapshot.
        await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(
            db,
            cancellationToken);
        var visibilitySequence =
            await ProcessingVisibilityBarrier.AllocateSequenceAsync(
                db,
                cancellationToken);
        var completionNowUtc = timeProvider.GetUtcNow();
        try
        {
            job.Complete(
                workerId,
                tokenMatches,
                authorityNowUtc,
                completionNowUtc,
                result.CompletionDigest);
        }
        catch (DomainValidationException)
        {
            return VisionCompletionResult.Failure("vision_job_lease_invalid");
        }

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

        await db.SaveChangesAsync(cancellationToken);

        databaseCommitAttempted = true;
        try
        {
            await transaction.CommitAsync(cancellationToken);
            databaseCommitSucceeded = true;
        }
        catch
        {
            try
            {
                await transaction.RollbackAsync(CancellationToken.None);
            }
            catch (Exception rollbackException)
            {
                compensationSafe = false;
                LogRollbackConfirmationFailure(logger, jobId, rollbackException);
            }

            throw;
        }

        return VisionCompletionResult.Success(
            run.Id,
            result.Tracks.Count,
            completionNowUtc);
        }
        finally
        {
            if (!databaseCommitSucceeded &&
                (!databaseCommitAttempted || compensationSafe) &&
                newlySealedKeys.Count > 0)
            {
                await CompensateNewlySealedEvidenceAsync(
                    newlySealedKeys,
                    jobId,
                    acceptedEvidenceStore,
                    logger);
            }
        }
    }

    private static async Task CompensateNewlySealedEvidenceAsync(
        List<string> newlySealedKeys,
        Guid jobId,
        IAcceptedEvidenceStore acceptedEvidenceStore,
        ILogger<ProcessingResultStore> logger)
    {
        for (var index = newlySealedKeys.Count - 1; index >= 0; index--)
        {
            try
            {
                await acceptedEvidenceStore.DeleteAcceptedAsync(
                    newlySealedKeys[index],
                    CancellationToken.None);
            }
            catch (Exception exception)
            {
                LogEvidenceCompensationFailure(
                    logger,
                    jobId,
                    newlySealedKeys[index],
                    exception);
            }
        }
    }

    private async Task<string?> SealAsync(
        EvidenceSealingUnit unit,
        List<string> newlySealedKeys,
        Dictionary<string, string> acceptedStorageKeys,
        CancellationToken cancellationToken)
    {
        var sealedResult = await acceptedEvidenceStore.SealAsync(
            unit.SourceStorageKey,
            unit.AcceptedStorageKey,
            unit.ExpectedSizeBytes,
            unit.ExpectedSha256,
            cancellationToken);
        if (sealedResult.CreatedNew && sealedResult.StorageKey is { } createdKey)
            newlySealedKeys.Add(createdKey);
        var failure = MapSealFailure(sealedResult.Status);
        if (failure is null)
            acceptedStorageKeys.Add(unit.SourceStorageKey, sealedResult.StorageKey ?? unit.AcceptedStorageKey);
        return failure;
    }

    private static string? MapSealFailure(AcceptedEvidenceSealStatus status) => status switch
    {
        AcceptedEvidenceSealStatus.Sealed => null,
        AcceptedEvidenceSealStatus.Missing => "vision_result_artifact_missing",
        AcceptedEvidenceSealStatus.IntegrityMismatch => "vision_result_artifact_integrity_failed",
        AcceptedEvidenceSealStatus.DestinationConflict => "vision_result_artifact_integrity_failed",
        _ => "vision_result_artifact_integrity_failed",
    };
}
