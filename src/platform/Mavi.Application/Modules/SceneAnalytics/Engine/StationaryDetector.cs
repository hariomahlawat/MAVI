using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// Finds the spans in which a Track's reference point stopped moving, following the
/// frozen rules of plan section L.
/// </summary>
/// <remarks>
/// <para>
/// A stationary person and a stopped vehicle are the same computation with
/// different thresholds; the class only chooses which pair applies.
/// </para>
/// <para>
/// Everything here is measured in normalised image units. A fixed threshold means a
/// larger real distance further from the camera, so no result may be described as a
/// physical speed or distance.
/// </para>
/// </remarks>
public static class StationaryDetector
{
    public static IReadOnlyList<StationaryIntervalFact> Detect(
        TrajectoryPath path,
        ObjectClass objectClass,
        SceneAnalyticsParameters parameters)
    {
        ArgumentNullException.ThrowIfNull(path);
        ArgumentNullException.ThrowIfNull(parameters);

        var (displacementLimit, minimumMs) = parameters.StationaryThresholdsFor(objectClass);
        var smoothed = Smooth(path, parameters.SmoothingWindowSamples);
        var intervals = new List<StationaryIntervalFact>();

        foreach (var run in path.Runs)
        {
            var candidateStart = -1;
            for (var index = run.Start; index <= run.End; index++)
            {
                if (IsCandidate(path, smoothed, run, index, displacementLimit, parameters.StationaryWindowMs))
                {
                    if (candidateStart < 0)
                    {
                        candidateStart = index;
                    }

                    continue;
                }

                AddIfLongEnough(path, intervals, candidateStart, index - 1, minimumMs);
                candidateStart = -1;
            }

            AddIfLongEnough(path, intervals, candidateStart, run.End, minimumMs);
        }

        return intervals;
    }

    /// <summary>The zones whose polygon contains the midpoint of each interval.</summary>
    public static IReadOnlyList<Guid> ZonesContaining(
        TrajectoryPath path,
        IReadOnlyList<StationaryIntervalFact> intervals,
        IReadOnlyList<(Guid ZoneId, IReadOnlyList<NormalizedPoint> Vertices)> zones)
    {
        ArgumentNullException.ThrowIfNull(path);
        ArgumentNullException.ThrowIfNull(intervals);
        ArgumentNullException.ThrowIfNull(zones);

        var found = new HashSet<Guid>();
        foreach (var interval in intervals)
        {
            var midpoint = path.PositionAt(interval.StartOffsetMs + ((interval.EndOffsetMs - interval.StartOffsetMs) / 2));
            if (midpoint is not { } position)
            {
                continue;
            }

            foreach (var (zoneId, vertices) in zones)
            {
                if (SceneGeometry.Contains(vertices, position))
                {
                    found.Add(zoneId);
                }
            }
        }

        return [.. found.Order()];
    }

    /// <summary>
    /// A centred moving median of width <paramref name="window"/>, taken on each
    /// coordinate independently so that a single mis-placed sample cannot drag the
    /// path the way a mean would.
    /// </summary>
    /// <remarks>
    /// The window never reaches across a long gap: each observed run is smoothed on
    /// its own. Drawing a value from the far side of a gap would put a position the
    /// engine is forbidden to infer into the evidence for an interval, and could
    /// back-date a stop by up to half a window.
    /// </remarks>
    internal static NormalizedPoint[] Smooth(TrajectoryPath path, int window)
    {
        var result = new NormalizedPoint[path.Count];
        var half = Math.Max(0, window / 2);
        var xs = new List<double>(window);
        var ys = new List<double>(window);

        foreach (var run in path.Runs)
        {
            for (var index = run.Start; index <= run.End; index++)
            {
                xs.Clear();
                ys.Clear();

                // Edges of a run use only the samples that exist inside it, rather
                // than padding with invented ones or borrowing across the gap.
                var from = Math.Max(run.Start, index - half);
                var to = Math.Min(run.End, index + half);
                for (var inner = from; inner <= to; inner++)
                {
                    xs.Add(path[inner].Position.X);
                    ys.Add(path[inner].Position.Y);
                }

                result[index] = NormalizedPoint.FromRounded(Median(xs), Median(ys));
            }
        }

        return result;
    }

    private static double Median(List<double> values)
    {
        values.Sort();
        var middle = values.Count / 2;
        return values.Count % 2 == 1
            ? values[middle]
            : (values[middle - 1] + values[middle]) / 2;
    }

    /// <summary>
    /// True when the smoothed point has stayed within the displacement limit across
    /// the trailing window.
    /// </summary>
    /// <remarks>
    /// Near the start of a run the window uses only the samples that exist, the same
    /// way the smoothing filter treats its edges. The opening samples of a moving
    /// Track therefore qualify briefly, which costs nothing: such a run is far shorter
    /// than the minimum duration and is discarded. Requiring a fully covered window
    /// instead would make every interval start a window late, so a Track that stood
    /// still from its first sample would be reported as arriving three seconds after
    /// it did.
    /// </remarks>
    private static bool IsCandidate(
        TrajectoryPath path,
        NormalizedPoint[] smoothed,
        TrajectoryPath.SampleRun run,
        int index,
        double displacementLimit,
        long windowMs)
    {
        var current = path[index].OffsetMs;
        for (var inner = index; inner >= run.Start; inner--)
        {
            if (current - path[inner].OffsetMs > windowMs)
            {
                break;
            }

            if (smoothed[index].DistanceTo(smoothed[inner]) >= displacementLimit)
            {
                return false;
            }
        }

        return true;
    }

    private static void AddIfLongEnough(
        TrajectoryPath path,
        List<StationaryIntervalFact> intervals,
        int start,
        int end,
        long minimumMs)
    {
        if (start < 0 || end < start)
        {
            return;
        }

        var startOffset = path[start].OffsetMs;
        var endOffset = path[end].OffsetMs;
        if (endOffset - startOffset >= minimumMs)
        {
            intervals.Add(new StationaryIntervalFact(startOffset, endOffset));
        }
    }
}
