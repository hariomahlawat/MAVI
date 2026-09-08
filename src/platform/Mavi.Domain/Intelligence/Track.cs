using Mavi.Domain.Common;

namespace Mavi.Domain.Intelligence;

public sealed class Track
{
    // Construction
    private Track() { }

    public static Track Create(Guid processingRunId, Guid videoAssetId, int localTrackNumber, ObjectClass objectClass,
        long startOffsetMs, long endOffsetMs, DateTimeOffset recordingStartUtc, int detectionCount,
        double meanConfidence, double maxConfidence)
    {
        if (processingRunId == Guid.Empty || videoAssetId == Guid.Empty || localTrackNumber < 0 || startOffsetMs < 0 || endOffsetMs < startOffsetMs || detectionCount <= 0)
            throw Invalid();
        if (!InRange(meanConfidence) || !InRange(maxConfidence) || maxConfidence < meanConfidence) throw Invalid();
        var start = recordingStartUtc.ToUniversalTime();
        return new Track
        {
            Id = Guid.CreateVersion7(), ProcessingRunId = processingRunId, VideoAssetId = videoAssetId,
            LocalTrackNumber = localTrackNumber, ObjectClass = objectClass, StartOffsetMs = startOffsetMs,
            EndOffsetMs = endOffsetMs, StartTimestampUtc = start.AddMilliseconds(startOffsetMs),
            EndTimestampUtc = start.AddMilliseconds(endOffsetMs), DurationMs = endOffsetMs - startOffsetMs,
            DetectionCount = detectionCount, MeanConfidence = meanConfidence, MaxConfidence = maxConfidence,
            ReviewStatus = ReviewStatus.Unreviewed, CreatedAtUtc = DateTimeOffset.UtcNow,
        };
    }

    // Properties
    public Guid Id { get; private set; }
    public Guid ProcessingRunId { get; private set; }
    public Guid VideoAssetId { get; private set; }
    public Guid? EntityId { get; private set; }
    public int LocalTrackNumber { get; private set; }
    public ObjectClass ObjectClass { get; private set; }
    public long StartOffsetMs { get; private set; }
    public long EndOffsetMs { get; private set; }
    public DateTimeOffset StartTimestampUtc { get; private set; }
    public DateTimeOffset EndTimestampUtc { get; private set; }
    public long DurationMs { get; private set; }
    public int DetectionCount { get; private set; }
    public double MeanConfidence { get; private set; }
    public double MaxConfidence { get; private set; }
    public Guid? RepresentativeObservationId { get; private set; }
    public Guid? TrajectoryArtifactId { get; private set; }
    public ReviewStatus ReviewStatus { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }

    private static bool InRange(double value) => double.IsFinite(value) && value is >= 0 and <= 1;
    private static DomainValidationException Invalid() => new("track_invalid", "The track data is invalid.");
}
