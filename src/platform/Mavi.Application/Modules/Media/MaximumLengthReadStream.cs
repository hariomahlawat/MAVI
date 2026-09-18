namespace Mavi.Application.Modules.Media;

internal sealed class MaximumLengthReadStream(Stream inner, long maximumBytes) : Stream
{
    private long _observed;

    // Bounded reads
    public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
    {
        var allowed = Math.Min(buffer.Length, checked((int)Math.Min(int.MaxValue, maximumBytes + 1 - Math.Min(_observed, maximumBytes + 1))));
        if (allowed == 0) throw new VideoFileTooLargeException();
        var count = await inner.ReadAsync(buffer[..allowed], cancellationToken);
        _observed += count;
        if (_observed > maximumBytes) throw new VideoFileTooLargeException();
        return count;
    }

    public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    public override bool CanRead => inner.CanRead;
    public override bool CanSeek => false;
    public override bool CanWrite => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
    public override void Flush() => throw new NotSupportedException();
    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
}

internal sealed class VideoFileTooLargeException : Exception;
