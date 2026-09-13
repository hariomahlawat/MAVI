using System.Buffers;
using System.Security.Cryptography;
using Mavi.Application.Abstractions.Storage;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Storage;

/// <summary>
/// Copies worker-writable attempt artifacts into a platform-owned evidence root
/// while verifying the exact accepted byte length and SHA-256. Published evidence
/// is create-once: this service never overwrites an accepted storage key.
/// </summary>
public sealed class AcceptedEvidenceStore : IAcceptedEvidenceStore
{
    private const int MaximumStorageKeyLength = 512;
    private const string AcceptedPrefix = "evidence/";

    private readonly IMediaStore _mediaStore;
    private readonly string _evidenceRoot;
    private readonly string _evidenceRootPrefix;
    private readonly StringComparison _pathComparison = OperatingSystem.IsWindows()
        ? StringComparison.OrdinalIgnoreCase
        : StringComparison.Ordinal;

    public AcceptedEvidenceStore(
        IMediaStore mediaStore,
        IOptions<MediaStorageOptions> options)
    {
        ArgumentNullException.ThrowIfNull(mediaStore);
        ArgumentNullException.ThrowIfNull(options);
        if (string.IsNullOrWhiteSpace(options.Value.EvidenceRootPath))
            throw new InvalidOperationException("MediaStorage:EvidenceRootPath is required.");

        _mediaStore = mediaStore;
        _evidenceRoot = StorageRootSafety.NormalizeAndValidateRoot(
            options.Value.EvidenceRootPath);
        _evidenceRootPrefix = Path.EndsInDirectorySeparator(_evidenceRoot)
            ? _evidenceRoot
            : _evidenceRoot + Path.DirectorySeparatorChar;
    }

    public async Task<AcceptedEvidenceSealResult> SealAsync(
        string sourceStorageKey,
        string acceptedStorageKey,
        long expectedSizeBytes,
        string expectedSha256,
        CancellationToken cancellationToken)
    {
        if (expectedSizeBytes < 0 || !IsCanonicalSha256(expectedSha256))
            throw new ArgumentException("Expected artifact integrity facts are invalid.");
        cancellationToken.ThrowIfCancellationRequested();
        StorageRootSafety.EnsureNoLinkedExistingComponents(_evidenceRoot);

        var destinationPath = ResolveAcceptedPath(acceptedStorageKey);
        var parentPath = Path.GetDirectoryName(destinationPath)!;
        EnsureExistingPathDoesNotEscapeRoot(parentPath);
        Directory.CreateDirectory(parentPath);
        StorageRootSafety.EnsureNoLinkedExistingComponents(_evidenceRoot);
        EnsureExistingPathDoesNotEscapeRoot(parentPath);

        if (File.Exists(destinationPath))
            return await VerifyExistingAcceptedAsync(
                destinationPath,
                acceptedStorageKey,
                expectedSizeBytes,
                expectedSha256,
                cancellationToken);

        Stream source;
        try
        {
            source = await _mediaStore.OpenReadAsync(sourceStorageKey, cancellationToken);
        }
        catch (FileNotFoundException)
        {
            return new AcceptedEvidenceSealResult(AcceptedEvidenceSealStatus.Missing);
        }
        catch (DirectoryNotFoundException)
        {
            return new AcceptedEvidenceSealResult(AcceptedEvidenceSealStatus.Missing);
        }
        catch (UnsafeMediaPathException)
        {
            return new AcceptedEvidenceSealResult(AcceptedEvidenceSealStatus.IntegrityMismatch);
        }

        var temporaryPath = Path.Combine(
            parentPath,
            $".{Path.GetFileName(destinationPath)}.{Guid.NewGuid():N}.tmp");

        try
        {
            var copied = await CopyAndHashAsync(source, temporaryPath, cancellationToken);
            if (copied.SizeBytes != expectedSizeBytes ||
                !string.Equals(copied.Sha256, expectedSha256, StringComparison.Ordinal))
            {
                return new AcceptedEvidenceSealResult(
                    AcceptedEvidenceSealStatus.IntegrityMismatch,
                    SizeBytes: copied.SizeBytes,
                    Sha256: copied.Sha256);
            }

            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                File.Move(temporaryPath, destinationPath, overwrite: false);
            }
            catch (IOException) when (File.Exists(destinationPath))
            {
                return await VerifyExistingAcceptedAsync(
                    destinationPath,
                    acceptedStorageKey,
                    expectedSizeBytes,
                    expectedSha256,
                    cancellationToken);
            }

            TryMakeReadOnly(destinationPath);
            return new AcceptedEvidenceSealResult(
                AcceptedEvidenceSealStatus.Sealed,
                acceptedStorageKey,
                copied.SizeBytes,
                copied.Sha256);
        }
        finally
        {
            await source.DisposeAsync();
            if (File.Exists(temporaryPath))
                File.Delete(temporaryPath);
        }
    }

    private static async Task<AcceptedEvidenceSealResult> VerifyExistingAcceptedAsync(
        string destinationPath,
        string acceptedStorageKey,
        long expectedSizeBytes,
        string expectedSha256,
        CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            destinationPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 81_920,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        var actual = await HashAsync(stream, cancellationToken);
        if (actual.SizeBytes != expectedSizeBytes ||
            !string.Equals(actual.Sha256, expectedSha256, StringComparison.Ordinal))
        {
            return new AcceptedEvidenceSealResult(
                AcceptedEvidenceSealStatus.DestinationConflict,
                acceptedStorageKey,
                actual.SizeBytes,
                actual.Sha256);
        }

        return new AcceptedEvidenceSealResult(
            AcceptedEvidenceSealStatus.Sealed,
            acceptedStorageKey,
            actual.SizeBytes,
            actual.Sha256);
    }

    private static async Task<(long SizeBytes, string Sha256)> CopyAndHashAsync(
        Stream source,
        string destinationPath,
        CancellationToken cancellationToken)
    {
        await using var destination = new FileStream(
            destinationPath,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            bufferSize: 81_920,
            FileOptions.Asynchronous | FileOptions.SequentialScan);

        var result = await CopyAndHashCoreAsync(
            source,
            destination,
            cancellationToken);
        await destination.FlushAsync(cancellationToken);
        return result;
    }

    private static Task<(long SizeBytes, string Sha256)> HashAsync(
        Stream source,
        CancellationToken cancellationToken) =>
        CopyAndHashCoreAsync(source, destination: null, cancellationToken);

    private static async Task<(long SizeBytes, string Sha256)> CopyAndHashCoreAsync(
        Stream source,
        Stream? destination,
        CancellationToken cancellationToken)
    {
        var buffer = ArrayPool<byte>.Shared.Rent(81_920);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        long sizeBytes = 0;
        try
        {
            while (true)
            {
                var count = await source.ReadAsync(buffer.AsMemory(), cancellationToken);
                if (count == 0) break;
                if (destination is not null)
                    await destination.WriteAsync(buffer.AsMemory(0, count), cancellationToken);
                hash.AppendData(buffer, 0, count);
                sizeBytes = checked(sizeBytes + count);
            }

            return (
                sizeBytes,
                Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant());
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private string ResolveAcceptedPath(string storageKey)
    {
        ValidateAcceptedStorageKey(storageKey);
        var relative = storageKey[AcceptedPrefix.Length..]
            .Replace('/', Path.DirectorySeparatorChar);
        var resolvedPath = Path.GetFullPath(Path.Combine(_evidenceRoot, relative));
        if (!resolvedPath.StartsWith(_evidenceRootPrefix, _pathComparison))
            throw new ArgumentException("Accepted evidence key resolves outside the evidence root.", nameof(storageKey));

        EnsureExistingPathDoesNotEscapeRoot(Path.GetDirectoryName(resolvedPath)!);
        return resolvedPath;
    }

    private static void ValidateAcceptedStorageKey(string storageKey)
    {
        if (string.IsNullOrWhiteSpace(storageKey) ||
            storageKey.Length > MaximumStorageKeyLength ||
            !storageKey.StartsWith(AcceptedPrefix, StringComparison.Ordinal) ||
            storageKey.Contains('\\') ||
            storageKey.Contains(':') ||
            storageKey.Split('/').Any(segment => segment is "" or "." or ".."))
        {
            throw new ArgumentException(
                "Accepted evidence key must be a safe evidence/ relative key.",
                nameof(storageKey));
        }
    }

    private void EnsureExistingPathDoesNotEscapeRoot(string candidateDirectory)
    {
        var current = new DirectoryInfo(candidateDirectory);
        while (current.FullName.StartsWith(_evidenceRootPrefix, _pathComparison) &&
               !string.Equals(current.FullName, _evidenceRoot, _pathComparison))
        {
            if (current.Exists && current.LinkTarget is not null)
            {
                var target = Path.GetFullPath(
                    current.ResolveLinkTarget(returnFinalTarget: true)!.FullName);
                if (!target.StartsWith(_evidenceRootPrefix, _pathComparison) &&
                    !string.Equals(target, _evidenceRoot, _pathComparison))
                {
                    throw new ArgumentException(
                        "Accepted evidence path escapes the evidence root.",
                        nameof(candidateDirectory));
                }
            }

            current = current.Parent!;
        }
    }

    private static void TryMakeReadOnly(string path)
    {
        try
        {
            File.SetAttributes(path, File.GetAttributes(path) | FileAttributes.ReadOnly);
        }
        catch (Exception exception) when (
            exception is PlatformNotSupportedException or
            IOException or
            UnauthorizedAccessException)
        {
            // Root ACL/ownership and create-once publication are the authoritative
            // immutability boundary. Read-only attributes are defense-in-depth.
        }
    }

    private static bool IsCanonicalSha256(string value) =>
        value is { Length: 64 } &&
        value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');
}
