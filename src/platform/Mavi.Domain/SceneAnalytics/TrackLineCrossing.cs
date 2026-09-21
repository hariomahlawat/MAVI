using Mavi.Domain.Common;

namespace Mavi.Domain.SceneAnalytics;

/// <summary>One confirmed crossing of one trip line by one Track in one analysis unit.</summary>
public sealed class TrackLineCrossing
{
    private TrackLineCrossing() { }

    public static TrackLineCrossing Create(
        Guid analysisId,
        Guid trackId,
        Guid lineId,
        int crossingIndex,
        long offsetMs,
        DateTimeOffset timestampUtc,
        string direction,
        double pointX,
        double pointY)
    {
        if (analysisId == Guid.Empty || trackId == Guid.Empty || lineId == Guid.Empty) throw Invalid();
        if (crossingIndex < 0 || offsetMs < 0) throw Invalid();
        if (!SceneAnalyticsVocabulary.IsCrossingDirection(direction)) throw Invalid();
        if (!IsNormalised(pointX) || !IsNormalised(pointY)) throw Invalid();

        return new TrackLineCrossing
        {
            Id = Guid.CreateVersion7(),
            AnalysisId = analysisId,
            TrackId = trackId,
            LineId = lineId,
            CrossingIndex = crossingIndex,
            OffsetMs = offsetMs,
            TimestampUtc = timestampUtc.ToUniversalTime(),
            Direction = direction,
            PointX = pointX,
            PointY = pointY
        };
    }

    public Guid Id { get; private set; }
    public Guid AnalysisId { get; private set; }
    public Guid TrackId { get; private set; }
    public Guid LineId { get; private set; }
    public int CrossingIndex { get; private set; }
    public long OffsetMs { get; private set; }
    public DateTimeOffset TimestampUtc { get; private set; }
    public string Direction { get; private set; } = string.Empty;
    public double PointX { get; private set; }
    public double PointY { get; private set; }

    private static bool IsNormalised(double value) => double.IsFinite(value) && value is >= 0 and <= 1;

    private static DomainValidationException Invalid() =>
        new(SceneAnalyticsErrorCodes.TransitionInvalid, "The track line crossing is invalid.");
}
