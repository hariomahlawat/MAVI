namespace Mavi.Infrastructure.Storage;

public sealed class MediaStorageOptions
{
    public const string SectionName = "MediaStorage";
    public string RootPath { get; set; } = string.Empty;
}
