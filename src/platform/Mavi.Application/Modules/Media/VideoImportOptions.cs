namespace Mavi.Application.Modules.Media;

public sealed class VideoImportOptions
{
    public const string SectionName = "VideoImport";
    public long MaximumFileSizeBytes { get; init; } = 10L * 1024 * 1024 * 1024;
    public string[] AllowedExtensions { get; init; } = [".mp4"];
}
