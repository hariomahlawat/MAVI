namespace Mavi.Contracts.Api.Videos;

public sealed record VideoAssetResponse(
    Guid Id,
    Guid CameraId,
    string OriginalFileName,
    DateTimeOffset RecordingStartUtc,
    DateTimeOffset RecordingEndUtc,
    long DurationMs,
    int Width,
    int Height,
    int FrameRateNumerator,
    int FrameRateDenominator,
    string? CodecName,
    string ProcessingStatus,
    DateTimeOffset ImportedAtUtc);
