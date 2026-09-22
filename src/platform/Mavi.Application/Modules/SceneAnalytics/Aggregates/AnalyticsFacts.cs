using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.SceneAnalytics.Aggregates;

// The minimal projections the aggregate arithmetic needs. Deliberately narrow: the
// repository selects these columns and nothing else, and the counting rules below
// can be exercised without a database.

/// <summary>One persisted zone visit, as the aggregate reads it.</summary>
public readonly record struct ZoneVisitFact(
    Guid TrackId,
    Guid ZoneId,
    DateTimeOffset EntryUtc,
    DateTimeOffset ExitUtc,
    bool BeganInside,
    bool EndedInside);

/// <summary>One persisted line crossing.</summary>
public readonly record struct LineCrossingFact(
    Guid LineId,
    DateTimeOffset TimestampUtc,
    bool IsAToB);

/// <summary>
/// One persisted per-Track zone summary, for the whole-Track repeated-visit metric.
/// </summary>
public readonly record struct ZoneSummaryFact(Guid TrackId, Guid ZoneId, int VisitCount);

/// <summary>One analysed Track's interval and class, for the class-count series.</summary>
public readonly record struct TrackIntervalFact(
    Guid TrackId,
    ObjectClass ObjectClass,
    DateTimeOffset StartUtc,
    DateTimeOffset EndUtc);

/// <summary>A zone enabled in the resolved revision. Disabled geometry never reaches here.</summary>
public readonly record struct EnabledZone(Guid ZoneId, string Name);

/// <summary>A trip line enabled in the resolved revision.</summary>
public readonly record struct EnabledLine(Guid LineId, string Name, string AToBLabel, string BToALabel);

/// <summary>Everything the aggregate arithmetic runs over, for one resolved identity.</summary>
public sealed record AnalyticsFactSet(
    IReadOnlyList<EnabledZone> Zones,
    IReadOnlyList<EnabledLine> Lines,
    IReadOnlyList<ZoneVisitFact> ZoneVisits,
    IReadOnlyList<LineCrossingFact> LineCrossings,
    IReadOnlyList<ZoneSummaryFact> ZoneSummaries,
    IReadOnlyList<TrackIntervalFact> TrackIntervals)
{
    public static AnalyticsFactSet Empty { get; } = new([], [], [], [], [], []);
}
