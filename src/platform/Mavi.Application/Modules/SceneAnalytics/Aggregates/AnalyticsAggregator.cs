using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.SceneAnalytics.Aggregates;

/// <summary>One zone's computed series for a window.</summary>
public sealed record ZoneSeries(
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

/// <summary>One trip line's computed series.</summary>
public sealed record LineSeries(
    Guid LineId,
    string Name,
    string AToBLabel,
    string BToALabel,
    IReadOnlyList<int> AToBCounts,
    IReadOnlyList<int> BToACounts,
    int WindowAToBCount,
    int WindowBToACount);

/// <summary>One object class's computed series.</summary>
public sealed record ClassSeries(
    ObjectClass ObjectClass,
    IReadOnlyList<int> Counts,
    int WindowDistinctTrackCount);

/// <summary>The whole computed answer for one window.</summary>
public sealed record AnalyticsSeriesSet(
    IReadOnlyList<AnalyticsBucket> Buckets,
    IReadOnlyList<ZoneSeries> Zones,
    IReadOnlyList<LineSeries> Lines,
    IReadOnlyList<ClassSeries> Classes);

/// <summary>
/// The frozen Slice-6 counting rules (plan §4.2), in one place, over persisted facts.
/// </summary>
/// <remarks>
/// <para>
/// This is pure arithmetic on projections the repository already fetched. Keeping it
/// out of SQL is deliberate: these rules are the part of the slice most likely to be
/// got subtly wrong — half-open boundaries, distinct-versus-event counting,
/// occupancy sampled rather than integrated — and here every one of them can be
/// pinned by a golden fixture without a database. The repository's job is to fetch
/// exactly the covered facts; this decides what they mean.
/// </para>
/// <para>
/// Nothing here infers. Every number is a count of persisted facts.
/// </para>
/// </remarks>
public static class AnalyticsAggregator
{
    public static AnalyticsSeriesSet Compute(
        AnalyticsFactSet facts,
        DateTimeOffset fromUtc,
        DateTimeOffset toUtc,
        int bucketSeconds)
    {
        ArgumentNullException.ThrowIfNull(facts);

        var buckets = AnalyticsBuckets.Build(fromUtc, toUtc, bucketSeconds);
        return new AnalyticsSeriesSet(
            buckets,
            ComputeZones(facts, buckets, fromUtc, bucketSeconds),
            ComputeLines(facts, buckets, fromUtc, bucketSeconds),
            ComputeClasses(facts, buckets, fromUtc, toUtc));
    }

    private static List<ZoneSeries> ComputeZones(
        AnalyticsFactSet facts,
        IReadOnlyList<AnalyticsBucket> buckets,
        DateTimeOffset fromUtc,
        int bucketSeconds)
    {
        var count = buckets.Count;
        var series = new List<ZoneSeries>(facts.Zones.Count);

        foreach (var zone in facts.Zones)
        {
            var visits = facts.ZoneVisits.Where(visit => visit.ZoneId == zone.ZoneId).ToList();

            var entries = new int[count];
            var exits = new int[count];
            var occupancy = new int[count];
            // Distinct Tracks per bucket, so a Track visiting twice inside one bucket
            // counts once there. Sets rather than counters is the whole point.
            var uniquePerBucket = new HashSet<Guid>[count];
            for (var i = 0; i < count; i++)
            {
                uniquePerBucket[i] = [];
            }

            var windowUnique = new HashSet<Guid>();

            foreach (var visit in visits)
            {
                // An entry event exists only where the Track actually crossed in. A
                // visit that began inside the zone was already there; counting it
                // would invent a crossing the engine did not record.
                if (!visit.BeganInside)
                {
                    var index = AnalyticsBuckets.IndexOf(visit.EntryUtc, fromUtc, bucketSeconds, count);
                    if (index >= 0)
                    {
                        entries[index]++;
                    }
                }

                if (!visit.EndedInside)
                {
                    var index = AnalyticsBuckets.IndexOf(visit.ExitUtc, fromUtc, bucketSeconds, count);
                    if (index >= 0)
                    {
                        exits[index]++;
                    }
                }

                for (var i = 0; i < count; i++)
                {
                    var bucket = buckets[i];

                    if (AnalyticsBuckets.PositivelyOverlaps(visit.EntryUtc, visit.ExitUtc, bucket.StartUtc, bucket.EndUtc))
                    {
                        uniquePerBucket[i].Add(visit.TrackId);
                        windowUnique.Add(visit.TrackId);
                    }

                    // Occupancy is sampled at the bucket's start instant, not
                    // integrated over the bucket. A visit occupies the zone at that
                    // instant when it had entered by then and had not yet left.
                    if (visit.EntryUtc <= bucket.StartUtc && visit.ExitUtc > bucket.StartUtc)
                    {
                        occupancy[i]++;
                    }
                }
            }

            var peak = 0;
            DateTimeOffset? peakAt = null;
            for (var i = 0; i < count; i++)
            {
                // Strictly greater, walking forward: a tie keeps the earliest instant.
                if (occupancy[i] > peak)
                {
                    peak = occupancy[i];
                    peakAt = buckets[i].StartUtc;
                }
            }

            var repeated = facts.ZoneSummaries
                .Where(summary => summary.ZoneId == zone.ZoneId && summary.VisitCount >= 2)
                .Select(summary => summary.TrackId)
                .Distinct()
                .Count();

            series.Add(new ZoneSeries(
                zone.ZoneId,
                zone.Name,
                entries,
                exits,
                uniquePerBucket.Select(set => set.Count).ToArray(),
                occupancy,
                peak,
                // Null rather than the window start when nothing was ever present:
                // "peak 0 at 09:00" would read as an observation about 09:00.
                peak == 0 ? null : peakAt,
                entries.Sum(),
                exits.Sum(),
                windowUnique.Count,
                repeated));
        }

        return series;
    }

    private static List<LineSeries> ComputeLines(
        AnalyticsFactSet facts,
        IReadOnlyList<AnalyticsBucket> buckets,
        DateTimeOffset fromUtc,
        int bucketSeconds)
    {
        var count = buckets.Count;
        var series = new List<LineSeries>(facts.Lines.Count);

        foreach (var line in facts.Lines)
        {
            var aToB = new int[count];
            var bToA = new int[count];

            foreach (var crossing in facts.LineCrossings.Where(x => x.LineId == line.LineId))
            {
                var index = AnalyticsBuckets.IndexOf(crossing.TimestampUtc, fromUtc, bucketSeconds, count);
                if (index < 0)
                {
                    continue;
                }

                // The two directions are independent counts of the same line, never a
                // net flow: a crossing each way is two crossings, not zero.
                if (crossing.IsAToB)
                {
                    aToB[index]++;
                }
                else
                {
                    bToA[index]++;
                }
            }

            series.Add(new LineSeries(
                line.LineId,
                line.Name,
                line.AToBLabel,
                line.BToALabel,
                aToB,
                bToA,
                aToB.Sum(),
                bToA.Sum()));
        }

        return series;
    }

    private static List<ClassSeries> ComputeClasses(
        AnalyticsFactSet facts,
        IReadOnlyList<AnalyticsBucket> buckets,
        DateTimeOffset fromUtc,
        DateTimeOffset toUtc)
    {
        var count = buckets.Count;
        var series = new List<ClassSeries>();

        // Every class in the closed vocabulary gets a series, so an absent class reads
        // as an observed zero within a covered scope rather than as a missing row.
        foreach (var objectClass in Enum.GetValues<ObjectClass>().OrderBy(value => value.ToString(), StringComparer.Ordinal))
        {
            var tracks = facts.TrackIntervals.Where(track => track.ObjectClass == objectClass).ToList();
            var counts = new int[count];
            var windowDistinct = new HashSet<Guid>();

            for (var i = 0; i < count; i++)
            {
                var bucket = buckets[i];
                var inBucket = new HashSet<Guid>();
                foreach (var track in tracks)
                {
                    if (AnalyticsBuckets.PositivelyOverlaps(track.StartUtc, track.EndUtc, bucket.StartUtc, bucket.EndUtc))
                    {
                        inBucket.Add(track.TrackId);
                    }
                }

                counts[i] = inBucket.Count;
            }

            foreach (var track in tracks)
            {
                // The window's own distinct total, over the whole half-open window.
                // Summing the per-bucket counts would count a Track once for every
                // bucket it spans, which is why this is transported separately.
                if (AnalyticsBuckets.PositivelyOverlaps(track.StartUtc, track.EndUtc, fromUtc, toUtc))
                {
                    windowDistinct.Add(track.TrackId);
                }
            }

            series.Add(new ClassSeries(objectClass, counts, windowDistinct.Count));
        }

        return series;
    }
}
