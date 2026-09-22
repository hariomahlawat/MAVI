using System.Text.Json.Serialization;

namespace Mavi.Contracts.Api.Analytics;

// Scene Analytics Slice 6: the read-only aggregate and heatmap projections.
//
// Every response here is bound to one analytical identity — camera, scene
// revision, algorithm version and the visibility sequence the server resolved it
// against — and carries the coverage that says how much of its scope was actually
// evaluated. The client never reconstructs that identity: what the server
// returned is what the numbers mean.
//
// No internal analysis id, claim/fencing data, storage key or cursor-signing
// material crosses this boundary (plan §4.3, §16).

/// <summary>One bucket of the requested window, half-open: <c>[StartUtc, EndUtc)</c>.</summary>
public sealed record AnalyticsBucketResponse(
    DateTimeOffset StartUtc,
    DateTimeOffset EndUtc);

/// <summary>
/// One zone's series for the window, for a zone enabled in the resolved revision.
/// </summary>
/// <remarks>
/// Array lengths always equal the response's bucket count.
/// <para>
/// The window-level fields are not sums of their series. <paramref name="WindowUniqueTrackCount"/>
/// counts a Track once for the whole window however many buckets it appears in,
/// and <paramref name="PeakOccupancy"/> is a maximum, not a total. Only the event
/// counts — entries and exits — are additive across disjoint buckets, which is why
/// the non-additive answers are transported explicitly rather than left for a
/// caller to derive incorrectly (plan §4.3).
/// </para>
/// <para>
/// <paramref name="RepeatedVisitTrackCount"/> is a whole-Track summary metric read
/// from the persisted per-Track zone summary: Tracks that visited this zone at
/// least twice anywhere in their own life. It is deliberately not "two visits
/// inside this window".
/// </para>
/// </remarks>
public sealed record AnalyticsZoneSeriesResponse(
    Guid ZoneId,
    string Name,
    IReadOnlyList<int> EntryCounts,
    IReadOnlyList<int> ExitCounts,
    IReadOnlyList<int> UniqueTrackCounts,
    IReadOnlyList<int> OccupancyAtStart,
    int PeakOccupancy,
    DateTimeOffset? PeakOccupancyAtUtc,
    int WindowEntryCount,
    int WindowExitCount,
    int WindowUniqueTrackCount,
    int RepeatedVisitTrackCount);

/// <summary>One trip line's crossing series, for a line enabled in the resolved revision.</summary>
public sealed record AnalyticsLineSeriesResponse(
    Guid LineId,
    string Name,
    string AToBLabel,
    string BToALabel,
    IReadOnlyList<int> AToBCounts,
    IReadOnlyList<int> BToACounts,
    int WindowAToBCount,
    int WindowBToACount);

/// <summary>
/// Distinct analysed Tracks of one object class whose Track interval positively
/// overlaps each bucket.
/// </summary>
/// <remarks>
/// <paramref name="WindowDistinctTrackCount"/> counts each Track once for the whole
/// window; summing <paramref name="Counts"/> would count a Track once per bucket it
/// spans.
/// </remarks>
public sealed record AnalyticsClassSeriesResponse(
    string ObjectClass,
    IReadOnlyList<int> Counts,
    int WindowDistinctTrackCount);

/// <summary>The bucketed aggregate answer for one camera and window.</summary>
/// <remarks>
/// Disabled zones and trip lines are absent rather than present as rows of zeros:
/// they were not evaluated, and a zero row would read as an observed absence
/// (plan §4.3).
/// </remarks>
public sealed record AnalyticsAggregateResponse(
    Guid CameraId,
    Guid? SceneRevisionId,
    int? SceneRevisionNumber,
    string AlgorithmVersion,
    long SnapshotVisibilitySequence,
    DateTimeOffset FromUtc,
    DateTimeOffset ToUtc,
    int BucketSeconds,
    string? ObjectClass,
    AnalyticsCoverageResponse Coverage,
    IReadOnlyList<AnalyticsBucketResponse> Buckets,
    IReadOnlyList<AnalyticsZoneSeriesResponse> Zones,
    IReadOnlyList<AnalyticsLineSeriesResponse> Lines,
    IReadOnlyList<AnalyticsClassSeriesResponse> Classes);

/// <summary>
/// The on-demand trajectory-sample density map for one camera and window.
/// </summary>
/// <remarks>
/// <paramref name="Values"/> is row-major with exactly
/// <paramref name="GridWidth"/> × <paramref name="GridHeight"/> entries, in
/// normalised source-frame coordinates. It is sample density, not people density
/// and not probability; the UI is required to say so.
/// <para>
/// No raster is returned or persisted (plan §5.4).
/// </para>
/// </remarks>
public sealed record AnalyticsHeatmapResponse(
    Guid CameraId,
    Guid? SceneRevisionId,
    int? SceneRevisionNumber,
    string AlgorithmVersion,
    long SnapshotVisibilitySequence,
    DateTimeOffset FromUtc,
    DateTimeOffset ToUtc,
    string? ObjectClass,
    Guid? ProcessingRunId,
    AnalyticsCoverageResponse Coverage,
    int GridWidth,
    int GridHeight,
    long SampleCount,
    int TrackCount,
    int MaxCellValue,
    IReadOnlyList<int> Values);
