using System.Buffers;
using System.Security.Cryptography;
using Mavi.Application.Abstractions.Storage;

namespace Mavi.Infrastructure.Storage;

public sealed class ArtifactIntegrityVerifier(IMediaStore mediaStore) : IArtifactIntegrityVerifier
{
    public async Task<ArtifactIntegrityVerification> VerifyAsync(
        string storageKey,
        long expectedSizeBytes,
        string expectedSha256,
        CancellationToken cancellationToken)
    {
        if (expectedSizeBytes < 0 || !IsCanonicalSha256(expectedSha256))
            throw new ArgumentException("Expected artifact integrity facts are invalid.");

        Stream stream;
        try
        {
            stream = await mediaStore.OpenReadAsync(storageKey, cancellationToken);
        }
        catch (FileNotFoundException)
        {
            return new ArtifactIntegrityVerification(ArtifactIntegrityStatus.Missing);
        }
        catch (DirectoryNotFoundException)
        {
            return new ArtifactIntegrityVerification(ArtifactIntegrityStatus.Missing);
        }

        await using (stream)
        using (var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256))
        {
            var buffer = ArrayPool<byte>.Shared.Rent(81_920);
            long sizeBytes = 0;
            try
            {
                while (true)
                {
                    var count = await stream.ReadAsync(buffer.AsMemory(), cancellationToken);
                    if (count == 0) break;

                    sizeBytes = checked(sizeBytes + count);
                    hash.AppendData(buffer, 0, count);
                }

                var sha256 = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
                return sizeBytes == expectedSizeBytes &&
                       string.Equals(sha256, expectedSha256, StringComparison.Ordinal)
                    ? new ArtifactIntegrityVerification(ArtifactIntegrityStatus.Valid, sizeBytes, sha256)
                    : new ArtifactIntegrityVerification(ArtifactIntegrityStatus.Mismatch, sizeBytes, sha256);
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(buffer);
            }
        }
    }

    private static bool IsCanonicalSha256(string value) =>
        value is { Length: 64 } &&
        value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');
}
