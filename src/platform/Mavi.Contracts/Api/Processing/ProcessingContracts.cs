namespace Mavi.Contracts.Api.Processing;

public sealed record QueueProcessingResponse(Guid ProcessingRunId);

public sealed record ProcessingStatusResponse(
    string VideoStatus,
    ProcessingRunStatusResponse? LatestRun);

/// <summary>
/// One processing run's status, including whether the current scene geometry has been
/// applied to it.
/// </summary>
/// <remarks>
/// <paramref name="AnalyticsReadiness"/> is one of
/// <c>SceneAnalyticsContractRules.ReadinessValues</c>, derived per request rather than
/// stored: activating a new scene revision changes it for every run of that camera
/// without rewriting a row.
/// </remarks>
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
    int TracksCreated,
    string AnalyticsReadiness);
