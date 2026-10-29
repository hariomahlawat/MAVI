using Mavi.Contracts.Api.Analytics;

namespace Mavi.Contracts.Api.Events;

// Deterministic analytic events (ADR-025). Every event is a derivation from
// persisted scene-analytics facts by one versioned catalogue rule; nothing here is
// a model output, and nothing here asserts identity.

public sealed record RuleParameterResponse(
    string Name,
    string? Value,
    string? Unit,
    string Source,
    string Reference);

public sealed record RuleDefinitionResponse(
    string RuleId,
    int RuleVersion,
    string Title,
    string Description,
    bool Enabled,
    string? DisabledReason,
    IReadOnlyList<RuleParameterResponse> Parameters);

public sealed record RuleCatalogueResponse(
    string CatalogueVersion,
    string CatalogueSha256,
    IReadOnlyList<RuleDefinitionResponse> Rules);

/// <summary>
/// Scene-analytics coverage for the resolved identity, plus the evaluated runs whose
/// events are not derived yet. Neither kind of gap is ever shown as zero events.
/// </summary>
public sealed record AnalyticEventCoverageResponse(
    AnalyticsCoverageResponse Analytics,
    int DerivedRuns,
    int EventsPendingRuns)
{
    public bool Complete => Analytics.Complete && EventsPendingRuns == 0;
}

public sealed record AnalyticEventSummaryResponse(
    Guid EventId,
    string RuleId,
    int RuleVersion,
    DateTimeOffset StartUtc,
    DateTimeOffset EndUtc,
    long StartOffsetMs,
    long EndOffsetMs,
    Guid VideoAssetId,
    Guid ProcessingRunId,
    Guid? PrimaryTrackId,
    string? ObjectClass,
    Guid? ZoneId,
    string? ZoneName,
    Guid? LineId,
    string? LineName,
    string? Direction,
    string? DirectionLabel,
    int ParticipantCount);

public sealed record AnalyticEventCrossingCountsResponse(
    Guid LineId,
    string Name,
    string AToBLabel,
    string BToALabel,
    IReadOnlyList<int> AToBCounts,
    IReadOnlyList<int> BToACounts);

public sealed record AnalyticEventRuleCountResponse(string RuleId, int Count);

/// <summary>One camera's events in one window, under one resolved identity.</summary>
/// <remarks>
/// <paramref name="Truncated"/> is true when more events matched than
/// <paramref name="Limit"/>; the counts are always over every matching event.
/// <paramref name="RuleCounts"/> and <paramref name="CrossingCounts"/> name only rules that
/// ran: a rule that is disabled, filtered out, or has no derived run in scope is absent,
/// never reported as zero.
/// </remarks>
public sealed record AnalyticEventTimelineResponse(
    Guid CameraId,
    Guid? SceneRevisionId,
    int? SceneRevisionNumber,
    string AnalyticsAlgorithmVersion,
    string CatalogueVersion,
    long SnapshotVisibilitySequence,
    DateTimeOffset FromUtc,
    DateTimeOffset ToUtc,
    int BucketSeconds,
    AnalyticEventCoverageResponse Coverage,
    IReadOnlyList<AnalyticsBucketResponse> Buckets,
    IReadOnlyList<AnalyticEventRuleCountResponse> RuleCounts,
    IReadOnlyList<AnalyticEventCrossingCountsResponse> CrossingCounts,
    IReadOnlyList<AnalyticEventSummaryResponse> Events,
    int Limit,
    bool Truncated);

public sealed record AnalyticEventParticipantResponse(
    Guid TrackId,
    string Role,
    string ObjectClass,
    Guid VideoAssetId,
    long StartOffsetMs,
    long EndOffsetMs,
    string? ThumbnailContentUrl);

public sealed record AnalyticEventInputResponse(string Kind, string Reference, long? StartOffsetMs, long? EndOffsetMs);

public sealed record AnalyticEventParameterResponse(string Name, string Value, string? Unit, string Source, string Reference);

public sealed record AnalyticEventDetailValueResponse(string Name, string Value);

/// <summary>One event with its full provenance envelope (ADR-025 §4).</summary>
public sealed record AnalyticEventDetailResponse(
    AnalyticEventSummaryResponse Event,
    Guid CameraId,
    Guid SceneAnalysisId,
    Guid SceneRevisionId,
    int SceneRevisionNumber,
    string AnalyticsAlgorithmVersion,
    string CatalogueVersion,
    string CatalogueSha256,
    string InputSha256,
    DateTimeOffset DerivedAtUtc,
    IReadOnlyList<AnalyticEventParticipantResponse> Participants,
    IReadOnlyList<AnalyticEventInputResponse> Inputs,
    IReadOnlyList<AnalyticEventParameterResponse> Parameters,
    IReadOnlyList<AnalyticEventDetailValueResponse> Details);

/// <summary>Query keys and bounds of the Events read surface.</summary>
public static class AnalyticEventQueryRules
{
    public const string RuleIdKey = "ruleId";
    public const string LimitKey = "limit";

    public static readonly IReadOnlyList<string> TimelineQueryKeys =
        [AnalyticsQueryRules.FromUtcKey, AnalyticsQueryRules.ToUtcKey, AnalyticsQueryRules.BucketSecondsKey, RuleIdKey, LimitKey];

    public const int DefaultLimit = 1_000;
    public const int MaximumLimit = 5_000;

    public const string InvalidQueryCode = "analytic_events_query_invalid";
    public const string CameraNotFoundCode = "camera_not_found";
    public const string EventNotFoundCode = "analytic_event_not_found";
}
