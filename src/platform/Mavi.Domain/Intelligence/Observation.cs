using Mavi.Domain.Common;

namespace Mavi.Domain.Intelligence;

public sealed class Observation
{
    // Construction
    private Observation() { }

    public static Observation Create(Guid trackId, ObservationType observationType, long sourceFrameNumber,
        long videoOffsetMs, DateTimeOffset recordingStartUtc, float x, float y, float width, float height,
        double confidence, double qualityScore)
    {
        if (trackId == Guid.Empty || sourceFrameNumber < 0 || videoOffsetMs < 0 || !BoxValid(x, y, width, height) || !InRange(confidence) || !InRange(qualityScore))
            throw new DomainValidationException("observation_invalid", "The observation data is invalid.");
        return new Observation
        {
            Id = Guid.CreateVersion7(), TrackId = trackId, ObservationType = observationType,
            SourceFrameNumber = sourceFrameNumber, VideoOffsetMs = videoOffsetMs,
            TimestampUtc = recordingStartUtc.ToUniversalTime().AddMilliseconds(videoOffsetMs), BoundingBoxX = x,
            BoundingBoxY = y, BoundingBoxWidth = width, BoundingBoxHeight = height, Confidence = confidence,
            QualityScore = qualityScore, CreatedAtUtc = DateTimeOffset.UtcNow,
        };
    }

    // Properties
    public Guid Id { get; private set; }
    public Guid TrackId { get; private set; }
    public ObservationType ObservationType { get; private set; }
    public long SourceFrameNumber { get; private set; }
    public long VideoOffsetMs { get; private set; }
    public DateTimeOffset TimestampUtc { get; private set; }
    public float BoundingBoxX { get; private set; }
    public float BoundingBoxY { get; private set; }
    public float BoundingBoxWidth { get; private set; }
    public float BoundingBoxHeight { get; private set; }
    public double Confidence { get; private set; }
    public double QualityScore { get; private set; }
    public Guid? ThumbnailArtifactId { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }

    private static bool BoxValid(float x, float y, float width, float height) =>
        float.IsFinite(x) && float.IsFinite(y) && float.IsFinite(width) && float.IsFinite(height) &&
        x >= 0 && y >= 0 && width >= 0 && height >= 0 && x + width <= 1 && y + height <= 1;
    private static bool InRange(double value) => double.IsFinite(value) && value is >= 0 and <= 1;
}
