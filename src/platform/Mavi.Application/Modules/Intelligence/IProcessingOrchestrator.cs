using Mavi.Contracts.Api.Processing;
using Mavi.Domain.Processing;

namespace Mavi.Application.Modules.Intelligence;

public sealed record ProcessingRunAttestationSource(
    Guid ProcessingRunId,
    Guid VideoAssetId,
    DateTimeOffset CompletedAtUtc,
    string PipelineVersion,
    string? DetectorName,
    string? DetectorVersion,
    string? TrackerName,
    string? TrackerVersion,
    long FramesProcessed,
    int TracksCreated,
    long ProcessingDurationMs,
    string? RuntimeProvenanceJson);

public sealed record QueueProcessingResult(bool IsSuccess, Guid? ProcessingRunId, string? ErrorCode);
public sealed record ProcessingStatusResult(bool Found, string VideoStatus, ProcessingRunStatusView? LatestRun);
public sealed record ProcessingRunStatusView(Guid ProcessingRunId, string Status, string Pipeline, string PipelineVersion,
    string? WorkerId, DateTimeOffset QueuedAtUtc, DateTimeOffset? StartedAtUtc, DateTimeOffset? CompletedAtUtc,
    double ProgressPercent, int AttemptCount, string? FailureCode,
    long FramesProcessed = 0, int TracksCreated = 0, string Phase = ProcessingPhases.Processing);

/// <summary>
/// The status <c>phase</c> of the latest run, derived from its job's status (S1.4 B3
/// asynchronous finalization plan §11). <c>ProcessingRunStatus</c> itself has no Finalizing
/// value: the run stays Running until the finalizer publishes.
/// </summary>
public static class ProcessingPhaseRule
{
    public static string FromJobStatus(VisionJobStatus status) => status switch
    {
        VisionJobStatus.Queued => ProcessingPhases.Queued,
        VisionJobStatus.Leased => ProcessingPhases.Processing,
        VisionJobStatus.Finalizing => ProcessingPhases.Finalizing,
        VisionJobStatus.Completed => ProcessingPhases.Completed,
        VisionJobStatus.Failed or VisionJobStatus.Cancelled => ProcessingPhases.Failed,
        _ => throw new ArgumentOutOfRangeException(nameof(status), status, "Unknown vision job status."),
    };
}
public sealed record VisionLeaseView(Guid JobId, Guid ProcessingRunId, Guid VideoAssetId,
    Guid CameraId, string WorkerId, string LeaseToken, string Pipeline, string PipelineVersion, string SourceStorageKey, string SourceSha256,
    long SourceSizeBytes, DateTimeOffset RecordingStartUtc, DateTimeOffset RecordingEndUtc, long DurationMs,
    int Width, int Height, int FrameRateNumerator, int FrameRateDenominator, int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc, string RecordingTimeZoneId, int RecordingUtcOffsetMinutes);
public sealed record OrchestrationResult(bool IsSuccess, string? ErrorCode)
{
    public static OrchestrationResult Success() => new(true, null);
    public static OrchestrationResult Failure(string code) => new(false, code);
}

public abstract record HeartbeatResult
{
    private HeartbeatResult() { }

    public sealed record Success(double ProgressPercent, DateTimeOffset LeaseExpiresAtUtc) : HeartbeatResult;
    public sealed record Failure(string ErrorCode) : HeartbeatResult;
}

public interface IProcessingOrchestrator
{
    Task<QueueProcessingResult> QueueAsync(Guid videoId, CancellationToken cancellationToken);
    Task<ProcessingStatusResult> GetStatusAsync(Guid videoId, CancellationToken cancellationToken);
    Task<ProcessingRunAttestationSource?> GetCompletedRunAttestationAsync(Guid processingRunId, CancellationToken cancellationToken);
    Task<VisionLeaseView?> LeaseAsync(string workerId, CancellationToken cancellationToken);
    Task<HeartbeatResult> HeartbeatAsync(Guid jobId, string workerId, string leaseToken, double progressPercent, CancellationToken cancellationToken);
    Task<OrchestrationResult> FailAsync(Guid jobId, string workerId, string leaseToken, string failureCode, string? failureMessage, CancellationToken cancellationToken);
}
