using System.Globalization;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;

namespace Mavi.Application.Modules.Events;

/// <summary>
/// The pure rules of the catalogue. Each takes one canonical derivation input and
/// returns its events in a deterministic order; none reads a clock, a model or a
/// trajectory (ADR-025 §1).
/// </summary>
/// <remarks>
/// The rules build on scene-analytics facts rather than recompute them: a crossing is
/// the persisted crossing, dwell is the persisted loitering verdict, and a stationary
/// interval is the persisted one. What a rule adds is the condition that turns facts
/// into an occurrence an operator can put on a timeline, and the evidence for it.
/// </remarks>
public static class EventRules
{
    public const string SubjectRole = "subject";
    public const string ParticipantRole = "participant";

    public static IReadOnlyList<EventDraft> LineCrossing(EventDerivationInput input)
    {
        var lines = EnabledLines(input);
        var classes = Classes(input);
        var events = new List<EventDraft>();
        foreach (var crossing in input.Crossings)
        {
            if (!lines.TryGetValue(crossing.LineId, out var line) || !classes.TryGetValue(crossing.TrackId, out var objectClass))
                continue;

            events.Add(new EventDraft(
                crossing.CrossingId.ToString("D"),
                crossing.TrackId,
                objectClass,
                ZoneId: null,
                line.LineId,
                crossing.Direction,
                crossing.OffsetMs,
                crossing.OffsetMs,
                new EventProvenance(
                    [new EventParticipant(crossing.TrackId, SubjectRole, objectClass)],
                    [Crossing(crossing)],
                    [],
                    [new EventDetail("directionLabel", DirectionLabel(line, crossing.Direction))]),
                crossing.TimestampUtc));
        }

        return events;
    }

    public static IReadOnlyList<EventDraft> ZoneDwell(EventDerivationInput input)
    {
        var zones = EnabledZones(input);
        var classes = Classes(input);
        var events = new List<EventDraft>();
        foreach (var summary in input.Summaries)
        {
            // The scene-analytics verdict is the rule: it is person-only and already
            // compares total dwell with the zone's threshold (plan §M).
            if (!summary.Loitering || !zones.ContainsKey(summary.ZoneId) ||
                !classes.TryGetValue(summary.TrackId, out var objectClass))
                continue;

            var visits = input.Visits
                .Where(visit => visit.TrackId == summary.TrackId && visit.ZoneId == summary.ZoneId)
                .OrderBy(visit => visit.VisitIndex)
                .ToList();
            if (visits.Count == 0)
                continue;

            var thresholdMs = summary.LoiteringThresholdSeconds * 1000L;
            long accumulated = 0;
            long? reachedAt = null;
            foreach (var visit in visits)
            {
                if (accumulated + visit.DwellMs >= thresholdMs)
                {
                    reachedAt = visit.EntryOffsetMs + Math.Max(0, thresholdMs - accumulated);
                    break;
                }

                accumulated += visit.DwellMs;
            }

            events.Add(new EventDraft(
                summary.TrackId.ToString("D") + "/" + summary.ZoneId.ToString("D"),
                summary.TrackId,
                objectClass,
                summary.ZoneId,
                LineId: null,
                Direction: null,
                visits[0].EntryOffsetMs,
                visits.Max(visit => visit.ExitOffsetMs),
                new EventProvenance(
                    [new EventParticipant(summary.TrackId, SubjectRole, objectClass)],
                    [
                        new EventInputReference("zoneSummary", summary.TrackId.ToString("D") + "/" + summary.ZoneId.ToString("D"), null, null),
                        .. visits.Select(Visit),
                    ],
                    [
                        new EventAppliedParameter(
                            "thresholdSeconds",
                            Number(summary.LoiteringThresholdSeconds),
                            "s",
                            RuleParameterSource.SceneRevision,
                            "zone loiteringThresholdSeconds at the unit's revision (engine default when unset)"),
                    ],
                    [
                        new EventDetail("totalDwellMs", Number(summary.TotalDwellMs)),
                        new EventDetail("visitCount", Number(summary.VisitCount)),
                        new EventDetail("thresholdReachedOffsetMs", reachedAt is { } at ? Number(at) : "unknown"),
                    ])));
        }

        return events;
    }

    public static IReadOnlyList<EventDraft> StoppedVehicle(EventDerivationInput input, long minimumStationaryMs)
    {
        var restricted = EnabledZones(input)
            .Where(zone => zone.Value.Kind == SceneZoneKind.Restricted)
            .ToDictionary(zone => zone.Key, zone => zone.Value);
        var vehicles = input.Tracks
            .Where(track => track.ObjectClass == ObjectClass.Vehicle)
            .Select(track => track.TrackId)
            .ToHashSet();
        var events = new List<EventDraft>();
        foreach (var interval in input.StationaryIntervals)
        {
            if (!vehicles.Contains(interval.TrackId))
                continue;

            // Inside the zone, not merely somewhere: the overlap of the stationary span
            // with one visit is what is measured against the minimum.
            foreach (var visit in input.Visits.Where(visit => visit.TrackId == interval.TrackId && restricted.ContainsKey(visit.ZoneId)))
            {
                var start = Math.Max(interval.StartOffsetMs, visit.EntryOffsetMs);
                var end = Math.Min(interval.EndOffsetMs, visit.ExitOffsetMs);
                if (end - start < minimumStationaryMs)
                    continue;

                var vehicle = nameof(ObjectClass.Vehicle);
                events.Add(new EventDraft(
                    interval.TrackId.ToString("D") + "/" + Number(interval.IntervalIndex) + "/" + visit.VisitId.ToString("D"),
                    interval.TrackId,
                    vehicle,
                    visit.ZoneId,
                    LineId: null,
                    Direction: null,
                    start,
                    end,
                    new EventProvenance(
                        [new EventParticipant(interval.TrackId, SubjectRole, vehicle)],
                        [
                            new EventInputReference(
                                "stationaryInterval",
                                interval.TrackId.ToString("D") + "#" + Number(interval.IntervalIndex),
                                interval.StartOffsetMs,
                                interval.EndOffsetMs),
                            Visit(visit),
                        ],
                        [
                            new EventAppliedParameter(
                                "minimumStationarySeconds",
                                Number(minimumStationaryMs / 1000),
                                "s",
                                RuleParameterSource.OwnerDecision,
                                "S2 admissibility record §9, owner decision 10"),
                            new EventAppliedParameter("zoneKind", nameof(SceneZoneKind.Restricted), null, RuleParameterSource.Catalogue, "ADR-025 §2"),
                        ],
                        [new EventDetail("stationaryInZoneMs", Number(end - start))])));
            }
        }

        return events;
    }

    public static IReadOnlyList<EventDraft> WrongWay(EventDerivationInput input)
    {
        var lines = EnabledLines(input);
        var classes = Classes(input);
        var events = new List<EventDraft>();
        foreach (var crossing in input.Crossings)
        {
            if (!lines.TryGetValue(crossing.LineId, out var line) || line.PermittedDirection is not { } permitted ||
                string.Equals(permitted, crossing.Direction, StringComparison.Ordinal) ||
                !classes.TryGetValue(crossing.TrackId, out var objectClass))
                continue;

            events.Add(new EventDraft(
                crossing.CrossingId.ToString("D"),
                crossing.TrackId,
                objectClass,
                ZoneId: null,
                line.LineId,
                crossing.Direction,
                crossing.OffsetMs,
                crossing.OffsetMs,
                new EventProvenance(
                    [new EventParticipant(crossing.TrackId, SubjectRole, objectClass)],
                    [Crossing(crossing)],
                    [
                        new EventAppliedParameter(
                            "permittedDirection",
                            permitted,
                            null,
                            RuleParameterSource.SceneRevision,
                            "trip line permittedDirection at the unit's revision"),
                    ],
                    [
                        new EventDetail("directionLabel", DirectionLabel(line, crossing.Direction)),
                        new EventDetail("permittedLabel", DirectionLabel(line, permitted)),
                    ]),
                crossing.TimestampUtc));
        }

        return events;
    }

    public static IReadOnlyList<EventDraft> CoOccurrence(EventDerivationInput input)
    {
        var zones = EnabledZones(input);
        var classes = input.Tracks.ToDictionary(track => track.TrackId, track => track.ObjectClass);
        var events = new List<EventDraft>();
        foreach (var zone in zones.Values.OrderBy(zone => zone.ZoneId))
        {
            var visits = input.Visits
                .Where(visit => visit.ZoneId == zone.ZoneId && visit.ExitOffsetMs > visit.EntryOffsetMs &&
                                classes.ContainsKey(visit.TrackId))
                .ToList();
            if (visits.Count == 0)
                continue;

            // Elementary segments between consecutive visit boundaries. Inside one
            // segment the set of Tracks present is constant, so the condition "a Person
            // and a Vehicle are both inside" is decided per segment and episodes are the
            // maximal runs of segments where it holds. Only positive-length overlap counts.
            var boundaries = visits
                .SelectMany(visit => new[] { visit.EntryOffsetMs, visit.ExitOffsetMs })
                .Distinct()
                .Order()
                .ToList();

            long? episodeStart = null;
            long episodeEnd = 0;
            var episodeVisits = new HashSet<EventZoneVisit>();

            void Close()
            {
                if (episodeStart is not { } start)
                    return;
                events.Add(Episode(zone, start, episodeEnd, episodeVisits, classes));
                episodeStart = null;
                episodeVisits = [];
            }

            for (var index = 0; index + 1 < boundaries.Count; index++)
            {
                var from = boundaries[index];
                var to = boundaries[index + 1];
                var present = visits.Where(visit => visit.EntryOffsetMs <= from && visit.ExitOffsetMs >= to).ToList();
                var together = present.Any(visit => classes[visit.TrackId] == ObjectClass.Person) &&
                               present.Any(visit => classes[visit.TrackId] == ObjectClass.Vehicle);
                if (!together)
                {
                    Close();
                    continue;
                }

                episodeStart ??= from;
                episodeEnd = to;
                episodeVisits.UnionWith(present);
            }

            Close();
        }

        return events;
    }

    public static IReadOnlyList<EventDraft> RepeatedVisit(EventDerivationInput input, int minimumDistinctTracks)
    {
        var zones = EnabledZones(input);
        var tracks = input.Tracks.Where(track => track.EntityId is not null).ToDictionary(track => track.TrackId);
        var events = new List<EventDraft>();
        var groups = input.Visits
            .Where(visit => zones.ContainsKey(visit.ZoneId) && tracks.ContainsKey(visit.TrackId))
            .GroupBy(visit => (EntityId: tracks[visit.TrackId].EntityId!.Value, visit.ZoneId))
            .OrderBy(group => group.Key.EntityId)
            .ThenBy(group => group.Key.ZoneId);
        foreach (var group in groups)
        {
            var visits = group.OrderBy(visit => visit.EntryOffsetMs).ThenBy(visit => visit.TrackId).ToList();
            var distinctTracks = visits.Select(visit => visit.TrackId).Distinct().ToList();
            if (distinctTracks.Count < minimumDistinctTracks)
                continue;

            events.Add(new EventDraft(
                group.Key.EntityId.ToString("D") + "/" + group.Key.ZoneId.ToString("D"),
                PrimaryTrackId: null,
                ObjectClass: tracks[distinctTracks[0]].ObjectClass.ToString(),
                group.Key.ZoneId,
                LineId: null,
                Direction: null,
                visits[0].EntryOffsetMs,
                visits.Max(visit => visit.ExitOffsetMs),
                new EventProvenance(
                    [.. distinctTracks.Order().Select(trackId => new EventParticipant(trackId, ParticipantRole, tracks[trackId].ObjectClass.ToString()))],
                    [.. visits.Select(Visit)],
                    [
                        new EventAppliedParameter(
                            "minimumDistinctTracks", Number(minimumDistinctTracks), null, RuleParameterSource.Catalogue, "ADR-025 §2"),
                    ],
                    [
                        new EventDetail("entityId", group.Key.EntityId.ToString("D")),
                        new EventDetail("distinctTracks", Number(distinctTracks.Count)),
                    ])));
        }

        return events;
    }

    private static EventDraft Episode(
        EventZone zone,
        long start,
        long end,
        IEnumerable<EventZoneVisit> visits,
        Dictionary<Guid, ObjectClass> classes)
    {
        var ordered = visits.OrderBy(visit => visit.TrackId).ThenBy(visit => visit.VisitIndex).ToList();
        var participants = ordered
            .Select(visit => visit.TrackId)
            .Distinct()
            .Select(trackId => new EventParticipant(trackId, ParticipantRole, classes[trackId].ToString()))
            .ToList();
        return new EventDraft(
            zone.ZoneId.ToString("D") + "/" + Number(start),
            PrimaryTrackId: null,
            ObjectClass: null,
            zone.ZoneId,
            LineId: null,
            Direction: null,
            start,
            end,
            new EventProvenance(
                participants,
                [.. ordered.Select(Visit)],
                [
                    new EventAppliedParameter("classes", "Person+Vehicle", null, RuleParameterSource.Catalogue, "ADR-025 §2"),
                    new EventAppliedParameter("minimumOverlapMs", "0 (exclusive)", "ms", RuleParameterSource.Catalogue, "ADR-025 §2"),
                ],
                [
                    new EventDetail("persons", Number(participants.Count(participant => participant.ObjectClass == nameof(ObjectClass.Person)))),
                    new EventDetail("vehicles", Number(participants.Count(participant => participant.ObjectClass == nameof(ObjectClass.Vehicle)))),
                ]));
    }

    private static Dictionary<Guid, EventZone> EnabledZones(EventDerivationInput input) =>
        input.Zones.Where(zone => zone.Enabled).ToDictionary(zone => zone.ZoneId);

    private static Dictionary<Guid, EventLine> EnabledLines(EventDerivationInput input) =>
        input.Lines.Where(line => line.Enabled).ToDictionary(line => line.LineId);

    private static Dictionary<Guid, string> Classes(EventDerivationInput input) =>
        input.Tracks.ToDictionary(track => track.TrackId, track => track.ObjectClass.ToString());

    private static EventInputReference Crossing(EventLineCrossing crossing) =>
        new("lineCrossing", crossing.CrossingId.ToString("D"), crossing.OffsetMs, crossing.OffsetMs);

    private static EventInputReference Visit(EventZoneVisit visit) =>
        new("zoneVisit", visit.VisitId.ToString("D"), visit.EntryOffsetMs, visit.ExitOffsetMs);

    private static string DirectionLabel(EventLine line, string direction) =>
        direction == TripLine.PermittedDirectionAToB ? line.AToBLabel : line.BToALabel;

    private static string Number(long value) => value.ToString(CultureInfo.InvariantCulture);
}
