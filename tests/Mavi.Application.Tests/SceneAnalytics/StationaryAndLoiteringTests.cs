using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;

namespace Mavi.Application.Tests.SceneAnalytics;

public sealed class StationaryAndLoiteringTests
{
    private static readonly SceneAnalyticsParameters Parameters = SceneAnalyticsParameters.Default;

    // Stationary persons
    [Fact]
    public void PersonHoldingStillLongEnoughYieldsAnInterval()
    {
        // Eight seconds in one place, past the five-second minimum for a person.
        var samples = SceneFixture.Held(41, 200, (0.5, 0.5));

        var interval = Assert.Single(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));

        Assert.Equal(8_000, interval.EndOffsetMs);
        Assert.True(interval.DurationMs >= Parameters.PersonStationaryMinimumMs);
    }

    [Fact]
    public void PersonStillForLessThanTheMinimumYieldsNothing()
    {
        var samples = SceneFixture.Held(16, 200, (0.5, 0.5));

        Assert.Empty(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));
    }

    [Fact]
    public void WalkingPersonIsNeverStationary()
    {
        var samples = SceneFixture.Line(51, 200, (0.1, 0.5), (0.9, 0.5));

        Assert.Empty(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));
    }

    [Fact]
    public void TrackShorterThanTheMinimumCanNeverBeStationary()
    {
        var samples = SceneFixture.Held(6, 200, (0.5, 0.5));

        Assert.Empty(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));
    }

    // Vehicles
    [Fact]
    public void VehicleNeedsLongerThanAPersonToCountAsStopped()
    {
        // Seven seconds: enough for a person, short of the ten a vehicle needs.
        var samples = SceneFixture.Held(36, 200, (0.5, 0.5));

        Assert.Single(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));
        Assert.Empty(StationaryDetector.Detect(Path(samples), ObjectClass.Vehicle, Parameters));
    }

    [Fact]
    public void VehicleStoppedLongEnoughYieldsAnInterval()
    {
        var samples = SceneFixture.Held(61, 200, (0.5, 0.5));

        Assert.Single(StationaryDetector.Detect(Path(samples), ObjectClass.Vehicle, Parameters));
    }

    [Fact]
    public void VehicleToleratesLessDriftThanAPerson()
    {
        // A steady wobble of about 0.012, inside a person's tolerance and outside a
        // vehicle's.
        var samples = Wobble(61, 200, (0.5, 0.5), 0.012);

        Assert.NotEmpty(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));
        Assert.Empty(StationaryDetector.Detect(Path(samples), ObjectClass.Vehicle, Parameters));
    }

    // Smoothing
    [Fact]
    public void SingleSampleJumpIsSmoothedAway()
    {
        var samples = SceneFixture.Held(41, 200, (0.5, 0.5)).ToList();
        samples[20] = new TrajectorySample(
            samples[20].OffsetMs,
            Mavi.Domain.Scene.Geometry.NormalizedPoint.FromRounded(0.5, 0.9));

        Assert.Single(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));
    }

    [Fact]
    public void SmoothingUsesOnlyTheSamplesThatExistAtTheEdges()
    {
        var samples = SceneFixture.Line(5, 200, (0.1, 0.1), (0.5, 0.5));

        var smoothed = StationaryDetector.Smooth(Path(samples), Parameters.SmoothingWindowSamples);

        Assert.Equal(samples.Count, smoothed.Length);
        Assert.All(smoothed, point => Assert.InRange(point.X, 0.1, 0.5));
    }

    // Departure and gaps
    [Fact]
    public void StandingThenLeavingClosesTheInterval()
    {
        var samples = SceneFixture.Concat(
            SceneFixture.Held(41, 200, (0.5, 0.5)),
            SceneFixture.Line(21, 200, (0.5, 0.5), (0.1, 0.5), startMs: 8_200));

        var interval = Assert.Single(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));

        Assert.Equal(0, interval.StartOffsetMs);
        Assert.True(interval.EndOffsetMs <= 8_600);
    }

    [Fact]
    public void StillnessIsNotInferredAcrossALongGap()
    {
        // Two four-second stays either side of a ten-second gap. Neither is long
        // enough on its own, and nothing may be concluded about the gap.
        var samples = SceneFixture.Concat(
            SceneFixture.Held(21, 200, (0.5, 0.5)),
            SceneFixture.Held(21, 200, (0.5, 0.5), startMs: 14_000));

        Assert.Empty(StationaryDetector.Detect(Path(samples), ObjectClass.Person, Parameters));
    }

    [Fact]
    public void StationaryZoneIsTheZoneHoldingTheIntervalMidpoint()
    {
        var revision = SceneFixture.Revision(zones: [SceneFixture.CentreZone()]);
        var samples = SceneFixture.Held(41, 200, (0.5, 0.5));
        var path = Path(samples);
        var intervals = StationaryDetector.Detect(path, ObjectClass.Person, Parameters);

        var zones = StationaryDetector.ZonesContaining(
            path,
            intervals,
            [.. revision.Zones.Select(zone => (zone.ZoneId, zone.Vertices))]);

        Assert.Equal([revision.Zones[0].ZoneId], zones);
    }

    [Fact]
    public void StillnessOutsideEveryZoneNamesNoZone()
    {
        var revision = SceneFixture.Revision(zones: [SceneFixture.CentreZone()]);
        var samples = SceneFixture.Held(41, 200, (0.05, 0.05));
        var path = Path(samples);

        var zones = StationaryDetector.ZonesContaining(
            path,
            StationaryDetector.Detect(path, ObjectClass.Person, Parameters),
            [.. revision.Zones.Select(zone => (zone.ZoneId, zone.Vertices))]);

        Assert.Empty(zones);
    }

    // Loitering
    [Fact]
    public void DwellAtTheDefaultThresholdLoiters()
    {
        var summary = Summarise(ObjectClass.Person, null, Visit(0, 120_000));

        Assert.True(summary.Loitering);
        Assert.Equal(Parameters.LoiteringDefaultSeconds, summary.LoiteringThresholdSeconds);
        Assert.Equal(120_000, summary.LoiteringDwellMs);
        Assert.Equal([0], summary.LoiteringVisitIndexes);
    }

    [Fact]
    public void DwellJustBelowTheThresholdDoesNotLoiter()
    {
        var summary = Summarise(ObjectClass.Person, null, Visit(0, 119_999));

        Assert.False(summary.Loitering);
        Assert.Equal(0, summary.LoiteringDwellMs);
        Assert.Empty(summary.LoiteringVisitIndexes);
    }

    [Fact]
    public void ZoneThresholdOverridesTheDefault()
    {
        var summary = Summarise(ObjectClass.Person, 30, Visit(0, 40_000));

        Assert.True(summary.Loitering);
        Assert.Equal(30, summary.LoiteringThresholdSeconds);
    }

    [Fact]
    public void DwellAccumulatesAcrossVisits()
    {
        var summary = Summarise(ObjectClass.Person, 60, Visit(0, 30_000), Visit(1, 31_000, startMs: 90_000));

        Assert.True(summary.Loitering);
        Assert.Equal(61_000, summary.LoiteringDwellMs);
        Assert.Equal([0, 1], summary.LoiteringVisitIndexes);
        Assert.Equal(2, summary.VisitCount);
        Assert.Equal(0, summary.FirstEntryOffsetMs);
        Assert.Equal(121_000, summary.LastExitOffsetMs);
    }

    [Fact]
    public void VehiclesAreNeverFlaggedAsLoitering()
    {
        var summary = Summarise(ObjectClass.Vehicle, 30, Visit(0, 600_000));

        Assert.False(summary.Loitering);
        Assert.Equal(600_000, summary.TotalDwellMs);
    }

    [Fact]
    public void ZoneNeverVisitedSummarisesAsEmpty()
    {
        var summary = Summarise(ObjectClass.Person, null);

        Assert.Equal(0, summary.VisitCount);
        Assert.Equal(0, summary.TotalDwellMs);
        Assert.False(summary.Loitering);
    }

    // Helpers
    private static TrajectoryPath Path(IReadOnlyList<TrajectorySample> samples) =>
        TrajectoryPath.Create(samples, Parameters);

    private static ZoneVisitFact Visit(int index, long dwellMs, long startMs = 0) => new(
        Guid.Empty,
        index,
        startMs,
        startMs + dwellMs,
        dwellMs,
        BeganInside: false,
        EndedInside: false,
        ClosedByGap: false,
        AnalysisHeading.None,
        AnalysisHeading.None);

    private static ZoneSummaryFact Summarise(
        ObjectClass objectClass,
        int? thresholdSeconds,
        params ZoneVisitFact[] visits)
    {
        var revision = SceneFixture.Revision(zones:
            [SceneFixture.CentreZone(loiteringThresholdSeconds: thresholdSeconds)]);
        return LoiteringRule.Summarise(revision.Zones[0], objectClass, visits, Parameters);
    }

    /// <summary>A path that oscillates by a fixed amount around one point.</summary>
    private static IReadOnlyList<TrajectorySample> Wobble(
        int count,
        long stepMs,
        (double X, double Y) centre,
        double amplitude) =>
        [.. Enumerable.Range(0, count).Select(index => new TrajectorySample(
            index * stepMs,
            Mavi.Domain.Scene.Geometry.NormalizedPoint.FromRounded(
                centre.X + (index % 2 == 0 ? 0 : amplitude),
                centre.Y)))];
}
