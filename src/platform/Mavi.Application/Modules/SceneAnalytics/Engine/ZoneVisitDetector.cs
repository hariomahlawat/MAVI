using Mavi.Domain.Scene;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// Derives a Track's stays inside one zone, following the frozen entry and exit
/// rules of plan section K.
/// </summary>
/// <remarks>
/// A visit opens at the first sample inside the zone. It closes only once the Track
/// is clear of the boundary by at least the jitter tolerance for the whole
/// confirmation window, so a brief excursion or a tracker wobble on the edge does
/// not split one stay into several.
/// </remarks>
public static class ZoneVisitDetector
{
    public static IReadOnlyList<ZoneVisitFact> Detect(
        TrajectoryPath path,
        SceneZone zone,
        SceneAnalyticsParameters parameters)
    {
        ArgumentNullException.ThrowIfNull(path);
        ArgumentNullException.ThrowIfNull(zone);
        ArgumentNullException.ThrowIfNull(parameters);

        var vertices = zone.Vertices;
        var count = path.Count;
        var inside = new bool[count];
        var clearlyOutside = new bool[count];
        for (var index = 0; index < count; index++)
        {
            var position = path[index].Position;
            inside[index] = SceneGeometry.Contains(vertices, position);
            clearlyOutside[index] = !inside[index] &&
                DistanceToBoundary(vertices, position) >= parameters.Epsilon;
        }

        var visits = new List<ZoneVisitFact>();
        var visitIndex = 0;

        foreach (var run in path.Runs)
        {
            var open = false;
            var entryIndex = 0;
            long entryOffset = 0;
            var beganInside = false;
            var entryHeading = AnalysisHeading.None;
            var pendingOutside = 0;
            var candidateExitIndex = 0;

            for (var index = run.Start; index <= run.End; index++)
            {
                if (!open)
                {
                    if (!inside[index])
                    {
                        continue;
                    }

                    open = true;
                    entryIndex = index;
                    pendingOutside = 0;

                    // A visit that is already under way when the run begins has no
                    // observed boundary crossing, so the sample's own offset is used.
                    beganInside = index == run.Start;
                    entryOffset = beganInside
                        ? path[index].OffsetMs
                        : EntryOffset(path, vertices, index);
                    entryHeading = beganInside
                        ? AnalysisHeading.None
                        : TrajectoryPath.HeadingOf(
                            path[index - 1].Position,
                            path[index].Position,
                            parameters.HeadingMinimumDisplacement);
                    continue;
                }

                if (!clearlyOutside[index])
                {
                    // Inside, or outside but still hugging the boundary: the stay continues.
                    pendingOutside = 0;
                    continue;
                }

                if (pendingOutside == 0)
                {
                    candidateExitIndex = index;
                }

                pendingOutside++;
                if (pendingOutside < parameters.ConfirmationSamples)
                {
                    continue;
                }

                var exitOffset = ExitOffset(path, vertices, entryIndex, candidateExitIndex);
                visits.Add(Build(
                    zone.ZoneId,
                    visitIndex++,
                    entryOffset,
                    exitOffset,
                    beganInside,
                    endedInside: false,
                    closedByGap: false,
                    entryHeading,
                    TrajectoryPath.HeadingOf(
                        path[candidateExitIndex - 1].Position,
                        path[candidateExitIndex].Position,
                        parameters.HeadingMinimumDisplacement)));
                open = false;
                pendingOutside = 0;
            }

            if (!open)
            {
                continue;
            }

            // The run ended with the Track still inside. Whether that is the end of the
            // Track or the start of a gap decides which flag the visit carries.
            var isFinalRun = run.End == count - 1;
            visits.Add(Build(
                zone.ZoneId,
                visitIndex++,
                entryOffset,
                path[run.End].OffsetMs,
                beganInside,
                endedInside: isFinalRun,
                closedByGap: !isFinalRun,
                entryHeading,
                AnalysisHeading.None));
        }

        return visits;
    }

    private static ZoneVisitFact Build(
        Guid zoneId,
        int visitIndex,
        long entryOffsetMs,
        long exitOffsetMs,
        bool beganInside,
        bool endedInside,
        bool closedByGap,
        string entryHeading,
        string exitHeading)
    {
        var exit = Math.Max(entryOffsetMs, exitOffsetMs);
        return new ZoneVisitFact(
            zoneId,
            visitIndex,
            entryOffsetMs,
            exit,
            exit - entryOffsetMs,
            beganInside,
            endedInside,
            closedByGap,
            entryHeading,
            exitHeading);
    }

    /// <summary>Distance from a point to the nearest edge of the polygon.</summary>
    private static double DistanceToBoundary(IReadOnlyList<NormalizedPoint> vertices, NormalizedPoint point)
    {
        var nearest = double.MaxValue;
        for (var index = 0; index < vertices.Count; index++)
        {
            var distance = SceneGeometry.DistanceToSegment(
                point,
                vertices[index],
                vertices[(index + 1) % vertices.Count]);
            if (distance < nearest)
            {
                nearest = distance;
            }
        }

        return nearest;
    }

    /// <summary>The instant the path first crossed into the zone on the entering segment.</summary>
    private static long EntryOffset(TrajectoryPath path, IReadOnlyList<NormalizedPoint> vertices, int index)
    {
        var t = FirstBoundaryParameter(path[index - 1].Position, path[index].Position, vertices, wantFirst: true);
        return t is { } parameter ? path.InterpolateOffset(index - 1, parameter) : path[index].OffsetMs;
    }

    /// <summary>
    /// The instant the path last left the zone, searching back from the sample that
    /// confirmed the exit to the segment that actually crossed the boundary.
    /// </summary>
    private static long ExitOffset(
        TrajectoryPath path,
        IReadOnlyList<NormalizedPoint> vertices,
        int entryIndex,
        int candidateExitIndex)
    {
        for (var index = candidateExitIndex; index > entryIndex; index--)
        {
            var t = FirstBoundaryParameter(path[index - 1].Position, path[index].Position, vertices, wantFirst: false);
            if (t is { } parameter)
            {
                return path.InterpolateOffset(index - 1, parameter);
            }
        }

        return path[candidateExitIndex].OffsetMs;
    }

    /// <summary>
    /// The first or last parameter in [0, 1] at which the segment meets the polygon
    /// boundary, or null when it does not meet it at all.
    /// </summary>
    private static double? FirstBoundaryParameter(
        NormalizedPoint from,
        NormalizedPoint to,
        IReadOnlyList<NormalizedPoint> vertices,
        bool wantFirst)
    {
        double? chosen = null;
        for (var index = 0; index < vertices.Count; index++)
        {
            var a = vertices[index];
            var b = vertices[(index + 1) % vertices.Count];
            if (!SceneGeometry.SegmentsIntersect(from, to, a, b))
            {
                continue;
            }

            var t = SceneGeometry.LineIntersectionParameter(from, to, a, b);
            if (t is not { } parameter || parameter < 0 || parameter > 1)
            {
                continue;
            }

            if (chosen is null ||
                (wantFirst && parameter < chosen) ||
                (!wantFirst && parameter > chosen))
            {
                chosen = parameter;
            }
        }

        return chosen;
    }
}
