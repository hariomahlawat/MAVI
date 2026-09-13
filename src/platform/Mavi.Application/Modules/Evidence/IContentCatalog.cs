namespace Mavi.Application.Modules.Evidence;

public interface IContentCatalog
{
    Task<ContentDescriptor?> GetVideoContentAsync(
        Guid videoAssetId,
        CancellationToken cancellationToken);

    Task<ContentDescriptor?> GetEvidenceContentAsync(
        Guid artifactId,
        CancellationToken cancellationToken);
}
