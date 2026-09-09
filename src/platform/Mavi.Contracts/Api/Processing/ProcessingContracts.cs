namespace Mavi.Contracts.Api.Processing;

public sealed record LeaseVisionJobRequest(string? WorkerId);
public sealed record VisionJobHeartbeatRequest(string? WorkerId, double ProgressPercent);
public sealed record FailVisionJobRequest(string? WorkerId, string? FailureCode, string? FailureMessage);
public sealed record QueueProcessingResponse(Guid ProcessingRunId);
