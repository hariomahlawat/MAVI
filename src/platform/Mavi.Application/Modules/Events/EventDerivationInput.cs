using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;

namespace Mavi.Application.Modules.Events;

// The complete, persisted input of one derivation: one fact-bearing scene analysis
// unit's facts, the classes of its analysed Tracks and the unit's own revision
// geometry (ADR-025 §1). Nothing here is read from a trajectory, a model or the
// host's clock, which is what makes a derivation reproducible from the database.

public sealed record EventUnitIdentity(
    Guid SceneAnalysisId,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    Guid SceneRevisionId,
    int SceneRevisionNumber,
    string AnalyticsAlgorithmVersion,
    DateTimeOffset RecordingStartUtc);

public sealed record EventZone(Guid ZoneId, string Name, SceneZoneKind Kind, bool Enabled);

public sealed record EventLine(
    Guid LineId,
    string Name,
    bool Enabled,
    string AToBLabel,
    string BToALabel,
    string? PermittedDirection);

/// <summary>An analysed Track of the unit. <see cref="EntityId"/> is only ever set by confirmation (S7).</summary>
public sealed record EventTrack(Guid TrackId, ObjectClass ObjectClass, Guid? EntityId);

public sealed record EventZoneVisit(
    Guid VisitId,
    Guid TrackId,
    Guid ZoneId,
    int VisitIndex,
    long EntryOffsetMs,
    long ExitOffsetMs,
    long DwellMs);

public sealed record EventZoneSummary(
    Guid TrackId,
    Guid ZoneId,
    int VisitCount,
    long TotalDwellMs,
    bool Loitering,
    int LoiteringThresholdSeconds);

public sealed record EventLineCrossing(
    Guid CrossingId,
    Guid TrackId,
    Guid LineId,
    int CrossingIndex,
    long OffsetMs,
    string Direction,
    DateTimeOffset TimestampUtc);

public sealed record EventStationaryInterval(Guid TrackId, int IntervalIndex, long StartOffsetMs, long EndOffsetMs);

public sealed record EventDerivationInput(
    EventUnitIdentity Unit,
    IReadOnlyList<EventZone> Zones,
    IReadOnlyList<EventLine> Lines,
    IReadOnlyList<EventTrack> Tracks,
    IReadOnlyList<EventZoneVisit> Visits,
    IReadOnlyList<EventZoneSummary> Summaries,
    IReadOnlyList<EventLineCrossing> Crossings,
    IReadOnlyList<EventStationaryInterval> StationaryIntervals)
{
    /// <summary>
    /// The same input with every list in one canonical order, so that rule output and
    /// digests never depend on the order a database happened to return rows in.
    /// </summary>
    public EventDerivationInput Canonical() => this with
    {
        Zones = [.. Zones.OrderBy(zone => zone.ZoneId)],
        Lines = [.. Lines.OrderBy(line => line.LineId)],
        Tracks = [.. Tracks.OrderBy(track => track.TrackId)],
        Visits = [.. Visits.OrderBy(visit => visit.TrackId).ThenBy(visit => visit.ZoneId).ThenBy(visit => visit.VisitIndex)],
        Summaries = [.. Summaries.OrderBy(summary => summary.TrackId).ThenBy(summary => summary.ZoneId)],
        // A crossing index is numbered per (Track, line), so the line is part of the key.
        Crossings = [.. Crossings.OrderBy(crossing => crossing.TrackId).ThenBy(crossing => crossing.LineId).ThenBy(crossing => crossing.CrossingIndex)],
        StationaryIntervals = [.. StationaryIntervals.OrderBy(interval => interval.TrackId).ThenBy(interval => interval.IntervalIndex)],
    };
}
