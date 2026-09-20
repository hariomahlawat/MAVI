using Mavi.Domain.Scene;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// Derives confirmed crossings of one trip line, following the frozen rules of
/// plan section K.
/// </summary>
/// <remarks>
/// <para>
/// Each sample is assigned a side of the line, with an on-line band of width
/// <see cref="SceneAnalyticsParameters.Epsilon"/> counting as neither side. A
/// crossing is a change between two genuinely non-zero sides, so a Track that
/// merely wobbles inside the band never produces one, and a Track that runs along
/// the line never leaves the band at all.
/// </para>
/// <para>
/// <b>Direction convention.</b> The cross product of the line's direction with the
/// vector to a point is positive on one fixed side; arriving on that side is
/// <see cref="CrossingDirection.AToB"/>. In screen axes, with y growing downwards,
/// that is the side visually below a left-to-right line: a Track moving down
/// through a horizontal line drawn from left to right crosses A to B. Swapping the
/// endpoints reverses every direction, which is exactly what an operator expects
/// when they redraw the line the other way.
/// </para>
/// </remarks>
public static class LineCrossingDetector
{
    public static IReadOnlyList<LineCrossingFact> Detect(
        TrajectoryPath path,
        TripLine line,
        SceneAnalyticsParameters parameters)
    {
        ArgumentNullException.ThrowIfNull(path);
        ArgumentNullException.ThrowIfNull(line);
        ArgumentNullException.ThrowIfNull(parameters);

        var a = line.A;
        var b = line.B;
        var length = a.DistanceTo(b);
        if (length <= 0)
        {
            return [];
        }

        var band = parameters.Epsilon * length;
        var sides = new int[path.Count];
        for (var index = 0; index < path.Count; index++)
        {
            var value = SceneGeometry.Cross(a, b, path[index].Position);
            sides[index] = Math.Abs(value) < band ? 0 : Math.Sign(value);
        }

        var crossings = new List<LineCrossingFact>();
        long lastAToB = long.MinValue;
        long lastBToA = long.MinValue;
        var crossingIndex = 0;

        foreach (var run in path.Runs)
        {
            var lastNonZero = 0;
            var lastNonZeroIndex = -1;

            for (var index = run.Start; index <= run.End; index++)
            {
                if (sides[index] == 0)
                {
                    continue;
                }

                if (lastNonZeroIndex >= 0 && sides[index] != lastNonZero)
                {
                    var crossing = Resolve(
                        path,
                        line,
                        parameters,
                        sides,
                        lastNonZeroIndex,
                        index,
                        run);
                    if (crossing is { } found)
                    {
                        var previous = found.Direction == CrossingDirection.AToB ? lastAToB : lastBToA;

                        // Two crossings the same way inside the suppression window are one
                        // event seen twice; the opposite way is always a new event.
                        if (previous == long.MinValue ||
                            found.OffsetMs - previous >= parameters.RepeatSuppressionMs)
                        {
                            crossings.Add(found with { CrossingIndex = crossingIndex++ });
                            if (found.Direction == CrossingDirection.AToB)
                            {
                                lastAToB = found.OffsetMs;
                            }
                            else
                            {
                                lastBToA = found.OffsetMs;
                            }
                        }
                    }
                }

                lastNonZero = sides[index];
                lastNonZeroIndex = index;
            }
        }

        return crossings;
    }

    private static LineCrossingFact? Resolve(
        TrajectoryPath path,
        TripLine line,
        SceneAnalyticsParameters parameters,
        int[] sides,
        int departingIndex,
        int arrivingIndex,
        TrajectoryPath.SampleRun run)
    {
        // The path must actually meet the line segment somewhere in the span. A side
        // change that happens beyond the drawn endpoints is a pass-by, not a crossing.
        for (var index = departingIndex; index < arrivingIndex; index++)
        {
            var from = path[index].Position;
            var to = path[index + 1].Position;
            if (!SceneGeometry.SegmentsIntersect(from, to, line.A, line.B))
            {
                continue;
            }

            var t = SceneGeometry.LineIntersectionParameter(from, to, line.A, line.B);
            if (t is not { } parameter || parameter < 0 || parameter > 1)
            {
                continue;
            }

            var departing = sides[departingIndex];
            var arriving = sides[arrivingIndex];
            if (!IsConfirmed(sides, departingIndex, arrivingIndex, departing, arriving, parameters, run))
            {
                return null;
            }

            return new LineCrossingFact(
                line.LineId,
                CrossingIndex: 0,
                path.InterpolateOffset(index, parameter),
                arriving > 0 ? CrossingDirection.AToB : CrossingDirection.BToA,
                from.Lerp(to, parameter));
        }

        return null;
    }

    /// <summary>
    /// True when the Track held the departing side within the confirmation window
    /// before the crossing and reaches the arriving side within it afterwards.
    /// </summary>
    /// <remarks>
    /// Near the start or the end of a run there are fewer samples to look at, and the
    /// rule uses whatever is available rather than refusing the crossing.
    /// </remarks>
    private static bool IsConfirmed(
        int[] sides,
        int departingIndex,
        int arrivingIndex,
        int departing,
        int arriving,
        SceneAnalyticsParameters parameters,
        TrajectoryPath.SampleRun run)
    {
        var window = parameters.ConfirmationSamples;

        var departingConfirmed = false;
        var from = Math.Max(run.Start, departingIndex - window + 1);
        for (var index = from; index <= departingIndex; index++)
        {
            if (sides[index] == departing)
            {
                departingConfirmed = true;
                break;
            }
        }

        var arrivingConfirmed = false;
        var to = Math.Min(run.End, arrivingIndex + window - 1);
        for (var index = arrivingIndex; index <= to; index++)
        {
            if (sides[index] == arriving)
            {
                arrivingConfirmed = true;
                break;
            }
        }

        return departingConfirmed && arrivingConfirmed;
    }
}
