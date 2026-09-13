using System.Security.Cryptography;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Evidence;
using Mavi.Domain.Media;

namespace Mavi.Application.Tests;

public sealed class ContentReadServiceTests
{
    [Fact]
    public async Task InvalidDescriptorIsRejectedBeforeStorageAccess()
    {
        var descriptor = Descriptor(
            ArtifactType.Thumbnail,
            ContentStorageKind.AcceptedEvidence,
            "evidence/job/file.jpg",
            "text/plain",
            sizeBytes: 3);
        var catalog = new FakeCatalog(evidence: descriptor);
        var media = new FakeMediaStore([1, 2, 3]);
        var evidence = new FakeEvidenceReader([1, 2, 3]);
        var service = new ContentReadService(catalog, media, evidence);

        var result = await service.OpenEvidenceAsync(
            descriptor.ArtifactId,
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal("artifact_content_unavailable", result.ErrorCode);
        Assert.Equal(0, media.OpenCalls);
        Assert.Equal(0, evidence.OpenCalls);
    }

    [Fact]
    public async Task SourceAndEvidenceContentUseSeparateStores()
    {
        var videoDescriptor = Descriptor(
            ArtifactType.SourceVideo,
            ContentStorageKind.ManagedMedia,
            "source/cam/video.mp4",
            "video/mp4",
            sizeBytes: 3);
        var evidenceDescriptor = Descriptor(
            ArtifactType.Thumbnail,
            ContentStorageKind.AcceptedEvidence,
            "evidence/job/file.jpg",
            "image/jpeg",
            sizeBytes: 3);
        var catalog = new FakeCatalog(videoDescriptor, evidenceDescriptor);
        var media = new FakeMediaStore([1, 2, 3]);
        var evidence = new FakeEvidenceReader([4, 5, 6]);
        var service = new ContentReadService(catalog, media, evidence);

        var video = await service.OpenVideoAsync(Guid.CreateVersion7(), CancellationToken.None);
        var artifact = await service.OpenEvidenceAsync(
            evidenceDescriptor.ArtifactId,
            CancellationToken.None);

        Assert.True(video.IsSuccess);
        Assert.True(artifact.IsSuccess);
        Assert.Equal(1, media.OpenCalls);
        Assert.Equal(1, evidence.OpenCalls);
        await video.Stream!.DisposeAsync();
        await artifact.Stream!.DisposeAsync();
    }

    [Fact]
    public async Task LengthMismatchFailsClosedAndDisposesStream()
    {
        var descriptor = Descriptor(
            ArtifactType.Thumbnail,
            ContentStorageKind.AcceptedEvidence,
            "evidence/job/file.jpg",
            "image/jpeg",
            sizeBytes: 4);
        var stream = new TrackingStream([1, 2, 3]);
        var service = new ContentReadService(
            new FakeCatalog(evidence: descriptor),
            new FakeMediaStore([1]),
            new FakeEvidenceReader(stream));

        var result = await service.OpenEvidenceAsync(
            descriptor.ArtifactId,
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal("artifact_content_unavailable", result.ErrorCode);
        Assert.True(stream.WasDisposed);
    }

    private static ContentDescriptor Descriptor(
        ArtifactType type,
        ContentStorageKind storageKind,
        string key,
        string mime,
        long sizeBytes)
    {
        var bytes = new byte[Math.Max(1, checked((int)sizeBytes))];
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        return new ContentDescriptor(
            Guid.CreateVersion7(),
            type,
            key,
            mime,
            sizeBytes,
            sha,
            storageKind);
    }

    private sealed class FakeCatalog(
        ContentDescriptor? video = null,
        ContentDescriptor? evidence = null) : IContentCatalog
    {
        public Task<ContentDescriptor?> GetVideoContentAsync(
            Guid videoAssetId,
            CancellationToken cancellationToken) =>
            Task.FromResult(video);

        public Task<ContentDescriptor?> GetEvidenceContentAsync(
            Guid artifactId,
            CancellationToken cancellationToken) =>
            Task.FromResult(evidence);
    }

    private sealed class FakeMediaStore(byte[] bytes) : IMediaStore
    {
        public int OpenCalls { get; private set; }

        public Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken)
        {
            OpenCalls++;
            return Task.FromResult<Stream>(new MemoryStream(bytes, writable: false));
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

    private sealed class FakeEvidenceReader : IAcceptedEvidenceReader
    {
        private readonly Func<Stream> _streamFactory;

        public FakeEvidenceReader(byte[] bytes)
        {
            _streamFactory = () => new MemoryStream(bytes, writable: false);
        }

        public FakeEvidenceReader(Stream stream)
        {
            _streamFactory = () => stream;
        }

        public int OpenCalls { get; private set; }

        public Task<Stream> OpenReadAsync(
            string acceptedStorageKey,
            CancellationToken cancellationToken)
        {
            OpenCalls++;
            return Task.FromResult(_streamFactory());
        }
    }

    private sealed class TrackingStream(byte[] bytes)
        : MemoryStream(bytes, writable: false)
    {
        public bool WasDisposed { get; private set; }

        protected override void Dispose(bool disposing)
        {
            WasDisposed = true;
            base.Dispose(disposing);
        }

        public override async ValueTask DisposeAsync()
        {
            WasDisposed = true;
            await base.DisposeAsync();
        }
    }
}
