namespace Mavi.Infrastructure.Media;

public sealed class MediaProcessingOptions
{
    public const string SectionName = "MediaProcessing";
    public string FfprobePath { get; init; } = "ffprobe";
    public string FfmpegPath { get; init; } = "ffmpeg";
    public int ProbeTimeoutSeconds { get; init; } = 30;
}
