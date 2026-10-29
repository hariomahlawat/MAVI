using Mavi.Application.Modules.Events;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;

namespace Mavi.Application.Tests.Events;

/// <summary>
/// One deterministic fixture per catalogue rule (register C7.1): each rule fires on a
/// constructed set of persisted facts, stays silent on the near miss beside it, and
/// produces byte-identical output however its input rows happen to be ordered.
/// </summary>
public sealed class EventRuleFixtureTests
{
    private static readonly DateTimeOffset RecordingStart = new(2026, 10, 29, 9, 0, 0, TimeSpan.Zero);

    private static readonly Guid Unit = Id(1);
    private static readonly Guid Revision = Id(2);
    private static readonly Guid Bay = Id(10);       // Restricted
    private static readonly Guid Pavement = Id(11);  // General
    private static readonly Guid Closed = Id(12);    // disabled
    private static readonly Guid Gate = Id(20);      // one-way A→B
    private static readonly Guid Kerb = Id(21);      // two-way
    private static readonly Guid Person = Id(100);
    private static readonly Guid Car = Id(101);
    private static readonly Guid Van = Id(102);
    private static readonly Guid Walker = Id(103);

    // --- line-crossing ------------------------------------------------------

    [Fact]
    public void LineCrossingIsOneEventPerCrossingOfAnEnabledLine()
    {
        var input = Input(crossings:
        [
            Cross(Id(300), Car, Gate, 0, 4_000, "AToB"),
            Cross(Id(301), Person, Kerb, 0, 6_000, "BToA"),
            Cross(Id(302), Car, Id(29), 1, 7_000, "AToB"), // a line the revision does not enable
        ]);

        var events = Derive(input, EventRuleIds.LineCrossing);

        Assert.Equal(2, events.Count);
        Assert.Equal([Gate, Kerb], events.Select(item => item.LineId!.Value));
        Assert.Equal(["AToB", "BToA"], events.Select(item => item.Direction));
        Assert.Equal("Inbound", events[0].Provenance.Details.Single(detail => detail.Name == "directionLabel").Value);
        Assert.Equal(RecordingStart.AddMilliseconds(4_000), events[0].StartUtc);
        Assert.Equal(events[0].StartUtc, events[0].EndUtc);
    }

    // --- zone-dwell -----------------------------------------------------------

    [Fact]
    public void DwellIsTheStageThreeLoiteringVerdictWithTheInstantTheThresholdWasReached()
    {
        var input = Input(
            visits:
            [
                Visit(Id(400), Person, Pavement, 0, 1_000, 11_000),
                Visit(Id(401), Person, Pavement, 1, 20_000, 30_000),
                Visit(Id(402), Walker, Pavement, 0, 1_000, 9_000),
            ],
            summaries:
            [
                // 20 s of dwell against a 15 s threshold: the verdict scene analytics persisted.
                new EventZoneSummary(Person, Pavement, 2, 20_000, Loitering: true, LoiteringThresholdSeconds: 15),
                // The near miss: 8 s against 15 s, verdict false.
                new EventZoneSummary(Walker, Pavement, 1, 8_000, Loitering: false, LoiteringThresholdSeconds: 15),
            ]);

        var single = Assert.Single(Derive(input, EventRuleIds.ZoneDwell));

        Assert.Equal(Person, single.PrimaryTrackId);
        Assert.Equal(Pavement, single.ZoneId);
        Assert.Equal(25_000, single.StartOffsetMs);
        Assert.Equal(30_000, single.EndOffsetMs);
        // 10 s in the first visit, 5 s more needed in the second, which began at 20 s.
        Assert.Equal("25000", single.Provenance.Details.Single(detail => detail.Name == "thresholdReachedOffsetMs").Value);
        var threshold = Assert.Single(single.Provenance.Parameters);
        Assert.Equal(("thresholdSeconds", "15", RuleParameterSource.SceneRevision), (threshold.Name, threshold.Value, threshold.Source));
        Assert.Equal(3, single.Provenance.Inputs.Count); // the summary and both visits
    }

    // --- stopped-vehicle -------------------------------------------------------

    [Fact]
    public void AStoppedVehicleIsMeasuredInsideTheRestrictedZoneNotAnywhere()
    {
        var input = Input(
            visits:
            [
                Visit(Id(500), Car, Bay, 0, 10_000, 70_000),
                // The van stood for 40 s, but only 20 s of it inside the bay: the near miss
                // that "stationary anywhere" (the S2 audit query) would have counted.
                Visit(Id(501), Van, Bay, 0, 30_000, 50_000),
                // A General zone never counts, however long the stop.
                Visit(Id(502), Car, Pavement, 0, 0, 90_000),
            ],
            intervals:
            [
                new EventStationaryInterval(Car, 0, 15_000, 55_000),
                new EventStationaryInterval(Van, 0, 0, 40_000),
                // A person standing still is not a stopped vehicle.
                new EventStationaryInterval(Person, 0, 0, 60_000),
            ]);

        var single = Assert.Single(Derive(input, EventRuleIds.StoppedVehicle));

        Assert.Equal(Car, single.PrimaryTrackId);
        Assert.Equal(Bay, single.ZoneId);
        Assert.Equal((15_000L, 55_000L), (single.StartOffsetMs, single.EndOffsetMs));
        var minimum = single.Provenance.Parameters.Single(parameter => parameter.Name == "minimumStationarySeconds");
        Assert.Equal(("30", RuleParameterSource.OwnerDecision), (minimum.Value, minimum.Source));
    }

    [Fact]
    public void AStopOfExactlyTheMinimumFires()
    {
        var input = Input(
            visits: [Visit(Id(510), Car, Bay, 0, 0, 30_000)],
            intervals: [new EventStationaryInterval(Car, 0, 0, 30_000)]);

        Assert.Single(Derive(input, EventRuleIds.StoppedVehicle));
    }

    // --- wrong-way --------------------------------------------------------------

    [Fact]
    public void WrongWayFiresOnlyAgainstAPermittedDirection()
    {
        var input = Input(crossings:
        [
            Cross(Id(600), Car, Gate, 0, 4_000, "AToB"),   // permitted
            Cross(Id(601), Van, Gate, 0, 5_000, "BToA"),   // against
            Cross(Id(602), Person, Kerb, 0, 6_000, "BToA"), // line has no permitted direction
        ]);

        var single = Assert.Single(Derive(input, EventRuleIds.WrongWay));

        Assert.Equal(Van, single.PrimaryTrackId);
        Assert.Equal("BToA", single.Direction);
        var permitted = Assert.Single(single.Provenance.Parameters);
        Assert.Equal(("AToB", RuleParameterSource.SceneRevision), (permitted.Value, permitted.Source));
        Assert.Equal("Inbound", single.Provenance.Details.Single(detail => detail.Name == "permittedLabel").Value);
    }

    // --- co-occurrence ------------------------------------------------------------

    [Fact]
    public void CoOccurrenceIsOneEpisodePerZoneWhileAPersonAndAVehicleAreBothInside()
    {
        var input = Input(visits:
        [
            Visit(Id(700), Car, Bay, 0, 10_000, 40_000),
            Visit(Id(701), Person, Bay, 0, 20_000, 30_000),
            Visit(Id(702), Walker, Bay, 0, 28_000, 50_000),
            // Touching end to start is not overlap.
            Visit(Id(703), Van, Bay, 0, 50_000, 60_000),
            // Two vehicles together are not a co-occurrence.
            Visit(Id(704), Car, Pavement, 0, 0, 10_000),
            Visit(Id(705), Van, Pavement, 0, 0, 10_000),
            // Nothing in a disabled zone counts.
            Visit(Id(706), Car, Closed, 0, 0, 10_000),
            Visit(Id(707), Person, Closed, 0, 0, 10_000),
        ]);

        var single = Assert.Single(Derive(input, EventRuleIds.CoOccurrence));

        Assert.Equal(Bay, single.ZoneId);
        // From the person's entry until the car left; the walker keeps it going past 30 s.
        Assert.Equal((20_000L, 40_000L), (single.StartOffsetMs, single.EndOffsetMs));
        Assert.Equal([Person, Car, Walker], single.Provenance.Participants.Select(participant => participant.TrackId));
        Assert.Null(single.PrimaryTrackId);
    }

    [Fact]
    public void TwoSeparateEpisodesInOneZoneAreTwoEvents()
    {
        var input = Input(visits:
        [
            Visit(Id(710), Car, Bay, 0, 0, 100_000),
            Visit(Id(711), Person, Bay, 0, 10_000, 20_000),
            Visit(Id(712), Person, Bay, 1, 50_000, 60_000),
        ]);

        var events = Derive(input, EventRuleIds.CoOccurrence);

        Assert.Equal([10_000L, 50_000L], events.Select(item => item.StartOffsetMs));
        Assert.NotEqual(events[0].EventId, events[1].EventId);
    }

    // --- repeated-visit (disabled in v1) ----------------------------------------------

    [Fact]
    public void RepeatedVisitIsDisabledInV1AndTheDeriverDoesNotRunIt()
    {
        var rule = RuleCatalogue.V1.Rule(EventRuleIds.RepeatedVisit);
        Assert.False(rule.Enabled);
        Assert.Equal(RuleCatalogue.RequiresEntityConfirmation, rule.DisabledReason);

        var entity = Id(900);
        var result = EventDeriver.Derive(RepeatedVisitInput(entity), RuleCatalogue.V1);

        Assert.DoesNotContain(result.Events, item => item.RuleId == EventRuleIds.RepeatedVisit);
        var state = result.RuleStates.Single(item => item.RuleId == EventRuleIds.RepeatedVisit);
        Assert.Equal((false, RuleCatalogue.RequiresEntityConfirmation, (int?)null), (state.Enabled, state.DisabledReason, state.EventCount));
    }

    [Fact]
    public void RepeatedVisitFiresOnTheFixtureWhenEvaluatedDirectly()
    {
        // Defined and tested now, so enabling it after S7 is a catalogue bump, not new code.
        var entity = Id(900);
        var input = RepeatedVisitInput(entity).Canonical();

        var single = Assert.Single(EventRules.RepeatedVisit(input, 2));

        Assert.Equal(Bay, single.ZoneId);
        Assert.Equal([Person, Walker], single.Provenance.Participants.Select(participant => participant.TrackId));
        Assert.Equal(entity.ToString("D"), single.Provenance.Details.Single(detail => detail.Name == "entityId").Value);
        // Without confirmation (no EntityId) nothing fires.
        Assert.Empty(EventRules.RepeatedVisit(Input(visits: input.Visits).Canonical(), 2));
    }

    // --- determinism and identity -------------------------------------------------------

    [Fact]
    public void TheSameFactsInAnyOrderProduceByteIdenticalOutput()
    {
        var input = Rich();
        var reversed = input with
        {
            Zones = [.. input.Zones.Reverse()],
            Lines = [.. input.Lines.Reverse()],
            Tracks = [.. input.Tracks.Reverse()],
            Visits = [.. input.Visits.Reverse()],
            Summaries = [.. input.Summaries.Reverse()],
            Crossings = [.. input.Crossings.Reverse()],
            StationaryIntervals = [.. input.StationaryIntervals.Reverse()],
        };

        var first = EventDeriver.Derive(input, RuleCatalogue.V1);
        var second = EventDeriver.Derive(reversed, RuleCatalogue.V1);

        Assert.Equal(first.InputsSha256, second.InputsSha256);
        Assert.Equal(first.RuleStatesJson, second.RuleStatesJson);
        Assert.Equal(
            first.Events.Select(item => (item.EventId, item.InputSha256, item.ProvenanceJson)),
            second.Events.Select(item => (item.EventId, item.InputSha256, item.ProvenanceJson)));
        Assert.Contains(first.Events, item => item.RuleId == EventRuleIds.LineCrossing);
        Assert.Contains(first.Events, item => item.RuleId == EventRuleIds.StoppedVehicle);
        Assert.Contains(first.Events, item => item.RuleId == EventRuleIds.WrongWay);
        Assert.Contains(first.Events, item => item.RuleId == EventRuleIds.CoOccurrence);
    }

    [Fact]
    public void TheEventIdentityIsBoundToCatalogueRuleUnitAndDiscriminator()
    {
        var baseline = EventDeriver.EventId("mavi-events-v1", EventRuleIds.LineCrossing, 1, Unit, "x");

        Assert.Equal(baseline, EventDeriver.EventId("mavi-events-v1", EventRuleIds.LineCrossing, 1, Unit, "x"));
        Assert.NotEqual(baseline, EventDeriver.EventId("mavi-events-v2", EventRuleIds.LineCrossing, 1, Unit, "x"));
        Assert.NotEqual(baseline, EventDeriver.EventId("mavi-events-v1", EventRuleIds.WrongWay, 1, Unit, "x"));
        Assert.NotEqual(baseline, EventDeriver.EventId("mavi-events-v1", EventRuleIds.LineCrossing, 2, Unit, "x"));
        Assert.NotEqual(baseline, EventDeriver.EventId("mavi-events-v1", EventRuleIds.LineCrossing, 1, Id(2), "x"));
        Assert.NotEqual(baseline, EventDeriver.EventId("mavi-events-v1", EventRuleIds.LineCrossing, 1, Unit, "y"));
        Assert.Equal(8, baseline.Version);
    }

    [Fact]
    public void ADifferentRevisionChangesEveryDigestButNoFactIdentity()
    {
        var input = Rich();
        var moved = input with { Unit = input.Unit with { SceneRevisionId = Id(3) } };

        var first = EventDeriver.Derive(input, RuleCatalogue.V1);
        var second = EventDeriver.Derive(moved, RuleCatalogue.V1);

        Assert.NotEqual(first.InputsSha256, second.InputsSha256);
        Assert.All(first.Events.Zip(second.Events), pair => Assert.NotEqual(pair.First.InputSha256, pair.Second.InputSha256));
    }

    [Fact]
    public void TheCatalogueDigestIsStableAndEveryRuleHasAnImplementation()
    {
        Assert.Equal(RuleCatalogue.V1.Sha256, new RuleCatalogueDefinition(RuleCatalogue.V1.CatalogueVersion, RuleCatalogue.V1.Rules).Sha256);
        Assert.Equal(EventRuleIds.All, RuleCatalogue.V1.Rules.Select(rule => rule.RuleId));
        foreach (var rule in RuleCatalogue.V1.Rules)
        {
            _ = EventDeriver.Evaluate(rule, Rich().Canonical());
            Assert.All(rule.Parameters, parameter => Assert.Contains(
                parameter.Source,
                new[] { RuleParameterSource.SceneRevision, RuleParameterSource.OwnerDecision, RuleParameterSource.Catalogue }));
        }
    }

    // --- Fixture -----------------------------------------------------------------------

    private static IReadOnlyList<DerivedEvent> Derive(EventDerivationInput input, string ruleId) =>
        [.. EventDeriver.Derive(input, RuleCatalogue.V1).Events.Where(item => item.RuleId == ruleId)];

    private static EventDerivationInput Rich() => Input(
        visits:
        [
            Visit(Id(800), Car, Bay, 0, 0, 60_000),
            Visit(Id(801), Person, Bay, 0, 10_000, 20_000),
        ],
        crossings:
        [
            Cross(Id(810), Car, Gate, 0, 61_000, "AToB"),
            Cross(Id(811), Van, Gate, 0, 62_000, "BToA"),
            // The same Track's first crossing of a second line: a crossing index is
            // numbered per (Track, line), so this one is also index 0.
            Cross(Id(812), Car, Kerb, 0, 30_000, "BToA"),
        ],
        summaries:
        [
            new EventZoneSummary(Car, Bay, 1, 60_000, Loitering: false, LoiteringThresholdSeconds: 120),
            new EventZoneSummary(Person, Bay, 1, 10_000, Loitering: false, LoiteringThresholdSeconds: 120),
        ],
        intervals: [new EventStationaryInterval(Car, 0, 5_000, 50_000)]);

    private static EventDerivationInput RepeatedVisitInput(Guid entity) => Input(
        tracks:
        [
            new EventTrack(Person, ObjectClass.Person, entity),
            new EventTrack(Walker, ObjectClass.Person, entity),
            new EventTrack(Car, ObjectClass.Vehicle, null),
        ],
        visits:
        [
            Visit(Id(910), Person, Bay, 0, 0, 5_000),
            Visit(Id(911), Walker, Bay, 0, 60_000, 65_000),
            Visit(Id(912), Car, Bay, 0, 0, 5_000),
        ]);

    private static EventDerivationInput Input(
        IReadOnlyList<EventTrack>? tracks = null,
        IReadOnlyList<EventZoneVisit>? visits = null,
        IReadOnlyList<EventZoneSummary>? summaries = null,
        IReadOnlyList<EventLineCrossing>? crossings = null,
        IReadOnlyList<EventStationaryInterval>? intervals = null) => new(
            new EventUnitIdentity(Unit, Id(5), Id(6), Id(7), Revision, 1, "scene-analytics-v1", RecordingStart),
            [
                new EventZone(Bay, "Parking bay", SceneZoneKind.Restricted, true),
                new EventZone(Pavement, "Pavement", SceneZoneKind.General, true),
                new EventZone(Closed, "Closed", SceneZoneKind.Restricted, false),
            ],
            [
                new EventLine(Gate, "Gate", true, "Inbound", "Outbound", TripLine.PermittedDirectionAToB),
                new EventLine(Kerb, "Kerb", true, "Away", "Toward", null),
            ],
            tracks ??
            [
                new EventTrack(Person, ObjectClass.Person, null),
                new EventTrack(Walker, ObjectClass.Person, null),
                new EventTrack(Car, ObjectClass.Vehicle, null),
                new EventTrack(Van, ObjectClass.Vehicle, null),
            ],
            visits ?? [],
            summaries ?? [],
            crossings ?? [],
            intervals ?? []);

    private static EventZoneVisit Visit(Guid id, Guid track, Guid zone, int index, long entry, long exit) =>
        new(id, track, zone, index, entry, exit, exit - entry);

    private static EventLineCrossing Cross(Guid id, Guid track, Guid line, int index, long offset, string direction) =>
        new(id, track, line, index, offset, direction, RecordingStart.AddMilliseconds(offset));

    private static Guid Id(int value) => new($"00000000-0000-0000-0000-{value:D12}");
}
