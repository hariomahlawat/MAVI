using Mavi.Application.Modules.Intelligence;

namespace Mavi.Application.Tests;

public sealed class TrackCursorCodecTests
{
    [Fact]
    public void RoundTripPreservesCanonicalUtcPosition()
    {
        
        var position = new TrackCursorPosition(
            new DateTimeOffset(2026, 9, 13, 11, 0, 0, TimeSpan.Zero),
            new DateTimeOffset(2026, 9, 13, 10, 20, 30, TimeSpan.Zero),
            Guid.CreateVersion7());

        var encoded = TrackCursorCodec.Encode(position);

        Assert.True(TrackCursorCodec.TryDecode(encoded, out var decoded));
        Assert.NotNull(decoded);
        Assert.Equal(position.SnapshotUtc, decoded!.SnapshotUtc);
        Assert.Equal(position.StartTimestampUtc, decoded.StartTimestampUtc);
        Assert.Equal(position.TrackId, decoded.TrackId);
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData("***")]
    [InlineData("A")]
    public void RejectsMalformedCursor(string cursor)
    {
        Assert.False(TrackCursorCodec.TryDecode(cursor, out _));
    }

    [Fact]
    public void RejectsOverlongCursor()
    {
        Assert.False(TrackCursorCodec.TryDecode(
            new string('A', TrackCursorCodec.MaximumEncodedLength + 1),
            out _));
    }

    [Fact]
    public void RejectsCursorWithUnknownJsonMembers()
    {
        var raw = """{"Version":1,"SnapshotUtc":"2026-09-13T11:00:00+00:00","StartTimestampUtc":"2026-09-13T10:20:30+00:00","TrackId":"0199479a-f71c-7c55-a1be-11798d372ce0","Extra":1}""";
        var encoded = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(raw))
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');

        Assert.False(TrackCursorCodec.TryDecode(encoded, out _));
    }
}
