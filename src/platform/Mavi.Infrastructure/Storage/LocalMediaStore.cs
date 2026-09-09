using System.Buffers;
using System.Security.Cryptography;
using Mavi.Application.Abstractions.Storage;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Storage;

public sealed class LocalMediaStore : IMediaStore, ILocalMediaPathResolver
{
    private const int MaximumStorageKeyLength = 512;
    private readonly string _rootPath;
    private readonly string _rootPrefix;
    private readonly StringComparison _pathComparison = OperatingSystem.IsWindows()
        ? StringComparison.OrdinalIgnoreCase
        : StringComparison.Ordinal;

    // Configuration
    public LocalMediaStore(IOptions<MediaStorageOptions> options)
    {
        ArgumentNullException.ThrowIfNull(options);
        if (string.IsNullOrWhiteSpace(options.Value.RootPath))
        {
            throw new InvalidOperationException("MediaStorage:RootPath is required.");
        }

        _rootPath = Path.GetFullPath(options.Value.RootPath);
        _rootPrefix = Path.EndsInDirectorySeparator(_rootPath)
            ? _rootPath
            : _rootPath + Path.DirectorySeparatorChar;
    }

    // Write operations
    public async Task<MediaWriteResult> WriteAsync(
        string storageKey,
        Stream content,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(content);
        cancellationToken.ThrowIfCancellationRequested();
        var finalPath = ResolveLocalPath(storageKey);
        var parentPath = Path.GetDirectoryName(finalPath)!;
        EnsureExistingPathDoesNotEscapeRoot(parentPath);
        Directory.CreateDirectory(parentPath);
        EnsureExistingPathDoesNotEscapeRoot(parentPath);

        var temporaryPath = Path.Combine(parentPath, $".{Path.GetFileName(finalPath)}.{Guid.NewGuid():N}.tmp");
        if (File.Exists(finalPath))
        {
            throw new IOException("The managed media destination already exists.");
        }

        try
        {
            var writeResult = await WriteTemporaryFileAsync(temporaryPath, content, cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            File.Move(temporaryPath, finalPath, overwrite: false);
            return writeResult;
        }
        finally
        {
            if (File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }
    }

    private static async Task<MediaWriteResult> WriteTemporaryFileAsync(
        string temporaryPath,
        Stream content,
        CancellationToken cancellationToken)
    {
        var buffer = ArrayPool<byte>.Shared.Rent(81_920);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        long sizeBytes = 0;
        try
        {
            await using (var output = new FileStream(
                temporaryPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                bufferSize: 81_920,
                FileOptions.Asynchronous | FileOptions.SequentialScan))
            {
                while (true)
                {
                    var count = await content.ReadAsync(buffer.AsMemory(), cancellationToken);
                    if (count == 0) break;
                    await output.WriteAsync(buffer.AsMemory(0, count), cancellationToken);
                    hash.AppendData(buffer, 0, count);
                    sizeBytes = checked(sizeBytes + count);
                }

                await output.FlushAsync(cancellationToken);
            }

            return new MediaWriteResult(sizeBytes, Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant());
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    // Read and lifecycle operations
    public Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Stream stream = new FileStream(
            ResolveLocalPath(storageKey),
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 81_920,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        return Task.FromResult(stream);
    }

    public Task<bool> ExistsAsync(string storageKey, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(File.Exists(ResolveLocalPath(storageKey)));
    }

    public Task DeleteAsync(string storageKey, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        File.Delete(ResolveLocalPath(storageKey));
        return Task.CompletedTask;
    }

    // Path safety
    string ILocalMediaPathResolver.ResolveLocalPath(string storageKey) => ResolveLocalPath(storageKey);

    internal string ResolveLocalPath(string storageKey)
    {
        ValidateStorageKey(storageKey);
        var resolvedPath = Path.GetFullPath(Path.Combine(_rootPath, storageKey.Replace('/', Path.DirectorySeparatorChar)));
        if (!resolvedPath.StartsWith(_rootPrefix, _pathComparison))
        {
            throw new ArgumentException("Storage key resolves outside the managed media root.", nameof(storageKey));
        }

        EnsureExistingPathDoesNotEscapeRoot(Path.GetDirectoryName(resolvedPath)!);
        return resolvedPath;
    }

    private static void ValidateStorageKey(string storageKey)
    {
        if (string.IsNullOrWhiteSpace(storageKey) || storageKey.Length > MaximumStorageKeyLength || storageKey.StartsWith('/') ||
            storageKey.Contains('\\') || storageKey.Contains(':') ||
            storageKey.Split('/').Any(segment => segment is "" or "." or ".."))
        {
            throw new ArgumentException("Storage key must be a safe relative slash-separated key.", nameof(storageKey));
        }
    }

    private void EnsureExistingPathDoesNotEscapeRoot(string candidateDirectory)
    {
        var current = new DirectoryInfo(candidateDirectory);
        while (current.FullName.StartsWith(_rootPrefix, _pathComparison) &&
               !string.Equals(current.FullName, _rootPath, _pathComparison))
        {
            if (current.Exists && current.LinkTarget is not null)
            {
                var target = Path.GetFullPath(current.ResolveLinkTarget(returnFinalTarget: true)!.FullName);
                if (!target.StartsWith(_rootPrefix, _pathComparison) &&
                    !string.Equals(target, _rootPath, _pathComparison))
                {
                    throw new ArgumentException("Storage key resolves outside the managed media root.", nameof(candidateDirectory));
                }
            }

            current = current.Parent!;
        }
    }
}
