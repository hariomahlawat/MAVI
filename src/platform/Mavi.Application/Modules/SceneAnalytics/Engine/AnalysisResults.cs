using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>Eight-way heading in image space, with north meaning decreasing y.</summary>
/// <remarks>This is a screen direction, not a compass bearing, and is never presented as one.</remarks>
public static class AnalysisHeading
{
    public const string None = "None";
    public const string North = "N";
    public const string NorthEast = "NE";
    public const string East = "E";
    public const string SouthEast = "SE";
    public const string South = "S";
    public const string SouthWest = "SW";
    public const string West = "W";
    public const string NorthWest = "NW";
}

/// <summary>Which way a trip line was crossed, relative to its own A and B endpoints.</summary>
public static class CrossingDirection
{
    public const string AToB = "AToB";
    public const string BToA = "BToA";
}

/// <summary>One stay inside one zone.</summary>
public sealed record ZoneVisitFact(
    Guid ZoneId,
    int VisitIndex,
    long EntryOffsetMs,
    long ExitOffsetMs,
    long DwellMs,
    bool BeganInside,
    bool EndedInside,
    bool ClosedByGap,
    string EntryHeading,
    string ExitHeading);

/// <summary>Everything one Track did in one zone, including the loitering verdict.</summary>
public sealed record ZoneSummaryFact(
    Guid ZoneId,
    int VisitCount,
    long TotalDwellMs,
    long FirstEntryOffsetMs,
    long LastExitOffsetMs,
    bool Loitering,
    int LoiteringThresholdSeconds,
    long LoiteringDwellMs,
    IReadOnlyList<int> LoiteringVisitIndexes);

/// <summary>One confirmed crossing of one trip line.</summary>
public sealed record LineCrossingFact(
    Guid LineId,
    int CrossingIndex,
    long OffsetMs,
    string Direction,
    NormalizedPoint Point);

/// <summary>A span during which the Track's smoothed reference point did not move.</summary>
public sealed record StationaryIntervalFact(long StartOffsetMs, long EndOffsetMs)
{
    public long DurationMs => EndOffsetMs - StartOffsetMs;
}

/// <summary>
/// Per-Track motion diagnostics. Every quantity is in normalised image units:
/// nothing here is a physical speed or distance and none of it may be labelled as one.
/// </summary>
public sealed record MotionSummaryFact(
    string Heading,
    double PathLengthNormalised,
    double MeanDisplacementRateNormalisedPerSecond,
    long LongestStationaryMs,
    long TotalStationaryMs,
    IReadOnlyList<StationaryIntervalFact> StationaryIntervals,
    IReadOnlyList<Guid> StationaryZoneIds);

/// <summary>
/// The complete deterministic output for one Track against one scene revision:
/// exactly what a later slice persists, and nothing about how it is stored.
/// </summary>
public sealed record TrackAnalysisResult(
    string ReferencePoint,
    int SampleCount,
    int GapCount,
    long GapTotalMs,
    IReadOnlyList<ZoneVisitFact> ZoneVisits,
    IReadOnlyList<ZoneSummaryFact> ZoneSummaries,
    IReadOnlyList<LineCrossingFact> LineCrossings,
    MotionSummaryFact Motion);
