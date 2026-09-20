using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// A decoded trajectory prepared for analysis: its samples, and the runs of samples
/// between which no gap is long enough to forbid reasoning.
/// </summary>
/// <remarks>
/// Nothing is inferred across a gap longer than
/// <see cref="SceneAnalyticsParameters.MaximumGapMs"/>. Splitting the path once, here,
/// keeps that rule in a single place instead of in every detector.
/// </remarks>
public sealed class TrajectoryPath
{
    private TrajectoryPath(
        IReadOnlyList<TrajectorySample> samples,
        IReadOnlyList<SampleRun> runs,
        int gapCount,
        long gapTotalMs)
    {
        Samples = samples;
        Runs = runs;
        GapCount = gapCount;
        GapTotalMs = gapTotalMs;
    }

    /// <summary>A half-open-free inclusive index range of samples with no long gap inside it.</summary>
    public readonly record struct SampleRun(int Start, int End)
    {
        public int Length => End - Start + 1;
    }

    public IReadOnlyList<TrajectorySample> Samples { get; }

    public IReadOnlyList<SampleRun> Runs { get; }

    /// <summary>How many gaps exceeded the bridging limit.</summary>
    public int GapCount { get; }

    /// <summary>Total duration of those gaps.</summary>
    public long GapTotalMs { get; }

    public TrajectorySample this[int index] => Samples[index];

    public int Count => Samples.Count;

    public static TrajectoryPath Create(IReadOnlyList<TrajectorySample> samples, SceneAnalyticsParameters parameters)
    {
        ArgumentNullException.ThrowIfNull(samples);
        ArgumentNullException.ThrowIfNull(parameters);

        var runs = new List<SampleRun>();
        var gapCount = 0;
        long gapTotalMs = 0;
        var runStart = 0;

        for (var index = 1; index < samples.Count; index++)
        {
            var gap = samples[index].OffsetMs - samples[index - 1].OffsetMs;
            if (gap <= parameters.MaximumGapMs)
            {
                continue;
            }

            gapCount++;
            gapTotalMs += gap;
            runs.Add(new SampleRun(runStart, index - 1));
            runStart = index;
        }

        if (samples.Count > 0)
        {
            runs.Add(new SampleRun(runStart, samples.Count - 1));
        }

        return new TrajectoryPath(samples, runs, gapCount, gapTotalMs);
    }

    /// <summary>The total duration actually observed, excluding the bridged-out gaps.</summary>
    public long ObservedDurationMs
    {
        get
        {
            long total = 0;
            foreach (var run in Runs)
            {
                total += Samples[run.End].OffsetMs - Samples[run.Start].OffsetMs;
            }

            return total;
        }
    }

    /// <summary>
    /// The position at a media offset, linearly interpolated between the two
    /// surrounding samples. Null outside the sampled range or inside a long gap,
    /// because there is no evidence of position there.
    /// </summary>
    public NormalizedPoint? PositionAt(long offsetMs)
    {
        foreach (var run in Runs)
        {
            if (offsetMs < Samples[run.Start].OffsetMs || offsetMs > Samples[run.End].OffsetMs)
            {
                continue;
            }

            for (var index = run.Start; index < run.End; index++)
            {
                var before = Samples[index];
                var after = Samples[index + 1];
                if (offsetMs < before.OffsetMs || offsetMs > after.OffsetMs)
                {
                    continue;
                }

                var span = after.OffsetMs - before.OffsetMs;
                var t = span == 0 ? 0 : (double)(offsetMs - before.OffsetMs) / span;
                return before.Position.Lerp(after.Position, t);
            }

            return Samples[run.End].Position;
        }

        return null;
    }

    /// <summary>
    /// The media offset at parameter <paramref name="t"/> along the segment that starts
    /// at <paramref name="index"/>, rounded to the nearest whole millisecond.
    /// </summary>
    /// <remarks>
    /// Offsets are integers on the wire, so the interpolated instant is reported at
    /// the same resolution rather than inventing sub-millisecond precision. The result
    /// is always inside the two sample offsets: the engine never extrapolates.
    /// </remarks>
    public long InterpolateOffset(int index, double t)
    {
        var before = Samples[index].OffsetMs;
        var after = Samples[index + 1].OffsetMs;
        var clamped = Math.Clamp(t, 0, 1);
        var offset = before + (long)Math.Round((after - before) * clamped, MidpointRounding.AwayFromZero);
        return Math.Clamp(offset, before, after);
    }

    /// <summary>The eight-way image heading of a displacement, or none when it is too small.</summary>
    public static string HeadingOf(NormalizedPoint from, NormalizedPoint to, double minimumDisplacement)
    {
        var dx = to.X - from.X;
        var dy = to.Y - from.Y;
        if (Math.Sqrt((dx * dx) + (dy * dy)) < minimumDisplacement)
        {
            return AnalysisHeading.None;
        }

        // Screen axes: y grows downwards, so north is negative dy. Atan2 is taken on
        // (dx, -dy) to put north at zero and run the sectors clockwise on screen.
        var degrees = Math.Atan2(dx, -dy) * 180 / Math.PI;
        if (degrees < 0)
        {
            degrees += 360;
        }

        var sector = (int)Math.Floor((degrees + 22.5) / 45) % 8;
        return sector switch
        {
            0 => AnalysisHeading.North,
            1 => AnalysisHeading.NorthEast,
            2 => AnalysisHeading.East,
            3 => AnalysisHeading.SouthEast,
            4 => AnalysisHeading.South,
            5 => AnalysisHeading.SouthWest,
            6 => AnalysisHeading.West,
            _ => AnalysisHeading.NorthWest,
        };
    }
}
