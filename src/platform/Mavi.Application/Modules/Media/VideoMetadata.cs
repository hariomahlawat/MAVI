namespace Mavi.Application.Modules.Media;

public sealed record VideoMetadata(
    long DurationMs,
    int Width,
    int Height,
    int FrameRateNumerator,
    int FrameRateDenominator,
    string CodecName,
    string FormatName,
    string? MajorBrand = null);

public sealed class VideoMetadataException(string message, Exception? innerException = null)
    : Exception(message, innerException);
