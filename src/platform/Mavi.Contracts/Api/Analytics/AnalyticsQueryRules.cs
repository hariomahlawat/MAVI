namespace Mavi.Contracts.Api.Analytics;

/// <summary>
/// The closed vocabularies, bounds and problem codes of the Slice-6 read-only
/// analytics queries (plan §4.4, §5.3, §5.5, §6).
/// </summary>
/// <remarks>
/// These are transport-level facts: what a caller may ask for and what the server
/// refuses before doing work. Counting semantics live in the Application layer and
/// geometry in the Domain; nothing here decides what a number means.
/// </remarks>
public static class AnalyticsQueryRules
{
    // --- Query keys ---------------------------------------------------------
    //
    // Named here rather than spelled in the endpoint so the strict whitelist, the
    // tests and the client cannot drift apart.

    public const string FromUtcKey = "fromUtc";
    public const string ToUtcKey = "toUtc";
    public const string BucketSecondsKey = "bucketSeconds";
    public const string ObjectClassKey = "objectClass";
    public const string GridWidthKey = "gridWidth";
    public const string ProcessingRunIdKey = "processingRunId";

    public static readonly IReadOnlyList<string> AggregateQueryKeys =
        [FromUtcKey, ToUtcKey, BucketSecondsKey, ObjectClassKey];

    public static readonly IReadOnlyList<string> HeatmapQueryKeys =
        [FromUtcKey, ToUtcKey, ObjectClassKey, GridWidthKey, ProcessingRunIdKey];

    // --- Bucketing ----------------------------------------------------------

    public const int MinimumBucketSeconds = 60;
    public const int MaximumBucketSeconds = 86_400;

    /// <summary>
    /// The hard response-shape bound. This is not a performance claim: it is the
    /// largest number of buckets the contract will transport (plan §4.4).
    /// </summary>
    public const int MaximumBuckets = 512;

    /// <summary>
    /// Bucket sizes the UI picks from so an ordinary request stays well under the
    /// bound. Presentation policy only — the API accepts every integer in range.
    /// </summary>
    public static readonly IReadOnlyList<int> PreferredBucketSeconds =
        [60, 300, 900, 3_600, 21_600, 86_400];

    /// <summary>The bucket count a window and size produce, half-open on <c>toUtc</c>.</summary>
    /// <remarks>
    /// A window that is not a whole multiple of the bucket size ends in one short
    /// bucket, which is a real bucket and is counted. Returns 0 for an empty or
    /// inverted window, which validation rejects before this is asked.
    /// </remarks>
    public static long BucketCount(DateTimeOffset fromUtc, DateTimeOffset toUtc, int bucketSeconds)
    {
        if (bucketSeconds <= 0 || toUtc <= fromUtc)
        {
            return 0;
        }

        var span = toUtc - fromUtc;
        var ticksPerBucket = TimeSpan.TicksPerSecond * (long)bucketSeconds;
        return (span.Ticks + ticksPerBucket - 1) / ticksPerBucket;
    }

    public static bool IsBucketSeconds(int value) =>
        value >= MinimumBucketSeconds && value <= MaximumBucketSeconds;

    // --- Heatmap grid -------------------------------------------------------

    /// <summary>The only grid widths the heatmap accepts.</summary>
    public static readonly IReadOnlyList<int> GridWidths = [16, 32, 64, 128];

    public const int DefaultGridWidth = 64;

    public static bool IsGridWidth(int value) => GridWidths.Contains(value);

    /// <summary>
    /// The 16:9 height for a supported width. The grid spans the normalised frame
    /// extent, so cells need not be square source pixels over a non-16:9 frame.
    /// </summary>
    public static int GridHeightFor(int width) => width * 9 / 16;

    // --- Heatmap work bounds ------------------------------------------------
    //
    // Both are enforced from cheap scope metadata before a single trajectory
    // artefact is opened. The Track bound is on candidate Analysed outcomes, not
    // on samples actually read, because a guard that needs the I/O it bounds is
    // not a guard (plan §5.5).

    public const int MaximumHeatmapRuns = 50;
    public const int MaximumHeatmapTracks = 2_000;

    /// <summary>Which bounded dimension a rejected heatmap scope exceeded.</summary>
    public const string RunsDimension = "coveredRuns";
    public const string TracksDimension = "candidateTracks";

    // --- Problem codes ------------------------------------------------------

    public const string InvalidQueryCode = "analytics_query_invalid";
    public const string CameraNotFoundCode = "camera_not_found";
    public const string BucketCountInvalidCode = "analytics_bucket_count_invalid";
    public const string HeatmapScopeTooLargeCode = "analytics_heatmap_scope_too_large";
    public const string EvidenceUnreadableCode = "analytics_evidence_unreadable";

    // --- Object class -------------------------------------------------------

    public static readonly IReadOnlyList<string> ObjectClassValues = ["Person", "Vehicle"];

    public static bool IsObjectClass(string? value) =>
        value is not null && ObjectClassValues.Contains(value, StringComparer.Ordinal);
}
