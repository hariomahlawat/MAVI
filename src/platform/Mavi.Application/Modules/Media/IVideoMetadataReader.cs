namespace Mavi.Application.Modules.Media;

public interface IVideoMetadataReader
{
    Task<VideoMetadata> ReadAsync(string storageKey, CancellationToken cancellationToken);
}
