namespace Mavi.Contracts.Api.Tracks;

public sealed record TrackDetailResponse(
    Guid Id,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    TrackCameraResponse Camera,
    string ObjectClass,
    int LocalTrackNumber,
    long StartOffsetMs,
    long EndOffsetMs,
    DateTimeOffset StartTimestampUtc,
    DateTimeOffset EndTimestampUtc,
    long DurationMs,
    int DetectionCount,
    double MeanConfidence,
    double MaxConfidence,
    string ReviewStatus,
    TrackProcessingResponse Processing,
    TrackVideoResponse Video,
    TrackRepresentativeResponse? Representative,
    Guid? TrajectoryArtifactId,
    string? TrajectoryContentUrl);

public sealed record TrackCameraResponse(Guid Id, string Code, string Name);

public sealed record TrackProcessingResponse(
    string PipelineVersion,
    string? DetectorName,
    string? DetectorVersion,
    string? TrackerName,
    string? TrackerVersion,
    DateTimeOffset? CompletedAtUtc);

public sealed record TrackVideoResponse(
    DateTimeOffset RecordingStartUtc,
    DateTimeOffset RecordingEndUtc,
    long DurationMs,
    int Width,
    int Height,
    int FrameRateNumerator,
    int FrameRateDenominator,
    string VideoContentUrl);

public sealed record TrackRepresentativeResponse(
    Guid ObservationId,
    long SourceFrameNumber,
    long VideoOffsetMs,
    DateTimeOffset TimestampUtc,
    double Confidence,
    double QualityScore,
    TrackBoundingBoxResponse BoundingBox,
    Guid? ThumbnailArtifactId,
    string? ThumbnailContentUrl);

public sealed record TrackBoundingBoxResponse(float X, float Y, float Width, float Height);
