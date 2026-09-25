namespace Mavi.Contracts.Api.Processing;

public sealed record QueueProcessingResponse(Guid ProcessingRunId);

public sealed record ProcessingStatusResponse(
    string VideoStatus,
    ProcessingRunStatusResponse? LatestRun);

/// <summary>
/// Where a processing run is in its control-plane lifecycle, projected from the VisionJob
/// (S1.4 B3 asynchronous finalization plan §3.2, §12). <see cref="Finalizing"/> is the
/// worker having handed off and the platform still sealing and publishing; the run's own
/// status stays <c>Running</c> until publication, so this is the field that tells an operator
/// inference is over.
/// </summary>
public static class ProcessingPhases
{
    public const string Queued = "queued";
    public const string Processing = "processing";
    public const string Finalizing = "finalizing";
    public const string Completed = "completed";
    public const string Failed = "failed";

    public static IReadOnlyList<string> Values { get; } = [Queued, Processing, Finalizing, Completed, Failed];
}

/// <summary>
/// One processing run's status, including whether the current scene geometry has been
/// applied to it.
/// </summary>
/// <remarks>
/// <para>
/// <paramref name="AnalyticsReadiness"/> is one of
/// <c>SceneAnalyticsContractRules.ReadinessValues</c>, derived per request rather than
/// stored: activating a new scene revision changes it for every run of that camera
/// without rewriting a row.
/// </para>
/// <para>
/// <paramref name="Phase"/> is one of <see cref="ProcessingPhases.Values"/>. <paramref name="Status"/>
/// remains the run's own <c>ProcessingRunStatus</c>; <paramref name="FramesProcessed"/> and
/// <paramref name="TracksCreated"/> stay authoritative-only and are zero until publication.
/// </para>
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
    string AnalyticsReadiness,
    string Phase);
