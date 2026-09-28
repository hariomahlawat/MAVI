using System.Buffers;
using System.Security.Cryptography;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Contracts.Worker.Attributes;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Storage;

/// <summary>
/// Streams an uploaded prediction artefact into its attempt's staging directory: capped,
/// hashed while streaming, fsynced, then published create-once. Nothing is buffered beyond
/// one copy buffer, and nothing already staged is ever overwritten (S2b plan §12).
/// </summary>
public sealed class AttributeStagingStore : IAttributeStagingStore
{
    private readonly string _root;

    public AttributeStagingStore(IOptions<MediaStorageOptions> options)
    {
        ArgumentNullException.ThrowIfNull(options);
        _root = StorageRootSafety.NormalizeAndValidateRoot(options.Value.RootPath);
    }

    public async Task<AttributeUploadResult> WriteAsync(
        Guid analysisId, int attemptCount, Stream body, long declaredSizeBytes, string declaredSha256, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(body);
        if (analysisId == Guid.Empty || attemptCount < 1 || declaredSizeBytes < 0 ||
            declaredSizeBytes > VisualAttributeContractRules.MaximumPredictionArtifactBytes ||
            !VisualAttributeContractRules.IsCanonicalSha256(declaredSha256))
            throw new ArgumentException("The upload descriptor is invalid.");

        var directory = AttemptDirectory(analysisId, attemptCount);
        StorageRootSafety.EnsureNoLinkedExistingComponents(_root);
        DurableFilePublication.EnsureDirectoryHierarchy(_root, directory);
        StorageRootSafety.EnsureNoLinkedExistingComponents(directory);
        var destination = Path.Combine(directory, AttributeStagingLayout.PredictionsFileName);

        if (File.Exists(destination))
            return await CompareExistingAsync(destination, declaredSizeBytes, declaredSha256, cancellationToken);

        var temporary = Path.Combine(directory, $".{AttributeStagingLayout.PredictionsFileName}.{Guid.NewGuid():N}.tmp");
        try
        {
            var (size, sha256, exceeded) = await CopyAndHashAsync(body, temporary, declaredSizeBytes, cancellationToken);
            if (exceeded) return new AttributeUploadResult(AttributeUploadStatus.TooLarge, size, null);
            if (size < declaredSizeBytes) return new AttributeUploadResult(AttributeUploadStatus.Truncated, size, null);
            if (!string.Equals(sha256, declaredSha256, StringComparison.Ordinal))
                return new AttributeUploadResult(AttributeUploadStatus.IntegrityMismatch, size, sha256);

            cancellationToken.ThrowIfCancellationRequested();
            if (DurableFilePublication.Publish(temporary, destination, directory) == DurablePublicationOutcome.DestinationAlreadyExists)
                return await CompareExistingAsync(destination, declaredSizeBytes, declaredSha256, cancellationToken);
            return new AttributeUploadResult(AttributeUploadStatus.Stored, size, sha256);
        }
        finally
        {
            TryDelete(temporary);
        }
    }

    public StagedPredictions? Describe(Guid analysisId, int attemptCount)
    {
        var path = Path.Combine(AttemptDirectory(analysisId, attemptCount), AttributeStagingLayout.PredictionsFileName);
        var file = new FileInfo(path);
        return file.Exists && file.LinkTarget is null
            ? new StagedPredictions(AttributeStagingLayout.StagingKey(analysisId, attemptCount), file.Length)
            : null;
    }

    public Task<Stream> OpenReadAsync(Guid analysisId, int attemptCount, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var directory = AttemptDirectory(analysisId, attemptCount);
        StorageRootSafety.EnsureNoLinkedExistingComponents(directory);
        Stream stream = new FileStream(Path.Combine(directory, AttributeStagingLayout.PredictionsFileName), FileMode.Open,
            FileAccess.Read, FileShare.Read, 81_920, FileOptions.Asynchronous | FileOptions.SequentialScan);
        return Task.FromResult(stream);
    }

    private string AttemptDirectory(Guid analysisId, int attemptCount)
    {
        if (analysisId == Guid.Empty || attemptCount < 1) throw new ArgumentException("The staging attempt is invalid.");
        return Path.Combine(_root, AttributeStagingLayout.RootDirectoryName, analysisId.ToString("D"),
            AttributeStagingLayout.AttemptDirectoryName(attemptCount));
    }

    private static async Task<AttributeUploadResult> CompareExistingAsync(
        string destination, long declaredSizeBytes, string declaredSha256, CancellationToken cancellationToken)
    {
        await using var existing = new FileStream(destination, FileMode.Open, FileAccess.Read, FileShare.Read, 81_920,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        var (size, sha256, exceeded) = await CopyAndHashCoreAsync(existing, null, declaredSizeBytes, cancellationToken);
        return !exceeded && size == declaredSizeBytes && string.Equals(sha256, declaredSha256, StringComparison.Ordinal)
            ? new AttributeUploadResult(AttributeUploadStatus.AlreadyStored, size, sha256)
            : new AttributeUploadResult(AttributeUploadStatus.Conflict, size, null);
    }

    private static async Task<(long Size, string Sha256, bool Exceeded)> CopyAndHashAsync(
        Stream source, string destinationPath, long maximumBytes, CancellationToken cancellationToken)
    {
        await using var destination = new FileStream(destinationPath, FileMode.CreateNew, FileAccess.Write, FileShare.None,
            81_920, FileOptions.Asynchronous | FileOptions.SequentialScan);
        var result = await CopyAndHashCoreAsync(source, destination, maximumBytes, cancellationToken);
        if (!result.Exceeded)
        {
            await destination.FlushAsync(cancellationToken);
            destination.Flush(flushToDisk: true);
        }

        return result;
    }

    private static async Task<(long Size, string Sha256, bool Exceeded)> CopyAndHashCoreAsync(
        Stream source, Stream? destination, long maximumBytes, CancellationToken cancellationToken)
    {
        var buffer = ArrayPool<byte>.Shared.Rent(81_920);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        long size = 0;
        try
        {
            while (true)
            {
                var requested = (int)Math.Min(buffer.Length, maximumBytes - size + 1);
                var count = await source.ReadAsync(buffer.AsMemory(0, requested), cancellationToken);
                if (count == 0) break;
                if (size + count > maximumBytes) return (size + count, string.Empty, true);
                if (destination is not null) await destination.WriteAsync(buffer.AsMemory(0, count), cancellationToken);
                hash.AppendData(buffer, 0, count);
                size += count;
            }

            return (size, Convert.ToHexStringLower(hash.GetHashAndReset()), false);
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path)) File.Delete(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A leftover hidden temporary is janitor garbage; it never masks the result.
        }
    }
}
