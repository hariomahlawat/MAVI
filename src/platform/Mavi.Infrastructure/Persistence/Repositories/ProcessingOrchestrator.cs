using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Abstractions.Security;
using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class ProcessingOrchestrator(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities,
    IOptions<VisionProcessingOptions> configuredOptions) : IProcessingOrchestrator
{
    // Queue and status
    public async Task<QueueProcessingResult> QueueAsync(Guid videoId, CancellationToken cancellationToken)
    {
        var video = await db.VideoAssets.SingleOrDefaultAsync(x => x.Id == videoId, cancellationToken);
        if (video is null) return new(false, null, "video_not_found");
        if (video.ProcessingStatus is VideoProcessingStatus.Queued or VideoProcessingStatus.Processing)
            return new(false, null, "processing_already_active");
        var options = configuredOptions.Value;
        var nowUtc = timeProvider.GetUtcNow();
        video.QueueProcessing();
        var run = ProcessingRun.Create(video.Id, options.PipelineVersion,
            JsonSerializer.Serialize(new { options.Pipeline, options.PipelineVersion }), nowUtc);
        var job = VisionJob.Create(run.Id, options.Pipeline, nowUtc);
        db.ProcessingRuns.Add(run); db.VisionJobs.Add(job);
        try { await db.SaveChangesAsync(cancellationToken); }
        catch (DbUpdateException exception) when (exception.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation, ConstraintName: "ux_processing_runs_active_video" })
        { return new(false, null, "processing_already_active"); }
        return new(true, run.Id, null);
    }

    public async Task<ProcessingStatusResult> GetStatusAsync(Guid videoId, CancellationToken cancellationToken)
    {
        var video = await db.VideoAssets.AsNoTracking().SingleOrDefaultAsync(x => x.Id == videoId, cancellationToken);
        if (video is null) return new(false, string.Empty, null);
        var row = await (from run in db.ProcessingRuns.AsNoTracking()
                         where run.VideoAssetId == videoId
                         join job in db.VisionJobs.AsNoTracking() on run.Id equals job.ProcessingRunId
                         orderby run.QueuedAtUtc descending, run.Id descending
                         select new ProcessingRunStatusView(run.Id, run.Status.ToString(), job.Pipeline, run.PipelineVersion,
                             run.WorkerId, run.QueuedAtUtc, run.StartedAtUtc, run.CompletedAtUtc,
                             job.ProgressPercent, job.AttemptCount, job.FailureCode ?? run.ErrorCode)).FirstOrDefaultAsync(cancellationToken);
        return new(true, video.ProcessingStatus.ToString(), row);
    }

    // Atomic leasing
    public async Task<VisionLeaseView?> LeaseAsync(string workerId, CancellationToken cancellationToken)
    {
        var options = configuredOptions.Value;
        var selectionCutoffUtc = timeProvider.GetUtcNow();
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        while (true)
        {
            var job = await db.VisionJobs.FromSqlInterpolated($"""
                SELECT * FROM vision_jobs
                WHERE (status = 'Queued' AND available_at_utc <= {selectionCutoffUtc})
                   OR (status = 'Leased' AND lease_expires_at_utc <= {selectionCutoffUtc})
                ORDER BY available_at_utc, created_at_utc, id
                FOR UPDATE SKIP LOCKED LIMIT 1
                """).SingleOrDefaultAsync(cancellationToken);
            if (job is null) { await transaction.CommitAsync(cancellationToken); return null; }
            var nowUtc = timeProvider.GetUtcNow();
            var run = await db.ProcessingRuns.SingleAsync(x => x.Id == job.ProcessingRunId, cancellationToken);
            var video = await db.VideoAssets.SingleAsync(x => x.Id == run.VideoAssetId, cancellationToken);
            if (!job.CanLease(nowUtc, options.MaximumAttempts))
            {
                job.Exhaust(nowUtc); run.MarkFailed("vision_job_attempts_exhausted", null, nowUtc); video.MarkProcessingFailed();
                await db.SaveChangesAsync(cancellationToken);
                continue;
            }
            var capability = leaseCapabilities.Create();
            job.Lease(workerId, capability.Hash, nowUtc, TimeSpan.FromSeconds(options.LeaseSeconds), options.MaximumAttempts);
            run.AssignLease(workerId, nowUtc);
            if (video.ProcessingStatus == VideoProcessingStatus.Queued) video.MarkProcessing();
            var artifact = await db.Artifacts.AsNoTracking().SingleAsync(x => x.Id == video.SourceArtifactId, cancellationToken);
            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            return new("2.0", job.Id, run.Id, video.Id, video.CameraId, workerId, capability.Token, job.Pipeline, run.PipelineVersion,
                artifact.StorageKey, artifact.Sha256, artifact.SizeBytes, video.RecordingStartUtc, video.RecordingEndUtc,
                video.DurationMs, video.Width, video.Height, video.FrameRateNumerator, video.FrameRateDenominator,
                job.AttemptCount, job.LeaseExpiresAtUtc!.Value, video.RecordingTimeZoneId, video.RecordingUtcOffsetMinutes);
        }
    }

    // Worker-owned mutations
    public Task<OrchestrationResult> HeartbeatAsync(Guid jobId, string workerId, string leaseToken, double progressPercent, CancellationToken cancellationToken) =>
        MutateOwnedJobAsync(jobId, workerId, leaseToken, false, progressPercent, null, null, cancellationToken);

    public Task<OrchestrationResult> FailAsync(Guid jobId, string workerId, string leaseToken, string failureCode, string? failureMessage, CancellationToken cancellationToken) =>
        MutateOwnedJobAsync(jobId, workerId, leaseToken, true, 0, failureCode, failureMessage, cancellationToken);

    private async Task<OrchestrationResult> MutateOwnedJobAsync(Guid jobId, string workerId, string leaseToken, bool fail, double progress,
        string? failureCode, string? failureMessage, CancellationToken cancellationToken)
    {
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        var job = await db.VisionJobs.FromSqlInterpolated($"SELECT * FROM vision_jobs WHERE id = {jobId} FOR UPDATE").SingleOrDefaultAsync(cancellationToken);
        if (job is null) return OrchestrationResult.Failure("vision_job_not_found");
        var nowUtc = timeProvider.GetUtcNow();
        var tokenMatches = job.LeaseTokenHash is not null && leaseCapabilities.Matches(leaseToken, job.LeaseTokenHash);
        if (job.Status == VisionJobStatus.Failed && fail && tokenMatches &&
            string.Equals(job.LeaseOwner, workerId, StringComparison.Ordinal) &&
            string.Equals(job.FailureCode, failureCode, StringComparison.Ordinal) &&
            string.Equals(job.FailureDetails, failureMessage, StringComparison.Ordinal))
        {
            await transaction.CommitAsync(cancellationToken);
            return OrchestrationResult.Success();
        }
        if (job.Status != VisionJobStatus.Leased) return OrchestrationResult.Failure("vision_job_not_leased");
        if (!string.Equals(job.LeaseOwner, workerId, StringComparison.Ordinal) || !tokenMatches || job.LeaseExpiresAtUtc <= nowUtc)
            return OrchestrationResult.Failure("vision_job_lease_invalid");
        try
        {
            if (!fail) job.Heartbeat(workerId, tokenMatches, progress, nowUtc, TimeSpan.FromSeconds(configuredOptions.Value.HeartbeatExtensionSeconds));
            else
            {
                job.Fail(workerId, tokenMatches, failureCode!, failureMessage, nowUtc);
                var run = await db.ProcessingRuns.SingleAsync(x => x.Id == job.ProcessingRunId, cancellationToken);
                var video = await db.VideoAssets.SingleAsync(x => x.Id == run.VideoAssetId, cancellationToken);
                run.MarkFailed(failureCode!, failureMessage, nowUtc); video.MarkProcessingFailed();
            }
        }
        catch (DomainValidationException exception) { return OrchestrationResult.Failure(exception.Code); }
        await db.SaveChangesAsync(cancellationToken); await transaction.CommitAsync(cancellationToken);
        return !fail ? new(true, null, job.ProgressPercent, job.LeaseExpiresAtUtc) : OrchestrationResult.Success();
    }
}
