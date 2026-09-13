using Mavi.Application.Modules.Intelligence;

namespace Mavi.Application.Tests;

public sealed class TrackCursorCodecTests
{
    [Fact]
    public void RoundTripPreservesCanonicalUtcPosition()
    {
        var codec = new TrackCursorCodec();
        var position = new TrackCursorPosition(
            new DateTimeOffset(2026, 9, 13, 10, 20, 30, TimeSpan.Zero),
            Guid.CreateVersion7());

        var encoded = codec.Encode(position);

        Assert.True(codec.TryDecode(encoded, out var decoded));
        Assert.NotNull(decoded);
        Assert.Equal(position.StartTimestampUtc, decoded!.StartTimestampUtc);
        Assert.Equal(position.TrackId, decoded.TrackId);
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData("***")]
    [InlineData("A")]
    public void RejectsMalformedCursor(string cursor)
    {
        var codec = new TrackCursorCodec();

        Assert.False(codec.TryDecode(cursor, out _));
    }

    [Fact]
    public void RejectsOverlongCursor()
    {
        var codec = new TrackCursorCodec();

        Assert.False(codec.TryDecode(
            new string('A', TrackCursorCodec.MaximumEncodedLength + 1),
            out _));
    }

    [Fact]
    public void RejectsCursorWithUnknownJsonMembers()
    {
        var raw = """{"Version":1,"StartTimestampUtc":"2026-09-13T10:20:30+00:00","TrackId":"0199479a-f71c-7c55-a1be-11798d372ce0","Extra":1}""";
        var encoded = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(raw))
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');

        Assert.False(new TrackCursorCodec().TryDecode(encoded, out _));
    }
}
