namespace Mavi.Api.VisualAttributes;

/// <summary>The attempt lost ownership while its evidence read or upload was streaming.</summary>
public sealed class VisualAttributeLeaseLostException() : IOException("visual_attribute_lease_lost");

/// <summary>
/// A read-only stream that stays authorised for its whole lifetime, not only at its start
/// (S2b plan §10: "lease loss/cancellation aborts streaming"; §12). Every read is bracketed by
/// an ownership check; bytes read after ownership was lost are never handed on.
/// </summary>
/// <remarks>
/// <para>
/// The check is a clock comparison. The database is consulted only when the lease the platform
/// last granted this attempt has been reached — a heartbeat may have renewed it, so it is read
/// again — or every <see cref="RecheckInterval"/> at most. That is exact: another executor can
/// take the unit only after its lease expires (claim, attempts-exhausted and deadline all require
/// it), and the single exception — the owner's own failure requeueing the unit, which another
/// worker may then claim at once — is caught within one interval. A 64 MiB upload therefore
/// costs a handful of primary-key reads, and an evidence crop usually none.
/// </para>
/// </remarks>
public sealed class LeaseFencedStream : Stream
{
    public static readonly TimeSpan RecheckInterval = TimeSpan.FromSeconds(5);

    private readonly Stream _inner;
    private readonly Func<CancellationToken, Task<DateTimeOffset?>> _revalidate;
    private readonly TimeProvider _clock;
    private DateTimeOffset _leaseExpiresAtUtc;
    private DateTimeOffset _nextCheckUtc;

    /// <param name="leaseExpiresAtUtc">
    /// The expiry the authorisation observed, or <see cref="DateTimeOffset.MinValue"/> to validate
    /// before the first byte.
    /// </param>
    public LeaseFencedStream(Stream inner, Func<CancellationToken, Task<DateTimeOffset?>> revalidate, TimeProvider clock,
        DateTimeOffset leaseExpiresAtUtc)
    {
        ArgumentNullException.ThrowIfNull(inner);
        ArgumentNullException.ThrowIfNull(revalidate);
        ArgumentNullException.ThrowIfNull(clock);
        _inner = inner;
        _revalidate = revalidate;
        _clock = clock;
        _leaseExpiresAtUtc = leaseExpiresAtUtc;
        _nextCheckUtc = clock.GetUtcNow() + RecheckInterval;
    }

    public override bool CanRead => true;
    public override bool CanSeek => false;
    public override bool CanWrite => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }

    public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
    {
        await EnsureOwnedAsync(cancellationToken);
        var read = await _inner.ReadAsync(buffer, cancellationToken);
        // A read that blocked across the loss of ownership delivers nothing.
        await EnsureOwnedAsync(cancellationToken);
        return read;
    }

    public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
        ReadAsync(buffer.AsMemory(offset, count), cancellationToken).AsTask();

    public override int Read(byte[] buffer, int offset, int count) =>
        throw new NotSupportedException("Lease-fenced streams are read asynchronously.");

    private async ValueTask EnsureOwnedAsync(CancellationToken cancellationToken)
    {
        var now = _clock.GetUtcNow();
        if (now < _leaseExpiresAtUtc && now < _nextCheckUtc) return;
        var expiry = await _revalidate(cancellationToken) ?? throw new VisualAttributeLeaseLostException();
        _leaseExpiresAtUtc = expiry;
        _nextCheckUtc = now + RecheckInterval;
    }

    public override void Flush() { }
    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

    protected override void Dispose(bool disposing)
    {
        if (disposing) _inner.Dispose();
        base.Dispose(disposing);
    }

    public override async ValueTask DisposeAsync()
    {
        await _inner.DisposeAsync();
        await base.DisposeAsync();
    }
}
