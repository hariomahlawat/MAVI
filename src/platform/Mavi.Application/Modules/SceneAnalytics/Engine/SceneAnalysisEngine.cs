using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// Turns one Track's trajectory and one scene revision into the derived facts a
/// later slice will persist.
/// </summary>
/// <remarks>
/// <para>
/// Pure by construction: it reads no database, opens no file, performs no I/O and
/// never asks the clock what time it is. The same inputs produce the same facts on
/// every host, which is what makes an analysis reproducible from the revision and
/// algorithm version recorded beside it.
/// </para>
/// <para>
/// Results are emitted in a fixed order so that two runs of the engine are
/// comparable byte for byte after serialisation. The order is chosen to be stable
/// rather than meaningful: sorting by identity only guarantees that the same input
/// yields the same sequence, since a GUID does not sort by age.
/// </para>
/// </remarks>
public static class SceneAnalysisEngine
{
    public static TrackAnalysisResult Analyse(
        IReadOnlyList<TrajectorySample> samples,
        SceneConfigurationRevision revision,
        ObjectClass objectClass,
        SceneAnalyticsParameters parameters)
    {
        ArgumentNullException.ThrowIfNull(samples);
        ArgumentNullException.ThrowIfNull(revision);
        ArgumentNullException.ThrowIfNull(parameters);

        var path = TrajectoryPath.Create(samples, parameters);

        // Disabled geometry is not evaluated at all: an operator who switches a zone
        // off is asking for no facts from it, not for empty ones.
        var zones = revision.Zones.Where(zone => zone.Enabled).ToArray();
        var lines = revision.TripLines.Where(line => line.Enabled).ToArray();

        var visits = new List<ZoneVisitFact>();
        var summaries = new List<ZoneSummaryFact>();
        foreach (var zone in zones)
        {
            var zoneVisits = ZoneVisitDetector.Detect(path, zone, parameters);
            visits.AddRange(zoneVisits);
            summaries.Add(LoiteringRule.Summarise(zone, objectClass, zoneVisits, parameters));
        }

        var crossings = new List<LineCrossingFact>();
        foreach (var line in lines)
        {
            crossings.AddRange(LineCrossingDetector.Detect(path, line, parameters));
        }

        var intervals = StationaryDetector.Detect(path, objectClass, parameters);
        var stationaryZones = StationaryDetector.ZonesContaining(
            path,
            intervals,
            [.. zones.Select(zone => (zone.ZoneId, zone.Vertices))]);

        visits.Sort(CompareVisits);
        summaries.Sort(static (left, right) => left.ZoneId.CompareTo(right.ZoneId));
        crossings.Sort(CompareCrossings);

        return new TrackAnalysisResult(
            AnalysisReferencePoint.BoundingBoxCentre,
            path.Count,
            path.GapCount,
            path.GapTotalMs,
            visits,
            summaries,
            crossings,
            BuildMotion(path, intervals, stationaryZones, parameters));
    }

    private static int CompareVisits(ZoneVisitFact left, ZoneVisitFact right)
    {
        var byEntry = left.EntryOffsetMs.CompareTo(right.EntryOffsetMs);
        if (byEntry != 0)
        {
            return byEntry;
        }

        var byZone = left.ZoneId.CompareTo(right.ZoneId);
        return byZone != 0 ? byZone : left.VisitIndex.CompareTo(right.VisitIndex);
    }

    private static int CompareCrossings(LineCrossingFact left, LineCrossingFact right)
    {
        var byOffset = left.OffsetMs.CompareTo(right.OffsetMs);
        if (byOffset != 0)
        {
            return byOffset;
        }

        var byLine = left.LineId.CompareTo(right.LineId);
        return byLine != 0 ? byLine : left.CrossingIndex.CompareTo(right.CrossingIndex);
    }

    private static MotionSummaryFact BuildMotion(
        TrajectoryPath path,
        IReadOnlyList<StationaryIntervalFact> intervals,
        IReadOnlyList<Guid> stationaryZones,
        SceneAnalyticsParameters parameters)
    {
        double pathLength = 0;
        foreach (var run in path.Runs)
        {
            // Only observed motion is measured. A straight line drawn across a gap
            // would be a guess, and would inflate the path length with it.
            for (var index = run.Start; index < run.End; index++)
            {
                pathLength += path[index].Position.DistanceTo(path[index + 1].Position);
            }
        }

        var observedMs = path.ObservedDurationMs;
        var rate = observedMs > 0 ? pathLength / (observedMs / 1000d) : 0;

        long longest = 0;
        long total = 0;
        foreach (var interval in intervals)
        {
            total += interval.DurationMs;
            longest = Math.Max(longest, interval.DurationMs);
        }

        var heading = path.Count >= 2
            ? TrajectoryPath.HeadingOf(
                path[0].Position,
                path[path.Count - 1].Position,
                parameters.HeadingMinimumDisplacement)
            : AnalysisHeading.None;

        return new MotionSummaryFact(
            heading,
            NormalizedPoint.Round(pathLength),
            NormalizedPoint.Round(rate),
            longest,
            total,
            intervals,
            stationaryZones);
    }
}
