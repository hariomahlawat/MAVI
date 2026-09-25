using System.Diagnostics;
using Mavi.Application.Abstractions.Security;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The completion 3.1 durable hand-off (S1.4 B3 asynchronous finalization plan §6, §5.3, §10.1–§10.2).
/// </summary>
/// <remarks>
/// <para>
/// One transaction, <c>FOR UPDATE</c> on the job for exactly the bounded submission work:
/// authenticate the lease capability, validate the body, encode the capability-free semantic
/// payload, insert the payload row and move the job <c>Leased → Finalizing</c>. The row lock
/// serializes duplicate and competing submissions, so the second of two identical requests
/// observes <c>Finalizing</c> and replays; the second of two conflicting ones observes the
/// other's digest and conflicts. PostgreSQL atomicity is the only recovery mechanism: an
/// ambiguous HTTP outcome is resolved by the retry seeing either <c>Leased</c> or the
/// committed hand-off.
/// </para>
/// <para>
/// Replay authentication uses the retained <c>LeaseOwner</c>/<c>LeaseTokenHash</c>/<c>AttemptCount</c>
/// (<see cref="VisionJob.CanAuthenticateCompletionReplay"/>), never the lease expiry, and every
/// replay body is re-validated so the digest compared against the stored one is recomputed,
/// never caller-supplied. The raw lease token is compared only through
/// <see cref="ILeaseCapabilityService.Matches"/> and never reaches a row, a log or an error.
/// </para>
/// </remarks>
public sealed class VisionFinalizationSubmissionStore(
    MaviDbContext db,
    TimeProvider timeProvider,
    ILeaseCapabilityService leaseCapabilities,
    VisionResultValidator validator,
    IOptions<VisionFinalizationOptions> finalizationOptions,
    ILogger<VisionFinalizationSubmissionStore> logger) : IVisionFinalizationSubmissionStore
{
    private static readonly Action<ILogger, Guid, int, int, long, string, Exception?> LogHandOff =
        LoggerMessage.Define<Guid, int, int, long, string>(
            LogLevel.Information,
            new EventId(1310, nameof(LogHandOff)),
            "Completion 3.1 hand-off accepted for job {JobId} attempt {AttemptCount}: {TracksSubmitted} tracks, {PayloadBytes} payload bytes; {Timings}.");

    public async Task<VisionFinalizationSubmissionResult> SubmitAsync(
        Guid jobId,
        string workerId,
        string leaseToken,
        VisionJobCompleteRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        // Defence in depth behind the endpoint gate: without the F3 finalizer no job may enter
        // Finalizing, whatever reached this store (plan §15.2, F2 deployment note).
        if (!finalizationOptions.Value.Enabled)
            return VisionFinalizationSubmissionResult.Failure("vision_finalization_disabled");
        var total = Stopwatch.StartNew();

        // Only the asynchronous exchange comes here; 2.0 keeps its synchronous store and 3.0
        // is refused at the endpoint (plan §15.2). The body's envelope must be the route's.
        if (!WorkerContractRules.IsAsynchronousCompletionSchemaVersion(request.SchemaVersion) ||
            request.JobId != jobId ||
            !string.Equals(request.WorkerId, workerId, StringComparison.Ordinal) ||
            !string.Equals(request.LeaseToken, leaseToken, StringComparison.Ordinal))
            return VisionFinalizationSubmissionResult.Failure("vision_result_invalid");

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        var job = await db.VisionJobs
            .FromSqlInterpolated($"SELECT * FROM vision_jobs WHERE id = {jobId} FOR UPDATE")
            .SingleOrDefaultAsync(cancellationToken);
        if (job is null)
            return VisionFinalizationSubmissionResult.Failure("vision_job_not_found");

        // Capability first, before any work on a large body is done under the row lock.
        var tokenMatches = job.LeaseTokenHash is { Length: 32 } && leaseCapabilities.Matches(leaseToken, job.LeaseTokenHash);
        var attemptCount = request.AttemptCount ?? -1;

        if (job.Status is VisionJobStatus.Finalizing or VisionJobStatus.Completed)
        {
            // Plan §5.3: an exact replay of the hand-off that this capability made. The lease
            // expiry is not consulted; the retained capability facts are the authority.
            if (!job.CanAuthenticateCompletionReplay(workerId, tokenMatches, attemptCount))
                return VisionFinalizationSubmissionResult.Failure("vision_job_completion_conflict");

            var replayContext = await LoadContextAsync(job, cancellationToken);
            if (replayContext is null)
                return VisionFinalizationSubmissionResult.Failure("vision_job_completion_conflict");
            var (replayRun, replayVideo) = replayContext.Value;

            var validation = Stopwatch.StartNew();
            ValidatedVisionResult replay;
            try
            {
                replay = validator.Validate(jobId, request, replayVideo.DurationMs);
            }
            catch (VisionResultValidationException)
            {
                return VisionFinalizationSubmissionResult.Failure("vision_result_invalid");
            }
            validation.Stop();

            // Same attempt, different content: never idempotent (plan §5.3).
            if (!string.Equals(job.CompletionDigest, replay.CompletionDigest, StringComparison.Ordinal))
                return VisionFinalizationSubmissionResult.Failure("vision_job_completion_conflict");

            // Nothing is written: no second payload row, no reset of claim state, no new
            // acceptance time. The stored facts are the answer.
            await transaction.CommitAsync(cancellationToken);
            var timings = new VisionFinalizationSubmissionTimings(validation.Elapsed, TimeSpan.Zero, TimeSpan.Zero, total.Elapsed);
            if (job.Status == VisionJobStatus.Finalizing)
            {
                if (job.FinalizationAcceptedAtUtc is not { } replayAcceptedAtUtc)
                    return VisionFinalizationSubmissionResult.Failure("vision_job_completion_conflict");
                return VisionFinalizationSubmissionResult.Finalizing(replayRun.Id, replayAcceptedAtUtc, replay.Tracks.Count, timings);
            }

            if (job.CompletedAtUtc is not { } completedAtUtc || replayRun.Status != ProcessingRunStatus.Completed)
                return VisionFinalizationSubmissionResult.Failure("vision_job_completion_conflict");
            // A job the finalizer published carries its hand-off time; one completed by the
            // synchronous path before 3.1 existed does not, and its completion time stands in.
            return VisionFinalizationSubmissionResult.Completed(
                replayRun.Id, job.FinalizationAcceptedAtUtc ?? completedAtUtc, replay.Tracks.Count, completedAtUtc, timings);
        }

        if (job.Status != VisionJobStatus.Leased)
            return VisionFinalizationSubmissionResult.Failure("vision_job_not_leased");

        var authorityNowUtc = timeProvider.GetUtcNow();
        if (!string.Equals(job.LeaseOwner, workerId, StringComparison.Ordinal) ||
            !tokenMatches ||
            job.LeaseExpiresAtUtc is null ||
            job.LeaseExpiresAtUtc <= authorityNowUtc)
            return VisionFinalizationSubmissionResult.Failure("vision_job_lease_invalid");

        if (attemptCount != job.AttemptCount)
            return VisionFinalizationSubmissionResult.Failure("vision_job_attempt_mismatch");

        var context = await LoadContextAsync(job, cancellationToken);
        if (context is null)
            return VisionFinalizationSubmissionResult.Failure("vision_job_completion_conflict");
        var (run, video) = context.Value;
        if (run.Status != ProcessingRunStatus.Running || video.ProcessingStatus != VideoProcessingStatus.Processing)
            return VisionFinalizationSubmissionResult.Failure("vision_job_completion_conflict");

        var validationWatch = Stopwatch.StartNew();
        ValidatedVisionResult result;
        try
        {
            result = validator.Validate(jobId, request, video.DurationMs);
        }
        catch (VisionResultValidationException)
        {
            return VisionFinalizationSubmissionResult.Failure("vision_result_invalid");
        }
        validationWatch.Stop();

        // The retained bytes are the codec's canonical semantic document: the worker's
        // authentication envelope (workerId, leaseToken) is not part of it (plan §4, §6 step 7).
        var encodingWatch = Stopwatch.StartNew();
        byte[] payloadBytes;
        try
        {
            payloadBytes = VisionFinalizationPayloadCodec.Encode(request);
        }
        catch (VisionResultValidationException)
        {
            return VisionFinalizationSubmissionResult.Failure("vision_result_invalid");
        }
        encodingWatch.Stop();

        var persistenceWatch = Stopwatch.StartNew();
        VisionFinalizationPayload payload;
        try
        {
            payload = VisionFinalizationPayload.Create(
                jobId, job.AttemptCount, payloadBytes, result.CompletionDigest, authorityNowUtc,
                WorkerContractRules.MaximumCompletionRequestBodyBytes);
            job.BeginFinalization(workerId, tokenMatches, attemptCount, authorityNowUtc, result.CompletionDigest);
        }
        catch (DomainValidationException exception)
        {
            return VisionFinalizationSubmissionResult.Failure(exception.Code);
        }

        // Payload row and status transition are one unit of work in one transaction: a
        // committed Finalizing job always has its payload, and a payload row never outlives
        // a rejected submission.
        db.VisionFinalizationPayloads.Add(payload);
        await db.SaveChangesAsync(cancellationToken);
        try
        {
            await transaction.CommitAsync(cancellationToken);
        }
        catch
        {
            // Whether the database committed is now its knowledge alone (plan §10.2): the
            // worker's identical retry reads the answer. Roll back what can be rolled back.
            try { await transaction.RollbackAsync(CancellationToken.None); }
            catch (Exception rollbackException) when (rollbackException is not OutOfMemoryException) { }
            throw;
        }
        persistenceWatch.Stop();
        total.Stop();

        var acceptedAtUtc = job.FinalizationAcceptedAtUtc!.Value;
        var handOffTimings = new VisionFinalizationSubmissionTimings(
            validationWatch.Elapsed, encodingWatch.Elapsed, persistenceWatch.Elapsed, total.Elapsed);
        LogHandOff(logger, jobId, job.AttemptCount, result.Tracks.Count, payload.PayloadLength,
            string.Create(System.Globalization.CultureInfo.InvariantCulture,
                $"validation {handOffTimings.Validation.TotalMilliseconds:F1} ms, encoding {handOffTimings.PayloadEncoding.TotalMilliseconds:F1} ms, " +
                $"persistence {handOffTimings.Persistence.TotalMilliseconds:F1} ms, total {handOffTimings.Total.TotalMilliseconds:F1} ms"),
            null);
        return VisionFinalizationSubmissionResult.Finalizing(run.Id, acceptedAtUtc, result.Tracks.Count, handOffTimings);
    }

    private async Task<(ProcessingRun Run, VideoAsset Video)?> LoadContextAsync(VisionJob job, CancellationToken cancellationToken)
    {
        var run = await db.ProcessingRuns.SingleOrDefaultAsync(x => x.Id == job.ProcessingRunId, cancellationToken);
        if (run is null) return null;
        var video = await db.VideoAssets.SingleOrDefaultAsync(x => x.Id == run.VideoAssetId, cancellationToken);
        return video is null ? null : (run, video);
    }
}
