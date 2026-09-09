namespace Mavi.Application.Modules.Intelligence;

public sealed record QueueProcessingResult(bool IsSuccess, Guid? ProcessingRunId, string? ErrorCode);
public sealed record ProcessingStatusResult(bool Found, string VideoStatus, ProcessingRunStatusView? LatestRun);
public sealed record ProcessingRunStatusView(Guid ProcessingRunId, string Status, string Pipeline, string PipelineVersion,
    string? WorkerId, DateTimeOffset QueuedAtUtc, DateTimeOffset? StartedAtUtc, DateTimeOffset? CompletedAtUtc,
    double ProgressPercent, int AttemptCount, string? FailureCode);
public sealed record VisionLeaseView(Guid JobId, Guid ProcessingRunId, Guid VideoAssetId,
    Guid CameraId, string WorkerId, string LeaseToken, string Pipeline, string PipelineVersion, string SourceStorageKey, string SourceSha256,
    long SourceSizeBytes, DateTimeOffset RecordingStartUtc, DateTimeOffset RecordingEndUtc, long DurationMs,
    int Width, int Height, int FrameRateNumerator, int FrameRateDenominator, int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc, string RecordingTimeZoneId, int RecordingUtcOffsetMinutes);
public sealed record OrchestrationResult(bool IsSuccess, string? ErrorCode, double? ProgressPercent = null, DateTimeOffset? LeaseExpiresAtUtc = null)
{
    public static OrchestrationResult Success() => new(true, null);
    public static OrchestrationResult Failure(string code) => new(false, code);
}

public interface IProcessingOrchestrator
{
    Task<QueueProcessingResult> QueueAsync(Guid videoId, CancellationToken cancellationToken);
    Task<ProcessingStatusResult> GetStatusAsync(Guid videoId, CancellationToken cancellationToken);
    Task<VisionLeaseView?> LeaseAsync(string workerId, CancellationToken cancellationToken);
    Task<OrchestrationResult> HeartbeatAsync(Guid jobId, string workerId, string leaseToken, double progressPercent, CancellationToken cancellationToken);
    Task<OrchestrationResult> FailAsync(Guid jobId, string workerId, string leaseToken, string failureCode, string? failureMessage, CancellationToken cancellationToken);
}
