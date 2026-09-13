namespace Mavi.Application.Abstractions.Storage;

public enum AcceptedEvidenceSealStatus
{
    Sealed,
    Missing,
    IntegrityMismatch,
    DestinationConflict,
}

public sealed record AcceptedEvidenceSealResult(
    AcceptedEvidenceSealStatus Status,
    string? StorageKey = null,
    long? SizeBytes = null,
    string? Sha256 = null);

public interface IAcceptedEvidenceStore
{
    Task<AcceptedEvidenceSealResult> SealAsync(
        string sourceStorageKey,
        string acceptedStorageKey,
        long expectedSizeBytes,
        string expectedSha256,
        CancellationToken cancellationToken);
}
