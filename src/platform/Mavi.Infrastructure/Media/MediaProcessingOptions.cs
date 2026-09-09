namespace Mavi.Infrastructure.Media;

public sealed class MediaProcessingOptions
{
    public const string SectionName = "MediaProcessing";
    public string FfprobePath { get; set; } = "ffprobe";
}
