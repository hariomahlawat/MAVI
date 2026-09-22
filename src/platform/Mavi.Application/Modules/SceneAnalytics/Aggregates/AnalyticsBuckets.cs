namespace Mavi.Application.Modules.SceneAnalytics.Aggregates;

/// <summary>One bucket of a requested window, half-open: <c>[StartUtc, EndUtc)</c>.</summary>
public readonly record struct AnalyticsBucket(DateTimeOffset StartUtc, DateTimeOffset EndUtc);

/// <summary>
/// Bucket generation and assignment (plan §3.3).
/// </summary>
/// <remarks>
/// <para>
/// Buckets are anchored to <c>fromUtc</c>, never to wall-clock or epoch boundaries,
/// so the same request produces the same buckets in every timezone and a shared or
/// bookmarked window is reproducible.
/// </para>
/// <para>
/// Everything here is half-open. An event exactly at a bucket start belongs to that
/// bucket; one exactly at a bucket end belongs to the next; one exactly at
/// <c>toUtc</c> is outside the request altogether. That is the single rule that
/// stops two adjacent buckets both claiming a boundary event.
/// </para>
/// </remarks>
public static class AnalyticsBuckets
{
    /// <summary>
    /// The window's buckets in order. The last one is short when the window is not a
    /// whole multiple of the bucket size, and is clipped to <paramref name="toUtc"/>
    /// rather than run past the request.
    /// </summary>
    public static IReadOnlyList<AnalyticsBucket> Build(
        DateTimeOffset fromUtc,
        DateTimeOffset toUtc,
        int bucketSeconds)
    {
        if (bucketSeconds <= 0 || toUtc <= fromUtc)
        {
            return [];
        }

        var size = TimeSpan.FromSeconds(bucketSeconds);
        var buckets = new List<AnalyticsBucket>();
        var start = fromUtc;
        while (start < toUtc)
        {
            var end = start + size;
            buckets.Add(new AnalyticsBucket(start, end > toUtc ? toUtc : end));
            start = end;
        }

        return buckets;
    }

    /// <summary>
    /// Which bucket an instant falls in, or -1 when it is outside the window.
    /// </summary>
    /// <remarks>
    /// Computed by division from the anchor rather than by scanning, so assignment
    /// cannot disagree with <see cref="Build"/> about a boundary. An instant exactly
    /// at <paramref name="toUtc"/> is outside: the window is half-open, and the
    /// division would otherwise hand it to a bucket that does not exist.
    /// </remarks>
    public static int IndexOf(
        DateTimeOffset instant,
        DateTimeOffset fromUtc,
        int bucketSeconds,
        int bucketCount)
    {
        if (bucketSeconds <= 0 || bucketCount <= 0 || instant < fromUtc)
        {
            return -1;
        }

        var ticksPerBucket = TimeSpan.TicksPerSecond * (long)bucketSeconds;
        var offsetTicks = (instant - fromUtc).Ticks;
        var index = offsetTicks / ticksPerBucket;
        return index >= bucketCount ? -1 : (int)index;
    }

    /// <summary>
    /// Whether an interval is genuinely active during a bucket: <c>start &lt; end</c>
    /// on both sides, so touching at an endpoint alone is not activity (plan §4.2).
    /// </summary>
    public static bool PositivelyOverlaps(
        DateTimeOffset intervalStart,
        DateTimeOffset intervalEnd,
        DateTimeOffset bucketStart,
        DateTimeOffset bucketEnd) =>
        intervalStart < bucketEnd && intervalEnd > bucketStart;
}
