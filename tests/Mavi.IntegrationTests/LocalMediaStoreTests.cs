using System.Security.Cryptography;
using System.Text;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

public sealed class LocalMediaStoreTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"mavi-media-{Guid.NewGuid():N}");

    // Streamed writes
    [Fact]
    public async Task WriteStreamsContentAndReturnsSizeAndLowercaseSha256()
    {
        var content = Encoding.UTF8.GetBytes("MAVI streamed content");
        var store = CreateStore();

        var result = await store.WriteAsync("source/CAM-01/video.mp4", new MemoryStream(content), CancellationToken.None);

        Assert.Equal(content.LongLength, result.SizeBytes);
        Assert.Equal(Convert.ToHexString(SHA256.HashData(content)).ToLowerInvariant(), result.Sha256);
        Assert.Matches("^[0-9a-f]{64}$", result.Sha256);
        Assert.True(File.Exists(Path.Combine(_root, "source", "CAM-01", "video.mp4")));
        Assert.Empty(FindTemporaryFiles());
    }

    [Fact]
    public async Task ExistingDestinationIsNotOverwrittenAndLeavesNoTemporaryFile()
    {
        var store = CreateStore();
        await store.WriteAsync("source/video.mp4", new MemoryStream([1, 2, 3]), CancellationToken.None);

        await Assert.ThrowsAsync<IOException>(() =>
            store.WriteAsync("source/video.mp4", new MemoryStream([9, 9]), CancellationToken.None));

        Assert.Equal([1, 2, 3], await File.ReadAllBytesAsync(Path.Combine(_root, "source", "video.mp4")));
        Assert.Empty(FindTemporaryFiles());
    }

    [Fact]
    public async Task CancellationLeavesNoFinalOrTemporaryFile()
    {
        var store = CreateStore();
        using var cancellation = new CancellationTokenSource();
        await using var content = new CancellingStream(cancellation);

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            store.WriteAsync("source/cancelled.mp4", content, cancellation.Token));

        Assert.False(File.Exists(Path.Combine(_root, "source", "cancelled.mp4")));
        Assert.Empty(FindTemporaryFiles());
    }

    [Fact]
    public async Task ReadFailureLeavesNoFinalOrTemporaryFile()
    {
        var store = CreateStore();
        await using var content = new ThrowingStream();

        await Assert.ThrowsAsync<IOException>(() =>
            store.WriteAsync("source/failure.mp4", content, CancellationToken.None));

        Assert.False(File.Exists(Path.Combine(_root, "source", "failure.mp4")));
        Assert.Empty(FindTemporaryFiles());
    }

    // Logical file operations
    [Fact]
    public async Task OpenExistsAndDeleteRoundTrip()
    {
        var store = CreateStore();
        Assert.False(await store.ExistsAsync("artifact.bin", CancellationToken.None));
        await store.WriteAsync("artifact.bin", new MemoryStream([4, 5, 6]), CancellationToken.None);
        Assert.True(await store.ExistsAsync("artifact.bin", CancellationToken.None));

        await using (var read = await store.OpenReadAsync("artifact.bin", CancellationToken.None))
        {
            Assert.False(read.CanWrite);
            using var copy = new MemoryStream();
            await read.CopyToAsync(copy);
            Assert.Equal([4, 5, 6], copy.ToArray());
        }

        await store.DeleteAsync("artifact.bin", CancellationToken.None);
        await store.DeleteAsync("artifact.bin", CancellationToken.None);
        Assert.False(await store.ExistsAsync("artifact.bin", CancellationToken.None));
    }

    // Storage-key safety
    [Theory]
    [InlineData("")]
    [InlineData("/absolute/video.mp4")]
    [InlineData("C:/absolute/video.mp4")]
    [InlineData("C:\\absolute\\video.mp4")]
    [InlineData("source\\video.mp4")]
    [InlineData("source:video.mp4")]
    [InlineData("source//video.mp4")]
    [InlineData("source/./video.mp4")]
    [InlineData("source/../video.mp4")]
    [InlineData("../video.mp4")]
    public async Task UnsafeStorageKeysAreRejected(string storageKey)
    {
        var store = CreateStore();

        await Assert.ThrowsAsync<ArgumentException>(() =>
            store.ExistsAsync(storageKey, CancellationToken.None));
    }

    [Fact]
    public async Task SymbolicLinkCannotEscapeManagedRoot()
    {
        Directory.CreateDirectory(_root);
        var outside = Path.Combine(Path.GetTempPath(), $"mavi-outside-{Guid.NewGuid():N}");
        Directory.CreateDirectory(outside);
        Directory.CreateSymbolicLink(Path.Combine(_root, "escape"), outside);
        try
        {
            var store = CreateStore();
            await Assert.ThrowsAsync<ArgumentException>(() =>
                store.WriteAsync("escape/new-directory/video.mp4", new MemoryStream([1]), CancellationToken.None));
            Assert.False(Directory.Exists(Path.Combine(outside, "new-directory")));
            Assert.Empty(Directory.GetFiles(outside, "*.tmp", SearchOption.AllDirectories));
        }
        finally
        {
            Directory.Delete(outside, true);
        }
    }

    [Fact]
    public async Task StorageKeyLongerThanDomainMaximumIsRejectedBeforeMutation()
    {
        var store = CreateStore();
        var storageKey = $"{new string('a', 509)}.mp4";

        await Assert.ThrowsAsync<ArgumentException>(() =>
            store.WriteAsync(storageKey, new MemoryStream([1]), CancellationToken.None));

        Assert.False(Directory.Exists(_root));
    }

    // Test lifecycle
    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, true);
        GC.SuppressFinalize(this);
    }

    private LocalMediaStore CreateStore() => new(Options.Create(new MediaStorageOptions { RootPath = _root }));

    private string[] FindTemporaryFiles() => Directory.Exists(_root)
        ? Directory.GetFiles(_root, "*.tmp", SearchOption.AllDirectories)
        : [];

    private sealed class CancellingStream(CancellationTokenSource cancellation) : Stream
    {
        private bool _read;
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (_read) return 0;
            _read = true;
            buffer.Span[0] = 1;
            cancellation.Cancel();
            await Task.Yield();
            cancellationToken.ThrowIfCancellationRequested();
            return 1;
        }
        public override void Flush() { }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    private sealed class ThrowingStream : Stream
    {
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override int Read(byte[] buffer, int offset, int count) => throw new IOException("Synthetic read failure.");
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) =>
            ValueTask.FromException<int>(new IOException("Synthetic read failure."));
        public override void Flush() { }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}
