using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Scene;

namespace Mavi.Application.Tests.SceneAnalytics;

public sealed class LineCrossingTests
{
    private static readonly SceneAnalyticsParameters Parameters = SceneAnalyticsParameters.Default;

    // Genuine crossings
    [Fact]
    public void PathThroughTheLineIsOneCrossing()
    {
        var crossings = Detect(SceneFixture.Line(9, 100, (0.5, 0.1), (0.5, 0.9)));

        var crossing = Assert.Single(crossings);
        Assert.Equal(0, crossing.CrossingIndex);

        // The line is drawn left to right, so its left-hand side is the top of the
        // frame; a Track moving downwards arrives on the right and crosses B to A.
        Assert.Equal(CrossingDirection.BToA, crossing.Direction);
    }

    [Fact]
    public void DirectionReversesWithTheDirectionOfTravel()
    {
        var down = Assert.Single(Detect(SceneFixture.Line(9, 100, (0.5, 0.1), (0.5, 0.9))));
        var up = Assert.Single(Detect(SceneFixture.Line(9, 100, (0.5, 0.9), (0.5, 0.1))));

        Assert.Equal(CrossingDirection.BToA, down.Direction);
        Assert.Equal(CrossingDirection.AToB, up.Direction);
    }

    [Fact]
    public void RedrawingTheLineTheOtherWayReversesEveryDirection()
    {
        var samples = SceneFixture.Line(9, 100, (0.5, 0.1), (0.5, 0.9));

        var forward = Assert.Single(Detect(samples));
        var reversed = Assert.Single(Detect(samples, SceneFixture.ReversedHorizontalLine()));

        Assert.Equal(CrossingDirection.BToA, forward.Direction);
        Assert.Equal(CrossingDirection.AToB, reversed.Direction);
        Assert.Equal(forward.OffsetMs, reversed.OffsetMs);
    }

    [Fact]
    public void CrossingTimeAndPointAreInterpolatedBetweenSamples()
    {
        // Two samples 200 ms apart, straddling y = 0.5 at exactly the midpoint.
        var crossing = Assert.Single(Detect(SceneFixture.Samples(
            (0, 0.5, 0.2),
            (200, 0.5, 0.3),
            (400, 0.5, 0.4),
            (600, 0.5, 0.6),
            (800, 0.5, 0.7),
            (1_000, 0.5, 0.8))));

        Assert.Equal(500, crossing.OffsetMs);
        Assert.Equal(0.5, crossing.Point.Y, 6);
        Assert.Equal(0.5, crossing.Point.X, 6);
    }

    [Fact]
    public void CrossingTimeNeverLeavesItsSamplePair()
    {
        var crossing = Assert.Single(Detect(SceneFixture.Samples(
            (0, 0.5, 0.1), (100, 0.5, 0.2), (200, 0.5, 0.3), (900, 0.5, 0.9), (1_000, 0.5, 0.95))));

        Assert.InRange(crossing.OffsetMs, 200, 900);
    }

    // Non-crossings
    [Fact]
    public void PathThatStopsShortOfTheLineDoesNotCross() =>
        Assert.Empty(Detect(SceneFixture.Line(9, 100, (0.5, 0.1), (0.5, 0.45))));

    [Fact]
    public void PathBeyondTheDrawnEndpointsDoesNotCross()
    {
        // The line spans x from 0.1 to 0.9; this path crosses y = 0.5 outside it.
        Assert.Empty(Detect(SceneFixture.Line(9, 100, (0.95, 0.1), (0.95, 0.9))));
    }

    [Fact]
    public void TangentApproachThatTurnsBackDoesNotCross()
    {
        var samples = SceneFixture.Concat(
            SceneFixture.Line(5, 100, (0.5, 0.2), (0.5, 0.48)),
            SceneFixture.Line(5, 100, (0.5, 0.48), (0.5, 0.2), startMs: 500));

        Assert.Empty(Detect(samples));
    }

    [Fact]
    public void MotionAlongTheLineIsNeverACrossing() =>
        Assert.Empty(Detect(SceneFixture.Line(9, 100, (0.15, 0.5), (0.85, 0.5))));

    [Fact]
    public void JitterInsideTheBandIsNotACrossing()
    {
        // Every sample stays within epsilon of the line, so no side is ever attained.
        var samples = SceneFixture.Samples(
            (0, 0.5, 0.5),
            (100, 0.5, 0.5015),
            (200, 0.5, 0.4988),
            (300, 0.5, 0.5012),
            (400, 0.5, 0.4991),
            (500, 0.5, 0.5008));

        Assert.Empty(Detect(samples));
    }

    [Fact]
    public void TouchingTheLineAndReturningIsNotACrossing()
    {
        var samples = SceneFixture.Samples(
            (0, 0.5, 0.3), (100, 0.5, 0.4), (200, 0.5, 0.5), (300, 0.5, 0.4), (400, 0.5, 0.3));

        Assert.Empty(Detect(samples));
    }

    [Fact]
    public void SideChangeAcrossALongGapIsNotInferred()
    {
        // The two halves are 5 seconds apart, beyond the bridging limit, so nothing
        // may be concluded about what happened in between.
        var samples = SceneFixture.Concat(
            SceneFixture.Line(4, 100, (0.5, 0.1), (0.5, 0.4)),
            SceneFixture.Line(4, 100, (0.5, 0.6), (0.5, 0.9), startMs: 5_300));

        Assert.Empty(Detect(samples));
    }

    // Debounce and repeat suppression
    [Fact]
    public void ExcursionWellBeyondTheBandIsTwoGenuineCrossings()
    {
        // Out to 0.53 and back to 0.47 is far outside the jitter band on both sides,
        // so it is a crossing and a return, not noise. The band, not the confirmation
        // window, is what separates jitter from movement.
        var samples = SceneFixture.Samples(
            (0, 0.5, 0.40),
            (100, 0.5, 0.45),
            (200, 0.5, 0.47),
            (300, 0.5, 0.53),
            (400, 0.5, 0.47),
            (500, 0.5, 0.45),
            (600, 0.5, 0.40));

        Assert.Equal(
            [CrossingDirection.BToA, CrossingDirection.AToB],
            Detect(samples).Select(crossing => crossing.Direction));
    }

    [Fact]
    public void ArrivingSideReachedTooLateAfterTheCrossingIsNotConfirmed()
    {
        // The Track slips into the band, loiters there well past the confirmation
        // window and only then emerges. There is no instant at which it can honestly
        // be said to have crossed.
        var samples = SceneFixture.Samples(
            (0, 0.5, 0.40),
            (100, 0.5, 0.5002),
            (200, 0.5, 0.4998),
            (300, 0.5, 0.5001),
            (400, 0.5, 0.4999),
            (500, 0.5, 0.5003),
            (600, 0.5, 0.60),
            (700, 0.5, 0.70));

        Assert.Empty(Detect(samples));
    }

    [Fact]
    public void TwoCrossingsTheSameWayWithinTheSuppressionWindowCollapse()
    {
        // Down, up and down again inside one second: the second downward crossing is
        // the same event seen twice.
        var samples = SceneFixture.Concat(
            SceneFixture.Line(4, 100, (0.5, 0.40), (0.5, 0.60)),
            SceneFixture.Line(4, 100, (0.5, 0.60), (0.5, 0.40), startMs: 400),
            SceneFixture.Line(4, 100, (0.5, 0.40), (0.5, 0.60), startMs: 800));

        var directions = Detect(samples).Select(crossing => crossing.Direction).ToArray();

        Assert.Equal([CrossingDirection.BToA, CrossingDirection.AToB], directions);
    }

    [Fact]
    public void TwoCrossingsTheSameWayBeyondTheSuppressionWindowAreBothKept()
    {
        var samples = SceneFixture.Concat(
            SceneFixture.Line(4, 100, (0.5, 0.40), (0.5, 0.60)),
            SceneFixture.Line(4, 100, (0.5, 0.60), (0.5, 0.40), startMs: 400),
            SceneFixture.Line(4, 500, (0.5, 0.40), (0.5, 0.60), startMs: 2_000));

        var crossings = Detect(samples);

        Assert.Equal(3, crossings.Count);
        Assert.Equal([0, 1, 2], crossings.Select(crossing => crossing.CrossingIndex));
        Assert.Equal(
            [CrossingDirection.BToA, CrossingDirection.AToB, CrossingDirection.BToA],
            crossings.Select(crossing => crossing.Direction));
    }

    [Fact]
    public void OppositeDirectionsAreNeverSuppressed()
    {
        var samples = SceneFixture.Concat(
            SceneFixture.Line(4, 50, (0.5, 0.40), (0.5, 0.60)),
            SceneFixture.Line(4, 50, (0.5, 0.60), (0.5, 0.40), startMs: 200));

        Assert.Equal(2, Detect(samples).Count);
    }

    // Helpers
    private static IReadOnlyList<LineCrossingFact> Detect(
        IReadOnlyList<TrajectorySample> samples,
        TripLineDraft? line = null)
    {
        var revision = SceneFixture.Revision(lines: [line ?? SceneFixture.HorizontalLine()]);
        var path = TrajectoryPath.Create(samples, Parameters);
        return LineCrossingDetector.Detect(path, revision.TripLines[0], Parameters);
    }
}
