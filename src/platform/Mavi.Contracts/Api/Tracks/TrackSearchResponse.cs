using System.Text.Json.Serialization;
using Mavi.Contracts.Api.Analytics;

namespace Mavi.Contracts.Api.Tracks;

/// <summary>A page of Track results.</summary>
/// <remarks>
/// <paramref name="AnalyticsCoverage"/> is present only for an analytics-dependent
/// query (plan §H, §S) and is omitted from the JSON otherwise, so an ordinary search
/// response is byte-for-byte what it was before Slice 4.
/// <para>
/// <paramref name="AttributeCoverage"/> is present exactly when the query carried <c>attribute</c> (PoC S5).
/// </para>
/// <para>
/// <paramref name="PlateCoverage"/> is present exactly when the query carried <c>plateText</c>
/// (Stage 4, plan §5.4), so an empty plate result is never read as "no such plate".
/// </para>
/// </remarks>
public sealed record TrackSearchResponse(
    IReadOnlyList<TrackSearchItemResponse> Items,
    string? NextCursor,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    AnalyticsCoverageResponse? AnalyticsCoverage = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    PlateCoverageResponse? PlateCoverage = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    AppearanceSearchResponse? Appearance = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    AttributeCoverageResponse? AttributeCoverage = null);

/// <summary>One Track result.</summary>
/// <remarks>
/// <paramref name="Analytics"/> is the bounded explanation of why the row matched an
/// analytics-dependent query, for the identity that query pinned. It is absent on an
/// ordinary search.
/// <para>
/// <paramref name="ObjectSubclass"/> is the operator-facing vehicle subclass (Stage 3, X2):
/// present only on a Vehicle whose persisted subclass the exposure policy allows (X1:
/// <c>car</c> from the release profile), and omitted otherwise. It refines
/// <paramref name="ObjectClass"/>; it never replaces it.
/// </para>
/// <para>
/// <paramref name="Plate"/> explains a <c>plateText</c> match (Stage 4); absent otherwise.
/// </para>
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
    TrackItemAnalyticsResponse? Analytics = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? ObjectSubclass = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    TrackItemPlateResponse? Plate = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    double? AppearanceScore = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    IReadOnlyList<TrackItemAttributeResponse>? Attributes = null);
