using Mavi.Domain.Common;

namespace Mavi.Domain.SceneAnalytics;

/// <summary>One stay by one Track inside one zone, as computed by one analysis unit.</summary>
/// <remarks>
/// Immutable once written. A visit belongs to its unit, and a unit's facts are
/// replaced wholesale inside that unit's own successful commit rather than edited.
/// </remarks>
public sealed class TrackZoneVisit
{
    private TrackZoneVisit() { }

    public static TrackZoneVisit Create(
        Guid analysisId,
        Guid trackId,
        Guid zoneId,
        int visitIndex,
        long entryOffsetMs,
        long exitOffsetMs,
        DateTimeOffset entryTimestampUtc,
        DateTimeOffset exitTimestampUtc,
        long dwellMs,
        bool beganInside,
        bool endedInside,
        bool closedByGap,
        string entryHeading,
        string exitHeading)
    {
        if (analysisId == Guid.Empty || trackId == Guid.Empty || zoneId == Guid.Empty) throw Invalid();
        if (visitIndex < 0) throw Invalid();
        if (entryOffsetMs < 0 || exitOffsetMs < entryOffsetMs) throw Invalid();
        if (dwellMs < 0) throw Invalid();
        if (exitTimestampUtc < entryTimestampUtc) throw Invalid();
        if (!SceneAnalyticsVocabulary.IsHeading(entryHeading)) throw Invalid();
        if (!SceneAnalyticsVocabulary.IsHeading(exitHeading)) throw Invalid();

        return new TrackZoneVisit
        {
            Id = Guid.CreateVersion7(),
            AnalysisId = analysisId,
            TrackId = trackId,
            ZoneId = zoneId,
            VisitIndex = visitIndex,
            EntryOffsetMs = entryOffsetMs,
            ExitOffsetMs = exitOffsetMs,
            EntryTimestampUtc = entryTimestampUtc.ToUniversalTime(),
            ExitTimestampUtc = exitTimestampUtc.ToUniversalTime(),
            DwellMs = dwellMs,
            BeganInside = beganInside,
            EndedInside = endedInside,
            ClosedByGap = closedByGap,
            EntryHeading = entryHeading,
            ExitHeading = exitHeading
        };
    }

    public Guid Id { get; private set; }
    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public Guid ZoneId { get; private set; }
    public int VisitIndex { get; private set; }
    public long EntryOffsetMs { get; private set; }
    public long ExitOffsetMs { get; private set; }
    public DateTimeOffset EntryTimestampUtc { get; private set; }
    public DateTimeOffset ExitTimestampUtc { get; private set; }
    public long DwellMs { get; private set; }
    public bool BeganInside { get; private set; }
    public bool EndedInside { get; private set; }
    public bool ClosedByGap { get; private set; }
    public string EntryHeading { get; private set; } = string.Empty;
    public string ExitHeading { get; private set; } = string.Empty;

    private static DomainValidationException Invalid() =>
        new(SceneAnalyticsErrorCodes.TransitionInvalid, "The track zone visit is invalid.");
}
