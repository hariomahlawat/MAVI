using Mavi.Domain.Common;

namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// Per-Track motion diagnostics for one analysis unit.
/// </summary>
/// <remarks>
/// Every quantity is in normalised image units. Nothing here is a physical speed or
/// distance and none of it may be presented as one; §N defers physical calibration.
/// </remarks>
public sealed class TrackMotionSummary
{
    private readonly List<StationaryInterval> _stationaryIntervals = [];
    private readonly List<Guid> _stationaryZoneIds = [];

    private TrackMotionSummary() { }

    public static TrackMotionSummary Create(
        Guid analysisId,
        Guid trackId,
        string heading,
        double pathLengthNormalised,
        double meanDisplacementRate,
        long longestStationaryMs,
        long totalStationaryMs,
        IReadOnlyList<StationaryInterval> stationaryIntervals,
        IReadOnlyList<Guid> stationaryZoneIds)
    {
        ArgumentNullException.ThrowIfNull(stationaryIntervals);
        ArgumentNullException.ThrowIfNull(stationaryZoneIds);
        if (analysisId == Guid.Empty || trackId == Guid.Empty) throw Invalid();
        if (!SceneAnalyticsVocabulary.IsHeading(heading)) throw Invalid();
        if (!double.IsFinite(pathLengthNormalised) || pathLengthNormalised < 0) throw Invalid();
        if (!double.IsFinite(meanDisplacementRate) || meanDisplacementRate < 0) throw Invalid();
        if (longestStationaryMs < 0 || totalStationaryMs < 0) throw Invalid();
        if (longestStationaryMs > totalStationaryMs) throw Invalid();

        foreach (var interval in stationaryIntervals)
        {
            if (interval.StartOffsetMs < 0 || interval.EndOffsetMs < interval.StartOffsetMs) throw Invalid();
        }

        var summary = new TrackMotionSummary
        {
            AnalysisId = analysisId,
            TrackId = trackId,
            Heading = heading,
            PathLengthNormalised = pathLengthNormalised,
            MeanDisplacementRate = meanDisplacementRate,
            LongestStationaryMs = longestStationaryMs,
            TotalStationaryMs = totalStationaryMs
        };
        summary._stationaryIntervals.AddRange(stationaryIntervals);
        summary._stationaryZoneIds.AddRange(stationaryZoneIds);
        return summary;
    }

    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public string Heading { get; private set; } = string.Empty;
    public double PathLengthNormalised { get; private set; }

    /// <summary>Mean displacement per second in normalised image units.</summary>
    public double MeanDisplacementRate { get; private set; }

    public long LongestStationaryMs { get; private set; }
    public long TotalStationaryMs { get; private set; }

    public IReadOnlyList<StationaryInterval> StationaryIntervals => _stationaryIntervals;

    /// <summary>Zones the Track was stationary inside, for evidence display.</summary>
    public IReadOnlyList<Guid> StationaryZoneIds => _stationaryZoneIds;

    private static DomainValidationException Invalid() =>
        new(SceneAnalyticsErrorCodes.TransitionInvalid, "The track motion summary is invalid.");
}
