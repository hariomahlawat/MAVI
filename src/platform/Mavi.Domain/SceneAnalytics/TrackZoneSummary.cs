using Mavi.Domain.Common;

namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// Everything one Track did in one zone within one analysis unit, including the
/// loitering verdict. This is the row zone predicates hit.
/// </summary>
public sealed class TrackZoneSummary
{
    private TrackZoneSummary() { }

    public static TrackZoneSummary Create(
        Guid analysisId,
        Guid trackId,
        Guid zoneId,
        int visitCount,
        long totalDwellMs,
        DateTimeOffset? firstEntryTimestampUtc,
        DateTimeOffset? lastExitTimestampUtc,
        bool loitering,
        int loiteringThresholdSeconds,
        long loiteringDwellMs)
    {
        if (analysisId == Guid.Empty || trackId == Guid.Empty || zoneId == Guid.Empty) throw Invalid();
        if (visitCount < 0 || totalDwellMs < 0 || loiteringDwellMs < 0) throw Invalid();
        if (loiteringThresholdSeconds <= 0) throw Invalid();
        if (firstEntryTimestampUtc is { } first && lastExitTimestampUtc is { } last && last < first) throw Invalid();
        // A zone the Track never entered still gets a summary row, so the absence of
        // visits must be representable: no visits means no timestamps.
        if (visitCount == 0 && (firstEntryTimestampUtc is not null || lastExitTimestampUtc is not null)) throw Invalid();

        return new TrackZoneSummary
        {
            AnalysisId = analysisId,
            TrackId = trackId,
            ZoneId = zoneId,
            VisitCount = visitCount,
            TotalDwellMs = totalDwellMs,
            FirstEntryTimestampUtc = firstEntryTimestampUtc?.ToUniversalTime(),
            LastExitTimestampUtc = lastExitTimestampUtc?.ToUniversalTime(),
            Loitering = loitering,
            LoiteringThresholdSeconds = loiteringThresholdSeconds,
            LoiteringDwellMs = loiteringDwellMs
        };
    }

    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public Guid ZoneId { get; private set; }
    public int VisitCount { get; private set; }
    public long TotalDwellMs { get; private set; }
    public DateTimeOffset? FirstEntryTimestampUtc { get; private set; }
    public DateTimeOffset? LastExitTimestampUtc { get; private set; }
    public bool Loitering { get; private set; }
    public int LoiteringThresholdSeconds { get; private set; }
    public long LoiteringDwellMs { get; private set; }

    private static DomainValidationException Invalid() =>
        new(SceneAnalyticsErrorCodes.TransitionInvalid, "The track zone summary is invalid.");
}
