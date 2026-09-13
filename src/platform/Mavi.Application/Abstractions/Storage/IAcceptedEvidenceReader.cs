namespace Mavi.Application.Abstractions.Storage;

public interface IAcceptedEvidenceReader
{
    Task<Stream> OpenReadAsync(
        string acceptedStorageKey,
        CancellationToken cancellationToken);
}
