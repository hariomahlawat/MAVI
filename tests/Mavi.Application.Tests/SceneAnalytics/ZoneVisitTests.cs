using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Scene;

namespace Mavi.Application.Tests.SceneAnalytics;

public sealed class ZoneVisitTests
{
    private static readonly SceneAnalyticsParameters Parameters = SceneAnalyticsParameters.Default;

    // The zone spans 0.3 to 0.7 on both axes.
    [Fact]
    public void PathStraightThroughIsOneVisit()
    {
        var visits = Detect(SceneFixture.Line(21, 100, (0.5, 0.05), (0.5, 0.95)));

        var visit = Assert.Single(visits);
        Assert.Equal(0, visit.VisitIndex);
        Assert.False(visit.BeganInside);
        Assert.False(visit.EndedInside);
        Assert.False(visit.ClosedByGap);
        Assert.True(visit.DwellMs > 0);
    }

    [Fact]
    public void EntryAndExitInstantsAreInterpolatedOnTheBoundary()
    {
        // Moving down the middle at 0.05 per 100 ms, the boundary at y = 0.3 falls
        // between the samples at 0.25 and 0.35.
        var visit = Assert.Single(Detect(SceneFixture.Line(19, 100, (0.5, 0.05), (0.5, 0.95))));

        Assert.Equal(500, visit.EntryOffsetMs);
        Assert.Equal(1_300, visit.ExitOffsetMs);
        Assert.Equal(800, visit.DwellMs);
    }

    [Fact]
    public void PathStartingInsideBeginsInside()
    {
        var visit = Assert.Single(Detect(SceneFixture.Line(15, 100, (0.5, 0.5), (0.5, 0.95))));

        Assert.True(visit.BeganInside);
        Assert.Equal(0, visit.EntryOffsetMs);
        Assert.Equal(AnalysisHeading.None, visit.EntryHeading);
    }

    [Fact]
    public void PathEndingInsideEndsInside()
    {
        var samples = SceneFixture.Line(11, 100, (0.5, 0.05), (0.5, 0.55));
        var visit = Assert.Single(Detect(samples));

        Assert.True(visit.EndedInside);
        Assert.False(visit.ClosedByGap);
        Assert.Equal(1_000, visit.ExitOffsetMs);
    }

    [Fact]
    public void PathEntirelyOutsideProducesNoVisit() =>
        Assert.Empty(Detect(SceneFixture.Line(11, 100, (0.05, 0.05), (0.2, 0.2))));

    [Fact]
    public void ReEntryOpensANewVisitWithTheNextIndex()
    {
        var samples = SceneFixture.Concat(
            SceneFixture.Line(11, 100, (0.5, 0.05), (0.5, 0.55)),
            SceneFixture.Line(11, 100, (0.5, 0.55), (0.5, 0.05), startMs: 1_100),
            SceneFixture.Line(11, 100, (0.5, 0.05), (0.5, 0.55), startMs: 2_200));

        var visits = Detect(samples);

        Assert.Equal(2, visits.Count);
        Assert.Equal([0, 1], visits.Select(visit => visit.VisitIndex));
        Assert.True(visits[1].EndedInside);
    }

    [Fact]
    public void BriefExcursionDoesNotCloseTheVisit()
    {
        // Two samples just outside the zone, fewer than the confirmation window, then
        // back in. That is one stay, not three.
        var samples = SceneFixture.Samples(
            (0, 0.5, 0.40),
            (100, 0.5, 0.50),
            (200, 0.5, 0.60),
            (300, 0.5, 0.72),
            (400, 0.5, 0.73),
            (500, 0.5, 0.60),
            (600, 0.5, 0.50),
            (700, 0.5, 0.40));

        var visit = Assert.Single(Detect(samples));

        Assert.True(visit.EndedInside);
    }

    [Fact]
    public void HuggingTheBoundaryFromOutsideKeepsTheVisitOpen()
    {
        // Every sample outside sits within epsilon of the edge, so the exit is never
        // confirmed however long it lasts.
        var samples = SceneFixture.Samples(
            (0, 0.5, 0.50),
            (100, 0.5, 0.60),
            (200, 0.5, 0.7002),
            (300, 0.5, 0.7003),
            (400, 0.5, 0.7001),
            (500, 0.5, 0.7004),
            (600, 0.5, 0.60));

        var visit = Assert.Single(Detect(samples));

        Assert.True(visit.EndedInside);
        Assert.True(visit.BeganInside);
    }

    [Fact]
    public void TouchingTheBoundaryFromInsideCountsAsInside()
    {
        var visits = Detect(SceneFixture.Samples(
            (0, 0.5, 0.20), (100, 0.5, 0.30), (200, 0.5, 0.20), (300, 0.5, 0.10), (400, 0.5, 0.05)));

        Assert.Single(visits);
    }

    // Gaps
    [Fact]
    public void GapWithinTheBridgingLimitDoesNotSplitAVisit()
    {
        var samples = SceneFixture.Concat(
            SceneFixture.Line(6, 100, (0.5, 0.05), (0.5, 0.55)),
            SceneFixture.Line(6, 100, (0.5, 0.55), (0.5, 0.60), startMs: 2_400));

        var visit = Assert.Single(Detect(samples));

        Assert.True(visit.EndedInside);
        Assert.False(visit.ClosedByGap);
    }

    [Fact]
    public void GapBeyondTheBridgingLimitClosesTheVisit()
    {
        var samples = SceneFixture.Concat(
            SceneFixture.Line(6, 100, (0.5, 0.05), (0.5, 0.55)),
            SceneFixture.Line(6, 100, (0.5, 0.55), (0.5, 0.60), startMs: 6_000));

        var visits = Detect(samples);

        Assert.Equal(2, visits.Count);
        Assert.True(visits[0].ClosedByGap);
        Assert.False(visits[0].EndedInside);
        Assert.Equal(500, visits[0].ExitOffsetMs);

        // Analysis resumes after the gap as though the Track began there.
        Assert.True(visits[1].BeganInside);
        Assert.True(visits[1].EndedInside);
        Assert.Equal(6_000, visits[1].EntryOffsetMs);
    }

    [Fact]
    public void GapCountAndDurationAreRecorded()
    {
        var samples = SceneFixture.Concat(
            SceneFixture.Line(3, 100, (0.5, 0.05), (0.5, 0.15)),
            SceneFixture.Line(3, 100, (0.5, 0.45), (0.5, 0.55), startMs: 6_000));

        var path = TrajectoryPath.Create(samples, Parameters);

        Assert.Equal(1, path.GapCount);
        Assert.Equal(5_800, path.GapTotalMs);
        Assert.Equal(2, path.Runs.Count);
    }

    // Headings
    [Fact]
    public void EntryHeadingIsTheDirectionOfTravelIntoTheZone()
    {
        var visit = Assert.Single(Detect(SceneFixture.Line(21, 100, (0.5, 0.05), (0.5, 0.95))));

        Assert.Equal(AnalysisHeading.South, visit.EntryHeading);
    }

    [Fact]
    public void HeadingIsNoneWhenTheTrackBarelyMoves() =>
        Assert.Equal(
            AnalysisHeading.None,
            TrajectoryPath.HeadingOf(
                Mavi.Domain.Scene.Geometry.NormalizedPoint.FromRounded(0.5, 0.5),
                Mavi.Domain.Scene.Geometry.NormalizedPoint.FromRounded(0.505, 0.5),
                Parameters.HeadingMinimumDisplacement));

    [Theory]
    [InlineData(0.5, 0.1, AnalysisHeading.North)]
    [InlineData(0.9, 0.5, AnalysisHeading.East)]
    [InlineData(0.5, 0.9, AnalysisHeading.South)]
    [InlineData(0.1, 0.5, AnalysisHeading.West)]
    [InlineData(0.9, 0.1, AnalysisHeading.NorthEast)]
    [InlineData(0.9, 0.9, AnalysisHeading.SouthEast)]
    [InlineData(0.1, 0.9, AnalysisHeading.SouthWest)]
    [InlineData(0.1, 0.1, AnalysisHeading.NorthWest)]
    public void EightWayHeadingsUseScreenAxes(double x, double y, string expected) =>
        Assert.Equal(
            expected,
            TrajectoryPath.HeadingOf(
                Mavi.Domain.Scene.Geometry.NormalizedPoint.FromRounded(0.5, 0.5),
                Mavi.Domain.Scene.Geometry.NormalizedPoint.FromRounded(x, y),
                Parameters.HeadingMinimumDisplacement));

    // Helpers
    private static IReadOnlyList<ZoneVisitFact> Detect(
        IReadOnlyList<TrajectorySample> samples,
        SceneZoneDraft? zone = null)
    {
        var revision = SceneFixture.Revision(zones: [zone ?? SceneFixture.CentreZone()]);
        var path = TrajectoryPath.Create(samples, Parameters);
        return ZoneVisitDetector.Detect(path, revision.Zones[0], Parameters);
    }
}
