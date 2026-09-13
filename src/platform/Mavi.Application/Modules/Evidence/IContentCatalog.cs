namespace Mavi.Application.Modules.Evidence;

public interface IContentCatalog
{
    Task<VideoContentLookup> GetVideoContentAsync(
        Guid videoAssetId,
        CancellationToken cancellationToken);

    Task<ContentDescriptor?> GetEvidenceContentAsync(
        Guid artifactId,
        CancellationToken cancellationToken);
}
