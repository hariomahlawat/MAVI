namespace Mavi.Contracts.Api.Processing;

public sealed record QueueProcessingResponse(Guid ProcessingRunId);

public sealed record ProcessingStatusResponse(
    string VideoStatus,
    ProcessingRunStatusResponse? LatestRun);

public sealed record ProcessingRunStatusResponse(
    Guid ProcessingRunId,
    string Status,
    string Pipeline,
    string PipelineVersion,
    string? WorkerId,
    DateTimeOffset QueuedAtUtc,
    DateTimeOffset? StartedAtUtc,
    DateTimeOffset? CompletedAtUtc,
    double ProgressPercent,
    int AttemptCount,
    string? FailureCode,
    long FramesProcessed,
    int TracksCreated);
