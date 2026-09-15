namespace Mavi.Infrastructure.Media;

public sealed class MediaProcessingOptions
{
    public const string SectionName = "MediaProcessing";

    public string FfprobePath { get; init; } = "ffprobe";
    public string FfmpegPath { get; init; } = "ffmpeg";
    public string BundledRootPath { get; init; } = "tools/ffmpeg";
    public string BundledManifestPath { get; init; } = "tools/ffmpeg/manifest.json";
    public bool VerifyOnStartup { get; init; } = true;
    public bool RequireBundledTools { get; init; } = true;
    public bool AllowPathFallbackInDevelopment { get; init; }
    public int ProbeTimeoutSeconds { get; init; } = 30;
}
