using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests.SceneAnalytics;

/// <summary>
/// Golden fixtures for the frozen Slice-6 counting rules (plan §4.2, §13.1).
/// </summary>
/// <remarks>
/// Each test is written to fail under the most plausible wrong implementation:
/// closed instead of half-open boundaries, event counts where distinct Tracks are
/// meant, occupancy integrated instead of sampled, window totals recovered by
/// summing buckets.
/// </remarks>
public sealed class AnalyticsAggregatorTests
{
    private static readonly DateTimeOffset From = new(2026, 9, 22, 9, 0, 0, TimeSpan.Zero);
    private static readonly DateTimeOffset To = new(2026, 9, 22, 9, 5, 0, TimeSpan.Zero);
    private const int Minute = 60;

    private static readonly Guid ZoneA = Guid.Parse("11111111-1111-4111-8111-111111111111");
    private static readonly Guid LineA = Guid.Parse("22222222-2222-4222-8222-222222222222");
    private static readonly Guid Track1 = Guid.Parse("33333333-3333-4333-8333-333333333331");
    private static readonly Guid Track2 = Guid.Parse("33333333-3333-4333-8333-333333333332");
    private static readonly Guid Track3 = Guid.Parse("33333333-3333-4333-8333-333333333333");

    private static DateTimeOffset At(int minutes, int seconds = 0) =>
        From.AddMinutes(minutes).AddSeconds(seconds);

    private static AnalyticsFactSet Facts(
        IEnumerable<ZoneVisitFact>? visits = null,
        IEnumerable<LineCrossingFact>? crossings = null,
        IEnumerable<ZoneSummaryFact>? summaries = null,
        IEnumerable<TrackIntervalFact>? tracks = null,
        IEnumerable<EnabledZone>? zones = null,
        IEnumerable<EnabledLine>? lines = null) =>
        new(
            (zones ?? [new EnabledZone(ZoneA, "Forecourt")]).ToList(),
            (lines ?? [new EnabledLine(LineA, "Gate A", "Inbound", "Outbound")]).ToList(),
            (visits ?? []).ToList(),
            (crossings ?? []).ToList(),
            (summaries ?? []).ToList(),
            (tracks ?? []).ToList());

    private static AnalyticsSeriesSet Compute(AnalyticsFactSet facts) =>
        AnalyticsAggregator.Compute(facts, From, To, Minute);

    // --- Buckets ------------------------------------------------------------

    [Fact]
    public void BucketsAreAnchoredToTheWindowStartNotTheClock()
    {
        // 09:00:30 is not a minute boundary on the wall clock. Anchoring to fromUtc is
        // what makes a shared window reproducible in any timezone.
        var from = From.AddSeconds(30);
        var buckets = AnalyticsBuckets.Build(from, from.AddMinutes(2), Minute);

        Assert.Equal(2, buckets.Count);
        Assert.Equal(from, buckets[0].StartUtc);
        Assert.Equal(from.AddMinutes(1), buckets[0].EndUtc);
        Assert.Equal(from.AddMinutes(1), buckets[1].StartUtc);
    }

    [Fact]
    public void TheFinalBucketIsShortAndClippedToTheWindow()
    {
        var buckets = AnalyticsBuckets.Build(From, From.AddSeconds(150), Minute);

        Assert.Equal(3, buckets.Count);
        Assert.Equal(From.AddSeconds(150), buckets[2].EndUtc);
        Assert.Equal(TimeSpan.FromSeconds(30), buckets[2].EndUtc - buckets[2].StartUtc);
    }

    [Fact]
    public void AnInstantAtTheWindowEndIsOutsideEveryBucket()
    {
        // Half-open: toUtc belongs to the next window, not to the last bucket.
        Assert.Equal(-1, AnalyticsBuckets.IndexOf(To, From, Minute, 5));
        Assert.Equal(4, AnalyticsBuckets.IndexOf(To.AddTicks(-1), From, Minute, 5));
        Assert.Equal(-1, AnalyticsBuckets.IndexOf(From.AddTicks(-1), From, Minute, 5));
    }

    // --- Zone entries and exits --------------------------------------------

    [Fact]
    public void AnEntryExactlyOnABucketBoundaryBelongsToTheLaterBucket()
    {
        // The discriminating case: closed intervals would put this in bucket 0 as well.
        var facts = Facts(visits: [new ZoneVisitFact(Track1, ZoneA, At(1), At(2), false, false)]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal([0, 1, 0, 0, 0], zone.EntryCounts);
        Assert.Equal([0, 0, 1, 0, 0], zone.ExitCounts);
    }

    [Fact]
    public void AnEntryExactlyAtTheWindowStartIsCountedAndOneAtTheEndIsNot()
    {
        var facts = Facts(visits:
        [
            new ZoneVisitFact(Track1, ZoneA, From, At(0, 30), false, false),
            // Exits exactly at toUtc: outside the half-open window entirely.
            new ZoneVisitFact(Track2, ZoneA, At(4), To, false, false),
        ]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal(1, zone.EntryCounts[0]);
        Assert.Equal(2, zone.WindowEntryCount);
        // Track2's exit is at toUtc, which no bucket owns.
        Assert.Equal(1, zone.WindowExitCount);
    }

    [Fact]
    public void AVisitAlreadyInsideTheZoneIsNotAnEntryEvent()
    {
        // beganInside means the Track was already there; there is no crossing to count.
        var facts = Facts(visits: [new ZoneVisitFact(Track1, ZoneA, At(1), At(2), true, true)]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal(0, zone.WindowEntryCount);
        Assert.Equal(0, zone.WindowExitCount);
        // It is still occupancy and still a unique Track: it happened.
        Assert.Equal(1, zone.WindowUniqueTrackCount);
    }

    // --- Unique Tracks ------------------------------------------------------

    [Fact]
    public void OneTrackVisitingTwiceInABucketIsOneUniqueTrack()
    {
        // Event counting would say 2. Distinct-Track counting says 1.
        var facts = Facts(visits:
        [
            new ZoneVisitFact(Track1, ZoneA, At(0, 5), At(0, 15), false, false),
            new ZoneVisitFact(Track1, ZoneA, At(0, 30), At(0, 45), false, false),
        ]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal(1, zone.UniqueTrackCounts[0]);
        Assert.Equal(2, zone.EntryCounts[0]);
        Assert.Equal(1, zone.WindowUniqueTrackCount);
    }

    [Fact]
    public void ATrackSpanningBucketsIsUniqueInEachButOnceInTheWindow()
    {
        // The non-additive case the window total exists for: summing the series gives
        // 3, and the window answer is 1.
        var facts = Facts(visits: [new ZoneVisitFact(Track1, ZoneA, At(0, 30), At(2, 30), false, false)]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal([1, 1, 1, 0, 0], zone.UniqueTrackCounts);
        Assert.Equal(3, zone.UniqueTrackCounts.Sum());
        Assert.Equal(1, zone.WindowUniqueTrackCount);
    }

    [Fact]
    public void AVisitOnlyTouchingABucketEndpointIsNotActivityInIt()
    {
        // Ends exactly where bucket 1 starts: positive overlap requires end > start.
        var facts = Facts(visits: [new ZoneVisitFact(Track1, ZoneA, At(0, 10), At(1), false, false)]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal([1, 0, 0, 0, 0], zone.UniqueTrackCounts);
    }

    // --- Occupancy ----------------------------------------------------------

    [Fact]
    public void OccupancyIsSampledAtBucketStarts()
    {
        // Wholly inside bucket 0 and never present at any bucket start: a sampled
        // metric reports zero, an integrated one would not.
        var facts = Facts(visits: [new ZoneVisitFact(Track1, ZoneA, At(0, 10), At(0, 50), false, false)]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal([0, 0, 0, 0, 0], zone.OccupancyAtStart);
        Assert.Equal(0, zone.PeakOccupancy);
        Assert.Null(zone.PeakOccupancyAtUtc);
        // It was still observed: the unique-Track series is how that shows.
        Assert.Equal(1, zone.WindowUniqueTrackCount);
    }

    [Fact]
    public void OccupancyCountsAVisitThatEnteredExactlyAtTheBucketStart()
    {
        var facts = Facts(visits:
        [
            new ZoneVisitFact(Track1, ZoneA, At(1), At(3), false, false),
            // Leaves exactly at bucket 3's start, so it is gone by then.
            new ZoneVisitFact(Track2, ZoneA, At(0), At(3), false, false),
        ]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal([1, 2, 2, 0, 0], zone.OccupancyAtStart);
    }

    [Fact]
    public void PeakOccupancyTakesTheEarliestInstantOnATie()
    {
        var facts = Facts(visits:
        [
            new ZoneVisitFact(Track1, ZoneA, At(0), At(2), false, false),
            new ZoneVisitFact(Track2, ZoneA, At(0), At(2), false, false),
            new ZoneVisitFact(Track3, ZoneA, At(3), At(5), false, false),
        ]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal([2, 2, 0, 1, 1], zone.OccupancyAtStart);
        Assert.Equal(2, zone.PeakOccupancy);
        Assert.Equal(From, zone.PeakOccupancyAtUtc);
    }

    // --- Repeated visits ----------------------------------------------------

    [Fact]
    public void RepeatedVisitsIsAWholeTrackSummaryNotTwoVisitsInTheWindow()
    {
        // Track1 visited twice over its life; only one of those visits is in scope.
        // Track2 visited once. The metric reads the persisted summary, not the window.
        var facts = Facts(
            visits: [new ZoneVisitFact(Track1, ZoneA, At(1), At(2), false, false)],
            summaries:
            [
                new ZoneSummaryFact(Track1, ZoneA, 2),
                new ZoneSummaryFact(Track2, ZoneA, 1),
            ]);

        var zone = Compute(facts).Zones.Single();

        Assert.Equal(1, zone.RepeatedVisitTrackCount);
    }

    // --- Lines --------------------------------------------------------------

    [Fact]
    public void TheTwoCrossingDirectionsAreIndependentCounts()
    {
        // A crossing each way is two crossings, never a net flow of zero.
        var facts = Facts(crossings:
        [
            new LineCrossingFact(LineA, At(1, 10), true),
            new LineCrossingFact(LineA, At(1, 20), false),
            new LineCrossingFact(LineA, At(2), true),
        ]);

        var line = Compute(facts).Lines.Single();

        Assert.Equal([0, 1, 1, 0, 0], line.AToBCounts);
        Assert.Equal([0, 1, 0, 0, 0], line.BToACounts);
        Assert.Equal(2, line.WindowAToBCount);
        Assert.Equal(1, line.WindowBToACount);
    }

    [Fact]
    public void ACrossingExactlyAtTheWindowEndIsOutsideTheRequest()
    {
        var facts = Facts(crossings: [new LineCrossingFact(LineA, To, true)]);

        var line = Compute(facts).Lines.Single();

        Assert.Equal(0, line.WindowAToBCount);
    }

    // --- Classes ------------------------------------------------------------

    [Fact]
    public void ClassCountsAreDistinctTracksOverlappingEachBucket()
    {
        var facts = Facts(tracks:
        [
            new TrackIntervalFact(Track1, ObjectClass.Person, At(0, 30), At(2, 30)),
            new TrackIntervalFact(Track2, ObjectClass.Person, At(1), At(1, 30)),
            new TrackIntervalFact(Track3, ObjectClass.Vehicle, At(4), At(4, 30)),
        ]);

        var classes = Compute(facts).Classes;
        var person = classes.Single(x => x.ObjectClass == ObjectClass.Person);
        var vehicle = classes.Single(x => x.ObjectClass == ObjectClass.Vehicle);

        Assert.Equal([1, 2, 1, 0, 0], person.Counts);
        // Summing gives 4; the window holds two distinct Person Tracks.
        Assert.Equal(4, person.Counts.Sum());
        Assert.Equal(2, person.WindowDistinctTrackCount);
        Assert.Equal([0, 0, 0, 0, 1], vehicle.Counts);
        Assert.Equal(1, vehicle.WindowDistinctTrackCount);
    }

    [Fact]
    public void EveryClassInTheVocabularyGetsASeriesEvenWithNoTracks()
    {
        var classes = Compute(Facts()).Classes;

        Assert.Equal(2, classes.Count);
        Assert.All(classes, series => Assert.Equal(5, series.Counts.Count));
        Assert.All(classes, series => Assert.Equal(0, series.WindowDistinctTrackCount));
    }

    // --- Shape --------------------------------------------------------------

    [Fact]
    public void EverySeriesHasExactlyOneValuePerBucket()
    {
        var result = AnalyticsAggregator.Compute(
            Facts(visits: [new ZoneVisitFact(Track1, ZoneA, At(1), At(2), false, false)]),
            From,
            From.AddSeconds(150),
            Minute);

        Assert.Equal(3, result.Buckets.Count);
        var zone = result.Zones.Single();
        Assert.Equal(3, zone.EntryCounts.Count);
        Assert.Equal(3, zone.ExitCounts.Count);
        Assert.Equal(3, zone.UniqueTrackCounts.Count);
        Assert.Equal(3, zone.OccupancyAtStart.Count);
        var line = result.Lines.Single();
        Assert.Equal(3, line.AToBCounts.Count);
        Assert.Equal(3, line.BToACounts.Count);
    }

    [Fact]
    public void OnlyGeometrySuppliedAsEnabledProducesASeries()
    {
        // The repository supplies enabled geometry only. A disabled zone's facts
        // cannot conjure a row of zeros that would read as an observed absence.
        var facts = Facts(
            visits: [new ZoneVisitFact(Track1, ZoneA, At(1), At(2), false, false)],
            zones: []);

        Assert.Empty(Compute(facts).Zones);
    }
}
