namespace Mavi.Contracts.Api.Tracks;

public sealed record TrackSearchResponse(
    IReadOnlyList<TrackSearchItemResponse> Items,
    string? NextCursor);

public sealed record TrackSearchItemResponse(
    Guid Id,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    string ObjectClass,
    DateTimeOffset StartTimestampUtc,
    DateTimeOffset EndTimestampUtc,
    long StartOffsetMs,
    long EndOffsetMs,
    long DurationMs,
    int DetectionCount,
    double MeanConfidence,
    double MaxConfidence,
    string ReviewStatus,
    Guid? ThumbnailArtifactId,
    string? ThumbnailContentUrl,
    string VideoContentUrl);
