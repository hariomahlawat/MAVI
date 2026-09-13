using System.Security.Cryptography;
using System.Text;
using Mavi.Application.Abstractions.Storage;
using Mavi.Infrastructure.Storage;
using Mavi.Contracts.Worker;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

public sealed class AcceptedEvidenceStoreTests : IDisposable
{
    private readonly string _mediaRoot =
        Path.Combine(Path.GetTempPath(), $"mavi-accepted-media-{Guid.NewGuid():N}");
    private readonly string _evidenceRoot =
        Path.Combine(Path.GetTempPath(), $"mavi-accepted-evidence-{Guid.NewGuid():N}");

    [Fact]
    public void DurablePublicationOwnsNestedHierarchyCreation()
    {
        var type = typeof(LocalMediaStore).Assembly.GetType(
            "Mavi.Infrastructure.Storage.DurableFilePublication");
        Assert.NotNull(type);
        var method = type.GetMethod(
            "EnsureDirectoryHierarchy",
            System.Reflection.BindingFlags.Static |
            System.Reflection.BindingFlags.Public |
            System.Reflection.BindingFlags.NonPublic);
        Assert.NotNull(method);

        var nested = Path.Combine(_evidenceRoot, "job", "attempt-0001", "thumbnails");
        Assert.False(Directory.Exists(nested));

        method.Invoke(null, [nested]);

        Assert.True(Directory.Exists(nested));
    }

    [Fact]
    public async Task SealCopiesVerifiedBytesIntoPlatformOwnedEvidenceRoot()
    {
        var mediaStore = CreateMediaStore();
        var sealer = CreateSealer(mediaStore);
        var sourceBytes = Encoding.UTF8.GetBytes("immutable-evidence");
        var source = await mediaStore.WriteAsync(
            "staging/job/attempt-0001/thumbnails/person-000001.jpg",
            new MemoryStream(sourceBytes),
            CancellationToken.None);
        var acceptedKey =
            $"evidence/job/attempt-0001/thumbnails/person-000001-{source.Sha256}.jpg";

        var result = await sealer.SealAsync(
            "staging/job/attempt-0001/thumbnails/person-000001.jpg",
            acceptedKey,
            source.SizeBytes,
            source.Sha256,
            CancellationToken.None);

        Assert.Equal(AcceptedEvidenceSealStatus.Sealed, result.Status);
        Assert.Equal(acceptedKey, result.StorageKey);
        Assert.True(result.CreatedNew);

        var acceptedPath = EvidencePath(acceptedKey);
        Assert.True(File.Exists(acceptedPath));
        var acceptedBytes = await File.ReadAllBytesAsync(acceptedPath);
        Assert.Equal(sourceBytes, acceptedBytes);

        await File.WriteAllBytesAsync(
            Path.Combine(
                _mediaRoot,
                "staging",
                "job",
                "attempt-0001",
                "thumbnails",
                "person-000001.jpg"),
            Encoding.UTF8.GetBytes("mutated-staging"));

        Assert.Equal(sourceBytes, await File.ReadAllBytesAsync(acceptedPath));
        Assert.Equal(
            source.Sha256,
            Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(acceptedPath)))
                .ToLowerInvariant());
    }

    [Fact]
    public async Task SealRejectsIntegrityMismatchWithoutPublishingAcceptedObject()
    {
        var mediaStore = CreateMediaStore();
        var sealer = CreateSealer(mediaStore);
        await mediaStore.WriteAsync(
            "staging/job/attempt-0001/trajectories/person-000001.msgpack",
            new MemoryStream([1, 2, 3]),
            CancellationToken.None);
        var acceptedKey =
            $"evidence/job/attempt-0001/trajectories/person-000001-{new string('a', 64)}.msgpack";

        var result = await sealer.SealAsync(
            "staging/job/attempt-0001/trajectories/person-000001.msgpack",
            acceptedKey,
            3,
            new string('a', 64),
            CancellationToken.None);

        Assert.Equal(AcceptedEvidenceSealStatus.IntegrityMismatch, result.Status);
        Assert.False(File.Exists(EvidencePath(acceptedKey)));
        Assert.Empty(FindTemporaryFiles());
    }

    [Fact]
    public async Task OversizedSourceStopsAfterDeclaredSizeProbeByte()
    {
        Directory.CreateDirectory(_mediaRoot);
        Directory.CreateDirectory(_evidenceRoot);
        var source = new CountingReadStream(new byte[1024]);
        var mediaStore = new ReadOnlyTestMediaStore(source);
        var sealer = CreateSealer(mediaStore);
        var acceptedKey =
            $"evidence/job/attempt-0001/thumbnails/person-000001-{new string('a', 64)}.jpg";

        var result = await sealer.SealAsync(
            "staging/job/attempt-0001/thumbnails/person-000001.jpg",
            acceptedKey,
            3,
            new string('a', 64),
            CancellationToken.None);

        Assert.Equal(AcceptedEvidenceSealStatus.IntegrityMismatch, result.Status);
        Assert.Equal(4, source.BytesRead);
        Assert.False(File.Exists(EvidencePath(acceptedKey)));
        Assert.Empty(FindTemporaryFiles());
    }

    [Fact]
    public async Task DeclaredArtifactAbovePolicyIsRejectedBeforeSourceOpen()
    {
        Directory.CreateDirectory(_mediaRoot);
        Directory.CreateDirectory(_evidenceRoot);
        var source = new CountingReadStream([1, 2, 3]);
        var mediaStore = new ReadOnlyTestMediaStore(source);
        var sealer = CreateSealer(mediaStore);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            sealer.SealAsync(
                "staging/job/attempt-0001/thumbnails/person-000001.jpg",
                $"evidence/job/attempt-0001/thumbnails/person-000001-{new string('a', 64)}.jpg",
                WorkerContractRules.MaximumCompletionArtifactBytes + 1,
                new string('a', 64),
                CancellationToken.None));

        Assert.False(mediaStore.WasOpened);
        Assert.Equal(0, source.BytesRead);
    }

    [Fact]
    public async Task ExistingAcceptedObjectIsIdempotentOnlyForIdenticalFacts()
    {
        var mediaStore = CreateMediaStore();
        var sealer = CreateSealer(mediaStore);
        var source = await mediaStore.WriteAsync(
            "staging/job/attempt-0001/thumbnails/person-000001.jpg",
            new MemoryStream([4, 5, 6]),
            CancellationToken.None);
        var acceptedKey =
            $"evidence/job/attempt-0001/thumbnails/person-000001-{source.Sha256}.jpg";

        var first = await sealer.SealAsync(
            "staging/job/attempt-0001/thumbnails/person-000001.jpg",
            acceptedKey,
            source.SizeBytes,
            source.Sha256,
            CancellationToken.None);
        var second = await sealer.SealAsync(
            "staging/job/attempt-0001/thumbnails/person-000001.jpg",
            acceptedKey,
            source.SizeBytes,
            source.Sha256,
            CancellationToken.None);

        Assert.Equal(AcceptedEvidenceSealStatus.Sealed, first.Status);
        Assert.Equal(AcceptedEvidenceSealStatus.Sealed, second.Status);
        Assert.True(first.CreatedNew);
        Assert.False(second.CreatedNew);
    }

    [Fact]
    public async Task DeleteAcceptedRemovesPublishedObject()
    {
        var mediaStore = CreateMediaStore();
        var sealer = CreateSealer(mediaStore);
        var source = await mediaStore.WriteAsync(
            "staging/job/attempt-0001/thumbnails/person-000001.jpg",
            new MemoryStream([7, 8, 9]),
            CancellationToken.None);
        var acceptedKey =
            $"evidence/job/attempt-0001/thumbnails/person-000001-{source.Sha256}.jpg";

        var sealedResult = await sealer.SealAsync(
            "staging/job/attempt-0001/thumbnails/person-000001.jpg",
            acceptedKey,
            source.SizeBytes,
            source.Sha256,
            CancellationToken.None);
        Assert.True(sealedResult.CreatedNew);
        Assert.True(File.Exists(EvidencePath(acceptedKey)));

        await sealer.DeleteAcceptedAsync(acceptedKey, CancellationToken.None);

        Assert.False(File.Exists(EvidencePath(acceptedKey)));
    }

    [Fact]
    public void LinkedEvidenceRootIsRejectedByStoreConstructor()
    {
        Directory.CreateDirectory(_mediaRoot);
        var linkedEvidence =
            Path.Combine(Path.GetTempPath(), $"mavi-linked-evidence-{Guid.NewGuid():N}");
        try
        {
            try
            {
                Directory.CreateSymbolicLink(linkedEvidence, _mediaRoot);
            }
            catch (Exception exception) when (
                exception is PlatformNotSupportedException or UnauthorizedAccessException)
            {
                return;
            }

            var mediaStore = CreateMediaStore();
            Assert.Throws<InvalidOperationException>(() =>
                new AcceptedEvidenceStore(
                    mediaStore,
                    Options.Create(new MediaStorageOptions
                    {
                        RootPath = _mediaRoot,
                        EvidenceRootPath = linkedEvidence,
                    })));
        }
        finally
        {
            if (Directory.Exists(linkedEvidence))
                Directory.Delete(linkedEvidence);
        }
    }

    [Theory]
    [InlineData("staging/job/a.jpg")]
    [InlineData("evidence/../escape.jpg")]
    [InlineData("evidence//escape.jpg")]
    [InlineData("evidence/C:/escape.jpg")]
    [InlineData("evidence\\escape.jpg")]
    public async Task UnsafeAcceptedStorageKeyIsRejected(string acceptedKey)
    {
        var mediaStore = CreateMediaStore();
        var sealer = CreateSealer(mediaStore);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            sealer.SealAsync(
                "staging/job/attempt-0001/a.jpg",
                acceptedKey,
                1,
                new string('a', 64),
                CancellationToken.None));
    }

    public void Dispose()
    {
        if (Directory.Exists(_mediaRoot))
            Directory.Delete(_mediaRoot, true);
        if (Directory.Exists(_evidenceRoot))
        {
            foreach (var file in Directory.GetFiles(_evidenceRoot, "*", SearchOption.AllDirectories))
                File.SetAttributes(file, FileAttributes.Normal);
            Directory.Delete(_evidenceRoot, true);
        }
        GC.SuppressFinalize(this);
    }

    private LocalMediaStore CreateMediaStore() =>
        new(Options.Create(new MediaStorageOptions
        {
            RootPath = _mediaRoot,
            EvidenceRootPath = _evidenceRoot,
        }));

    private AcceptedEvidenceStore CreateSealer(IMediaStore mediaStore) =>
        new(
            mediaStore,
            Options.Create(new MediaStorageOptions
            {
                RootPath = _mediaRoot,
                EvidenceRootPath = _evidenceRoot,
            }));

    private string EvidencePath(string storageKey) =>
        Path.Combine(
            _evidenceRoot,
            storageKey["evidence/".Length..]
                .Replace('/', Path.DirectorySeparatorChar));

    private string[] FindTemporaryFiles() =>
        Directory.Exists(_evidenceRoot)
            ? Directory.GetFiles(_evidenceRoot, "*.tmp", SearchOption.AllDirectories)
            : [];
}


internal sealed class ReadOnlyTestMediaStore(Stream source) : IMediaStore
{
    public bool WasOpened { get; private set; }

    public Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        WasOpened = true;
        return Task.FromResult(source);
    }

    public Task<MediaWriteResult> WriteAsync(
        string storageKey,
        Stream content,
        CancellationToken cancellationToken) =>
        throw new NotSupportedException();

    public Task<bool> ExistsAsync(string storageKey, CancellationToken cancellationToken) =>
        throw new NotSupportedException();

    public Task DeleteAsync(string storageKey, CancellationToken cancellationToken) =>
        throw new NotSupportedException();
}

internal sealed class CountingReadStream(byte[] bytes) : MemoryStream(bytes, writable: false)
{
    public long BytesRead { get; private set; }

    public override async ValueTask<int> ReadAsync(
        Memory<byte> buffer,
        CancellationToken cancellationToken = default)
    {
        var count = await base.ReadAsync(buffer, cancellationToken);
        BytesRead += count;
        return count;
    }
}
