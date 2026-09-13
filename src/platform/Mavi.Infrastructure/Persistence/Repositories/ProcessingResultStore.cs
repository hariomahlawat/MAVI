using Mavi.Application.Abstractions.Security;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class ProcessingResultStore(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities,
    VisionResultValidator validator,
    IAcceptedEvidenceStore acceptedEvidenceStore,
    ILogger<ProcessingResultStore> logger) : IProcessingResultStore
{
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

        var run = await db.ProcessingRuns
            .SingleAsync(x => x.Id == job.ProcessingRunId, cancellationToken);
        var video = await db.VideoAssets
            .SingleAsync(x => x.Id == run.VideoAssetId, cancellationToken);

        ValidatedVisionResult result;
        try
        {
            result = validator.Validate(jobId, request, video.DurationMs);
        }
        catch (VisionResultValidationException)
        {
            return VisionCompletionResult.Failure("vision_result_invalid");
        }

        if (!string.Equals(request.SchemaVersion, WorkerContractRules.SchemaVersion, StringComparison.Ordinal) ||
            !string.Equals(request.WorkerId, workerId, StringComparison.Ordinal) ||
            !string.Equals(request.LeaseToken, leaseToken, StringComparison.Ordinal))
            return VisionCompletionResult.Failure("vision_result_invalid");

        var tokenMatches = job.LeaseTokenHash is { Length: 32 } &&
                           leaseCapabilities.Matches(leaseToken, job.LeaseTokenHash);

        if (job.Status == VisionJobStatus.Completed)
        {
            if (job.AttemptCount != result.AttemptCount ||
                !string.Equals(job.LeaseOwner, workerId, StringComparison.Ordinal) ||
                !tokenMatches ||
                !string.Equals(job.CompletionDigest, result.CompletionDigest, StringComparison.Ordinal) ||
                run.Status != ProcessingRunStatus.Completed ||
                job.CompletedAtUtc is null)
                return VisionCompletionResult.Failure("vision_job_completion_conflict");

            await transaction.CommitAsync(cancellationToken);
            return VisionCompletionResult.Success(
                run.Id,
                run.TracksCreated,
                job.CompletedAtUtc.Value);
        }

        if (job.Status != VisionJobStatus.Leased)
            return VisionCompletionResult.Failure("vision_job_not_leased");
        if (job.AttemptCount != result.AttemptCount)
            return VisionCompletionResult.Failure("vision_job_attempt_mismatch");

        var authorityNowUtc = timeProvider.GetUtcNow();
        if (!string.Equals(job.LeaseOwner, workerId, StringComparison.Ordinal) ||
            !tokenMatches ||
            job.LeaseExpiresAtUtc is null ||
            job.LeaseExpiresAtUtc <= authorityNowUtc)
            return VisionCompletionResult.Failure("vision_job_lease_invalid");

        if (run.Status != ProcessingRunStatus.Running ||
            video.ProcessingStatus != VideoProcessingStatus.Processing)
            return VisionCompletionResult.Failure("vision_job_completion_conflict");

        var acceptedStorageKeys = new Dictionary<string, string>(StringComparer.Ordinal);
        var newlySealedKeys = new List<string>();
        var databaseCommitAttempted = false;
        var databaseCommitSucceeded = false;
        var compensationSafe = true;

        try
        {
            foreach (var track in result.Tracks)
            {
            var thumbnailAcceptedKey = AcceptedEvidenceKey(
                jobId,
                result.AttemptCount,
                "thumbnails",
                track.TrackId,
                track.Representative.Thumbnail.Sha256,
                "jpg");
            var thumbnail = await acceptedEvidenceStore.SealAsync(
                track.Representative.Thumbnail.StorageKey,
                thumbnailAcceptedKey,
                track.Representative.Thumbnail.SizeBytes,
                track.Representative.Thumbnail.Sha256,
                cancellationToken);
            if (thumbnail.CreatedNew && thumbnail.StorageKey is { } createdThumbnailKey)
                newlySealedKeys.Add(createdThumbnailKey);
            var thumbnailFailure = MapSealFailure(thumbnail.Status);
            if (thumbnailFailure is not null)
                return VisionCompletionResult.Failure(thumbnailFailure);
            acceptedStorageKeys.Add(
                track.Representative.Thumbnail.StorageKey,
                thumbnail.StorageKey ?? thumbnailAcceptedKey);

            var trajectoryAcceptedKey = AcceptedEvidenceKey(
                jobId,
                result.AttemptCount,
                "trajectories",
                track.TrackId,
                track.TrajectoryArtifact.Sha256,
                "msgpack");
            var trajectory = await acceptedEvidenceStore.SealAsync(
                track.TrajectoryArtifact.StorageKey,
                trajectoryAcceptedKey,
                track.TrajectoryArtifact.SizeBytes,
                track.TrajectoryArtifact.Sha256,
                cancellationToken);
            if (trajectory.CreatedNew && trajectory.StorageKey is { } createdTrajectoryKey)
                newlySealedKeys.Add(createdTrajectoryKey);
            var trajectoryFailure = MapSealFailure(trajectory.Status);
            if (trajectoryFailure is not null)
                return VisionCompletionResult.Failure(trajectoryFailure);
            acceptedStorageKeys.Add(
                track.TrajectoryArtifact.StorageKey,
                trajectory.StorageKey ?? trajectoryAcceptedKey);
            }

        var createdAtUtc = timeProvider.GetUtcNow();
        var graph = new List<(Track Track, Observation Observation)>(result.Tracks.Count);

        for (var index = 0; index < result.Tracks.Count; index++)
        {
            var accepted = result.Tracks[index];

            var thumbnailArtifact = Artifact.Create(
                ArtifactType.Thumbnail,
                acceptedStorageKeys[accepted.Representative.Thumbnail.StorageKey],
                accepted.Representative.Thumbnail.MediaType,
                accepted.Representative.Thumbnail.SizeBytes,
                accepted.Representative.Thumbnail.Sha256,
                createdAtUtc: createdAtUtc);

            var trajectoryArtifact = Artifact.Create(
                ArtifactType.TrackTrajectory,
                acceptedStorageKeys[accepted.TrajectoryArtifact.StorageKey],
                accepted.TrajectoryArtifact.MediaType,
                accepted.TrajectoryArtifact.SizeBytes,
                accepted.TrajectoryArtifact.Sha256,
                createdAtUtc: createdAtUtc);

            var track = Track.Create(
                run.Id,
                video.Id,
                index + 1,
                accepted.ObjectClass,
                accepted.StartOffsetMs,
                accepted.EndOffsetMs,
                video.RecordingStartUtc,
                accepted.DetectionCount,
                accepted.MeanConfidence,
                accepted.MaxConfidence,
                createdAtUtc);

            var representative = accepted.Representative;
            var observation = Observation.Create(
                track.Id,
                ObservationType.Representative,
                representative.SourceFrameNumber,
                representative.OffsetMs,
                video.RecordingStartUtc,
                checked((float)representative.X),
                checked((float)representative.Y),
                checked((float)representative.Width),
                checked((float)representative.Height),
                representative.Confidence,
                representative.QualityScore,
                createdAtUtc);

            track.AttachTrajectoryArtifact(trajectoryArtifact.Id);
            observation.AttachThumbnailArtifact(thumbnailArtifact.Id);

            db.Artifacts.AddRange(thumbnailArtifact, trajectoryArtifact);
            db.Tracks.Add(track);
            db.Observations.Add(observation);
            graph.Add((track, observation));
        }

        await db.SaveChangesAsync(cancellationToken);

        foreach (var (track, observation) in graph)
            track.AttachRepresentativeObservation(observation.Id);

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
                logger.LogError(
                    rollbackException,
                    "Unable to confirm rollback after Task-13 completion commit failure for job {JobId}; newly sealed evidence is retained for safety.",
                    jobId);
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
        IReadOnlyList<string> newlySealedKeys,
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
                logger.LogError(
                    exception,
                    "Task-13 evidence compensation failed for job {JobId} and accepted key {AcceptedStorageKey}.",
                    jobId,
                    newlySealedKeys[index]);
            }
        }
    }

    private static string AcceptedEvidenceKey(
        Guid jobId,
        int attemptCount,
        string category,
        string trackId,
        string sha256,
        string extension) =>
        $"evidence/{jobId:D}/attempt-{attemptCount:0000}/{category}/{trackId}-{sha256}.{extension}";

    private static string? MapSealFailure(AcceptedEvidenceSealStatus status) => status switch
    {
        AcceptedEvidenceSealStatus.Sealed => null,
        AcceptedEvidenceSealStatus.Missing => "vision_result_artifact_missing",
        AcceptedEvidenceSealStatus.IntegrityMismatch => "vision_result_artifact_integrity_failed",
        AcceptedEvidenceSealStatus.DestinationConflict => "vision_result_artifact_integrity_failed",
        _ => "vision_result_artifact_integrity_failed",
    };
}
