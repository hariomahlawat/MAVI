using Mavi.Api.VisualAttributes;

namespace Mavi.IntegrationTests;

/// <summary>
/// The schedule of <see cref="LeaseFencedStream"/> in isolation: when it reads the unit's row,
/// what it enforces from the clock alone, and what it hands on after ownership is lost. The
/// end-to-end transfers over a real socket are in <see cref="VisualAttributeLeaseLifetimeTests"/>.
/// </summary>
public sealed class LeaseFencedStreamTests
{
    private static readonly DateTimeOffset Start = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);
    private static readonly TimeSpan Interval = LeaseFencedStream.RecheckInterval;

    /// <summary>A row read that counts itself and answers what the test says ownership is.</summary>
    private sealed class Ownership(MutableTimeProvider clock)
    {
        public int Reads { get; private set; }
        public DateTimeOffset? Expiry { get; set; } = Start.AddMinutes(2);
        public CancellationToken LastToken { get; private set; }

        public Task<DateTimeOffset?> RevalidateAsync(CancellationToken cancellationToken)
        {
            Reads++;
            LastToken = cancellationToken;
            return Task.FromResult(Expiry is { } expiry && expiry > clock.GetUtcNow() ? Expiry : null);
        }
    }

    /// <summary>An inner stream that yields <paramref name="chunk"/> bytes per read and records disposal.</summary>
    private sealed class ChunkedStream(int length, int chunk) : MemoryStream(new byte[length])
    {
        public bool Disposed { get; private set; }
        public Action? DuringRead { get; set; }

        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            DuringRead?.Invoke();
            return await base.ReadAsync(buffer[..Math.Min(buffer.Length, chunk)], cancellationToken);
        }

        protected override void Dispose(bool disposing)
        {
            Disposed = true;
            base.Dispose(disposing);
        }
    }

    private static (MutableTimeProvider Clock, Ownership Owner, ChunkedStream Inner, LeaseFencedStream Fence) Fence(
        DateTimeOffset? grantedExpiry = null, DateTimeOffset? verifiedAt = null, int length = 1024, int chunk = 16)
    {
        var clock = new MutableTimeProvider(Start);
        var owner = new Ownership(clock);
        var inner = new ChunkedStream(length, chunk);
        var fence = new LeaseFencedStream(inner, owner.RevalidateAsync, clock, grantedExpiry ?? owner.Expiry!.Value, verifiedAt ?? Start);
        return (clock, owner, inner, fence);
    }

    private static async Task<int> ReadAsync(Stream stream, CancellationToken cancellationToken = default) =>
        await stream.ReadAsync(new byte[16], cancellationToken);

    [Fact]
    public async Task ReadsWithinTheIntervalAndTheLeaseNeverTouchTheDatabase()
    {
        var (clock, owner, _, fence) = Fence();
        for (var i = 0; i < 20; i++)
        {
            Assert.Equal(16, await ReadAsync(fence));
            clock.Advance(TimeSpan.FromMilliseconds(200));
        }

        Assert.Equal(0, owner.Reads);
    }

    [Fact]
    public async Task TheFirstRowReadIsDueOneIntervalAfterTheAuthorisationNotAtTheGrantedExpiry()
    {
        // Built 4 s after its authorisation observed ownership, with 2 minutes of lease left.
        var (clock, owner, _, fence) = Fence(verifiedAt: Start.AddSeconds(-4));
        clock.Advance(Interval - TimeSpan.FromSeconds(4) - TimeSpan.FromTicks(1));
        await ReadAsync(fence);
        Assert.Equal(0, owner.Reads);

        clock.Advance(TimeSpan.FromTicks(1));
        owner.Expiry = null; // handed over: the owner failed and another attempt claimed
        await Assert.ThrowsAsync<VisualAttributeLeaseLostException>(() => ReadAsync(fence));
        Assert.Equal(1, owner.Reads);
    }

    [Fact]
    public async Task AfterASuccessfulRowReadTheNextIsDueOneIntervalLaterNotAtTheRenewedExpiry()
    {
        var (clock, owner, _, fence) = Fence();
        clock.Advance(Interval);
        await ReadAsync(fence);
        Assert.Equal(1, owner.Reads);

        // The same owner, the same lease: the fence keeps going and reads again after an interval.
        clock.Advance(Interval - TimeSpan.FromTicks(1));
        await ReadAsync(fence);
        Assert.Equal(1, owner.Reads);
        clock.Advance(TimeSpan.FromTicks(1));
        owner.Expiry = null;
        await Assert.ThrowsAsync<VisualAttributeLeaseLostException>(() => ReadAsync(fence));
        Assert.Equal(2, owner.Reads);
    }

    [Fact]
    public async Task AKnownExpiryIsEnforcedAtThatInstantEvenInsideAnInterval()
    {
        var expiry = Start.AddSeconds(2);
        var (clock, owner, _, fence) = Fence(grantedExpiry: expiry);
        owner.Expiry = expiry;
        clock.Advance(TimeSpan.FromSeconds(2) - TimeSpan.FromTicks(1));
        await ReadAsync(fence);
        Assert.Equal(0, owner.Reads);

        clock.Advance(TimeSpan.FromTicks(1));
        await Assert.ThrowsAsync<VisualAttributeLeaseLostException>(() => ReadAsync(fence));
    }

    [Fact]
    public async Task ARenewedLeaseCarriesTheStreamPastTheExpiryItStartedUnder()
    {
        var (clock, owner, _, fence) = Fence(grantedExpiry: Start.AddSeconds(2));
        owner.Expiry = Start.AddMinutes(2); // a heartbeat renewed it
        clock.Advance(TimeSpan.FromSeconds(2));
        Assert.Equal(16, await ReadAsync(fence));
        Assert.Equal(1, owner.Reads);
    }

    [Fact]
    public async Task AnUnknownExpiryIsValidatedBeforeTheFirstByte()
    {
        var clock = new MutableTimeProvider(Start);
        var owner = new Ownership(clock) { Expiry = null };
        await using var fence = new LeaseFencedStream(new ChunkedStream(64, 16), owner.RevalidateAsync, clock,
            DateTimeOffset.MinValue, DateTimeOffset.MinValue);

        await Assert.ThrowsAsync<VisualAttributeLeaseLostException>(() => ReadAsync(fence));
        Assert.Equal(1, owner.Reads);
    }

    [Fact]
    public async Task BytesReadAcrossTheLossOfOwnershipAreNeverHandedOn()
    {
        var (clock, owner, inner, fence) = Fence();
        inner.DuringRead = () =>
        {
            clock.Advance(Interval);
            owner.Expiry = null;
        };
        var buffer = new byte[16];

        await Assert.ThrowsAsync<VisualAttributeLeaseLostException>(async () => _ = await fence.ReadAsync(buffer));
    }

    [Fact]
    public async Task TheEndOfTheStreamIsFencedToo()
    {
        var (clock, owner, _, fence) = Fence(length: 16);
        Assert.Equal(16, await ReadAsync(fence));
        clock.Advance(Interval);
        owner.Expiry = null;
        await Assert.ThrowsAsync<VisualAttributeLeaseLostException>(() => ReadAsync(fence));
    }

    [Fact]
    public async Task CancellationReachesTheInnerReadAndTheRowRead()
    {
        var (clock, owner, _, fence) = Fence();
        using var cancellation = new CancellationTokenSource();
        clock.Advance(Interval);
        await ReadAsync(fence, cancellation.Token);
        Assert.Equal(cancellation.Token, owner.LastToken);

        await cancellation.CancelAsync();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => ReadAsync(fence, cancellation.Token));
    }

    [Fact]
    public async Task AFailingRowReadIsNotMistakenForOwnership()
    {
        var clock = new MutableTimeProvider(Start);
        await using var fence = new LeaseFencedStream(new ChunkedStream(64, 16),
            _ => Task.FromException<DateTimeOffset?>(new TimeoutException()), clock, Start.AddMinutes(2), Start);
        clock.Advance(Interval);

        await Assert.ThrowsAsync<TimeoutException>(() => ReadAsync(fence));
    }

    [Fact]
    public async Task DisposingTheFenceDisposesTheInnerStream()
    {
        var (_, _, asyncInner, asyncFence) = Fence();
        await asyncFence.DisposeAsync();
        Assert.True(asyncInner.Disposed);

        var (_, _, syncInner, syncFence) = Fence();
        syncFence.Dispose();
        Assert.True(syncInner.Disposed);
    }

    [Fact]
    public void TheFenceIsReadOnlyAndAsynchronous()
    {
        var (_, _, _, fence) = Fence();
        Assert.True(fence.CanRead);
        Assert.False(fence.CanSeek);
        Assert.False(fence.CanWrite);
        Assert.Throws<NotSupportedException>(() => fence.Read(new byte[16], 0, 16));
    }
}
