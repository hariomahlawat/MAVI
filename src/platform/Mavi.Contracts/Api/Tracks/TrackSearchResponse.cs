using System.Text.Json.Serialization;
using Mavi.Contracts.Api.Analytics;

namespace Mavi.Contracts.Api.Tracks;

/// <summary>A page of Track results.</summary>
/// <remarks>
/// <paramref name="AnalyticsCoverage"/> is present only for an analytics-dependent
/// query (plan §H, §S) and is omitted from the JSON otherwise, so an ordinary search
/// response is byte-for-byte what it was before Slice 4.
/// </remarks>
public sealed record TrackSearchResponse(
    IReadOnlyList<TrackSearchItemResponse> Items,
    string? NextCursor,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    AnalyticsCoverageResponse? AnalyticsCoverage = null);

/// <summary>One Track result.</summary>
/// <remarks>
/// <paramref name="Analytics"/> is the bounded explanation of why the row matched an
/// analytics-dependent query, for the identity that query pinned. It is absent on an
/// ordinary search.
/// </remarks>
public sealed record TrackSearchItemResponse(
    Guid Id,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    string ObjectClass,
    DateTimeOffset StartTimestampUtc,
    DateTimeOffset EndTimestampUtc,
    long StartOffsetMs,
    long EndOffsetMs,
    long DurationMs,
    int DetectionCount,
    double MeanConfidence,
    double MaxConfidence,
    string ReviewStatus,
    Guid? ThumbnailArtifactId,
    string? ThumbnailContentUrl,
    string VideoContentUrl,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    TrackItemAnalyticsResponse? Analytics = null);
