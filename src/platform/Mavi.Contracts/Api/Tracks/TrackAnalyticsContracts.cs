namespace Mavi.Contracts.Api.Tracks;

// Analytics on the Track surfaces (plan §S "Response contracts", frozen for
// Slice 4). Two shapes, deliberately different in size:
//
// - a search item carries a *bounded explanation* for the identity the search
//   pinned: which zones and lines matched and the one motion summary. Never the
//   visit or crossing history — a page of fifty rows must not become fifty fact
//   dumps.
// - the detail carries the *full facts* for one identity, mirroring the persisted
//   fact families rather than inventing a generic event bag, plus compact
//   summaries of the other identities that analysed the same Track.
//
// Internal analysis ids are not operator-facing and appear in neither. Crossing
// directions are the wire vocabulary (`aToB`/`bToA`), mapped from storage once.

// --- Search item ----------------------------------------------------------

/// <summary>Why this Track matched, against the identity the search pinned.</summary>
public sealed record TrackItemAnalyticsResponse(
    Guid SceneRevisionId,
    string AlgorithmVersion,
    IReadOnlyList<TrackItemZoneAnalyticsResponse> Zones,
    IReadOnlyList<TrackItemLineAnalyticsResponse> Lines,
    TrackItemMotionAnalyticsResponse? Motion);

public sealed record TrackItemZoneAnalyticsResponse(
    Guid ZoneId,
    int VisitCount,
    long TotalDwellMs,
    bool Loitering);

/// <summary>
/// One matched line. <paramref name="FirstMatchedCrossingUtc"/> is the only time a
/// row carries: the operator gets a moment to look at, and the complete crossing
/// list belongs to the detail.
/// </summary>
public sealed record TrackItemLineAnalyticsResponse(
    Guid LineId,
    int CrossingCount,
    string? MatchedDirection,
    DateTimeOffset? FirstMatchedCrossingUtc);

public sealed record TrackItemMotionAnalyticsResponse(
    string Heading,
    long LongestStationaryMs);

// --- Detail ---------------------------------------------------------------

/// <summary>
/// Everything analytics knows about one Track for one identity.
/// </summary>
/// <remarks>
/// <para>
/// <paramref name="Status"/> is one of
/// <see cref="TrackSearchContractRules.TrackAnalyticsStatusValues"/>. Only
/// <c>Analysed</c> carries facts; <c>Unavailable</c> carries the reason instead; the
/// remaining values describe the run's unit for this identity and carry neither.
/// </para>
/// <para>
/// The identity is the one the caller asked for, or the camera's active revision and
/// current engine when they asked for none. It is never silently substituted: a Track
/// opened from a historical search is reported against that history, and
/// <paramref name="SceneRevisionId"/> is null only for a camera that has never been
/// configured.
/// </para>
/// </remarks>
public sealed record TrackDetailAnalyticsResponse(
    Guid? SceneRevisionId,
    int? SceneRevisionNumber,
    string AlgorithmVersion,
    string Status,
    string? UnavailableReason,
    string? ReferencePoint,
    int? SampleCount,
    int? GapCount,
    long? GapTotalMs,
    IReadOnlyList<TrackDetailZoneSummaryResponse> ZoneSummaries,
    IReadOnlyList<TrackDetailZoneVisitResponse> ZoneVisits,
    IReadOnlyList<TrackDetailLineCrossingResponse> LineCrossings,
    TrackDetailMotionSummaryResponse? Motion,
    IReadOnlyList<TrackAnalyticsIdentitySummaryResponse> OtherIdentities);

public sealed record TrackDetailZoneSummaryResponse(
    Guid ZoneId,
    int VisitCount,
    long TotalDwellMs,
    DateTimeOffset? FirstEntryTimestampUtc,
    DateTimeOffset? LastExitTimestampUtc,
    bool Loitering,
    int LoiteringThresholdSeconds,
    long LoiteringDwellMs);

public sealed record TrackDetailZoneVisitResponse(
    Guid ZoneId,
    int VisitIndex,
    long EntryOffsetMs,
    long ExitOffsetMs,
    DateTimeOffset EntryTimestampUtc,
    DateTimeOffset ExitTimestampUtc,
    long DwellMs,
    bool BeganInside,
    bool EndedInside,
    bool ClosedByGap,
    string EntryHeading,
    string ExitHeading);

public sealed record TrackDetailLineCrossingResponse(
    Guid LineId,
    int CrossingIndex,
    long OffsetMs,
    DateTimeOffset TimestampUtc,
    string Direction,
    double PointX,
    double PointY);

/// <summary>Motion diagnostics in normalised image units; nothing here is a physical speed.</summary>
public sealed record TrackDetailMotionSummaryResponse(
    string Heading,
    double PathLengthNormalised,
    double MeanDisplacementRate,
    long LongestStationaryMs,
    long TotalStationaryMs,
    IReadOnlyList<TrackStationaryIntervalResponse> StationaryIntervals,
    IReadOnlyList<Guid> StationaryZoneIds);

public sealed record TrackStationaryIntervalResponse(long StartOffsetMs, long EndOffsetMs);

/// <summary>
/// Another identity that produced facts for this Track, so the operator can see that a
/// different revision or engine also looked at it without loading its facts.
/// </summary>
public sealed record TrackAnalyticsIdentitySummaryResponse(
    Guid SceneRevisionId,
    int SceneRevisionNumber,
    string AlgorithmVersion,
    string UnitStatus,
    string Outcome);
