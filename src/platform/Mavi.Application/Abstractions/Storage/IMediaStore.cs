namespace Mavi.Application.Abstractions.Storage;

public sealed record MediaWriteResult(long SizeBytes, string Sha256);

public interface IMediaStore
{
    Task<MediaWriteResult> WriteAsync(string storageKey, Stream content, CancellationToken cancellationToken);
    Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken);
    Task<bool> ExistsAsync(string storageKey, CancellationToken cancellationToken);
    Task DeleteAsync(string storageKey, CancellationToken cancellationToken);
}
