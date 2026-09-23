using Mavi.Domain.Common;

namespace Mavi.Domain.Intelligence;

public sealed class Observation
{
    private Observation() { }

    public static Observation Create(
        Guid trackId,
        ObservationType observationType,
        long sourceFrameNumber,
        long videoOffsetMs,
        DateTimeOffset recordingStartUtc,
        float x,
        float y,
        float width,
        float height,
        double confidence,
        double qualityScore,
        int evidenceRank,
        double selectionScore,
        DateTimeOffset? createdAtUtc = null)
    {
        if (trackId == Guid.Empty || sourceFrameNumber < 0 || videoOffsetMs < 0 ||
            !BoxValid(x, y, width, height) || !InRange(confidence) || !InRange(qualityScore) ||
            !InRange(selectionScore) || !Enum.IsDefined(observationType) ||
            evidenceRank is < 0 or > MaximumEvidenceRank ||
            (observationType == ObservationType.Representative) != (evidenceRank == 0))
            throw new DomainValidationException("observation_invalid", "The observation data is invalid.");

        return new Observation
        {
            Id = Guid.CreateVersion7(),
            TrackId = trackId,
            ObservationType = observationType,
            SourceFrameNumber = sourceFrameNumber,
            VideoOffsetMs = videoOffsetMs,
            TimestampUtc = recordingStartUtc.ToUniversalTime().AddMilliseconds(videoOffsetMs),
            BoundingBoxX = x,
            BoundingBoxY = y,
            BoundingBoxWidth = width,
            BoundingBoxHeight = height,
            Confidence = confidence,
            QualityScore = qualityScore,
            EvidenceRank = evidenceRank,
            SelectionScore = selectionScore,
            CreatedAtUtc = (createdAtUtc ?? DateTimeOffset.UtcNow).ToUniversalTime(),
        };
    }

    /// <summary>Highest rank an Evidence Set observation can carry (four roles, ranks 0..3).</summary>
    public const int MaximumEvidenceRank = 3;

    /// <summary>
    /// Attaches the accepted crop (a historical <c>Thumbnail</c> or a v3 <c>EvidenceCrop</c>).
    /// </summary>
    /// <remarks>The column keeps its historical name <c>thumbnail_artifact_id</c>.</remarks>
    public void AttachEvidenceArtifact(Guid artifactId)
    {
        if (artifactId == Guid.Empty || (ThumbnailArtifactId.HasValue && ThumbnailArtifactId.Value != artifactId))
            throw new DomainValidationException("observation_thumbnail_attachment_invalid", "Observation thumbnail attachment is invalid.");
        ThumbnailArtifactId = artifactId;
    }

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
    /// <summary>0 for Representative; 1..3 for the supplemental roles kept, in role order.</summary>
    public int EvidenceRank { get; private set; }
    /// <summary>The selector score admission ordered by; equals QualityScore for historical rows.</summary>
    public double SelectionScore { get; private set; }
    public Guid? ThumbnailArtifactId { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }

    private static bool BoxValid(float x, float y, float width, float height) =>
        float.IsFinite(x) && float.IsFinite(y) && float.IsFinite(width) && float.IsFinite(height) &&
        x >= 0 && y >= 0 && width > 0 && height > 0 && x + width <= 1 && y + height <= 1;

    private static bool InRange(double value) => double.IsFinite(value) && value is >= 0 and <= 1;
}
