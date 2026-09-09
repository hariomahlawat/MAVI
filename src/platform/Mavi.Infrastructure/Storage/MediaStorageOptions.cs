namespace Mavi.Infrastructure.Storage;

public sealed class MediaStorageOptions
{
    public const string SectionName = "MediaStorage";
    public string RootPath { get; init; } = string.Empty;
}
