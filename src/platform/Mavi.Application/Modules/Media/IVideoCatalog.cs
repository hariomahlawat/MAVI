using Mavi.Domain.Media;

namespace Mavi.Application.Modules.Media;

public interface IVideoCatalog
{
    Task<VideoAsset?> GetAsync(Guid id, CancellationToken cancellationToken);
    Task<IReadOnlyList<VideoAsset>> ListAsync(CancellationToken cancellationToken);
    Task<VideoAsset?> FindSourceVideoBySha256Async(string sha256, CancellationToken cancellationToken);
    Task AddAsync(Artifact artifact, VideoAsset video, CancellationToken cancellationToken);
    Task SaveChangesAsync(CancellationToken cancellationToken);
}

public sealed class DuplicateSourceVideoException(Exception innerException)
    : Exception("The source video has already been imported.", innerException);
