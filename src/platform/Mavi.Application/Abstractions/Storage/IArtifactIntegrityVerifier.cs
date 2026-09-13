namespace Mavi.Application.Abstractions.Storage;

public enum ArtifactIntegrityStatus
{
    Valid,
    Missing,
    Mismatch,
}

public sealed record ArtifactIntegrityVerification(
    ArtifactIntegrityStatus Status,
    long? ActualSizeBytes = null,
    string? ActualSha256 = null);

public interface IArtifactIntegrityVerifier
{
    Task<ArtifactIntegrityVerification> VerifyAsync(
        string storageKey,
        long expectedSizeBytes,
        string expectedSha256,
        CancellationToken cancellationToken);
}
