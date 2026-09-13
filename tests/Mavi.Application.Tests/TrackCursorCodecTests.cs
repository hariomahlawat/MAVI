using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

public sealed class TrackCursorCodecTests
{
    [Fact]
    public void RoundTripPreservesCanonicalUtcPosition()
    {
        var query = Query();
        var position = new TrackCursorPosition(
            new DateTimeOffset(2026, 9, 13, 11, 0, 0, TimeSpan.Zero),
            42,
            new DateTimeOffset(2026, 9, 13, 10, 20, 30, TimeSpan.Zero),
            Guid.CreateVersion7(),
            TrackCursorCodec.ComputeFilterFingerprint(query));

        var encoded = TrackCursorCodec.Encode(position);

        Assert.InRange(encoded.Length, 1, TrackCursorCodec.MaximumEncodedLength);
        Assert.True(TrackCursorCodec.TryDecode(encoded, out var decoded));
        Assert.NotNull(decoded);
        Assert.Equal(position.SnapshotUtc, decoded!.SnapshotUtc);
        Assert.Equal(position.SnapshotVisibilitySequence, decoded.SnapshotVisibilitySequence);
        Assert.Equal(position.StartTimestampUtc, decoded.StartTimestampUtc);
        Assert.Equal(position.TrackId, decoded.TrackId);
        Assert.Equal(position.FilterFingerprint, decoded.FilterFingerprint);
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
        var raw = """{"Version":2,"SnapshotUtc":"2026-09-13T11:00:00+00:00","SnapshotVisibilitySequence":42,"StartTimestampUtc":"2026-09-13T10:20:30+00:00","TrackId":"0199479a-f71c-7c55-a1be-11798d372ce0","FilterFingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","Extra":1}""";
        var encoded = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(raw))
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');

        Assert.False(TrackCursorCodec.TryDecode(encoded, out _));
    }

    [Fact]
    public void RejectsNonPositiveVisibilitySequence()
    {
        var query = Query();
        var raw = $"""{"Version":2,"SnapshotUtc":"2026-09-13T11:00:00+00:00","SnapshotVisibilitySequence":0,"StartTimestampUtc":"2026-09-13T10:20:30+00:00","TrackId":"{{Guid.CreateVersion7()}}","FilterFingerprint":"{{TrackCursorCodec.ComputeFilterFingerprint(query)}}"}""";
        var encoded = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(raw))
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');

        Assert.False(TrackCursorCodec.TryDecode(encoded, out _));
    }

    [Fact]
    public void FilterFingerprintChangesWhenSemanticFilterChanges()
    {
        var baseline = TrackCursorCodec.ComputeFilterFingerprint(Query());
        var changed = TrackCursorCodec.ComputeFilterFingerprint(
            Query() with { MinimumConfidence = 0.9 });

        Assert.NotEqual(baseline, changed);
    }

    private static TrackSearchQuery Query() => new(
        CameraId: null,
        VideoAssetId: null,
        ProcessingRunId: null,
        ObjectClass: ObjectClass.Person,
        FromUtc: null,
        ToUtc: null,
        MinimumDurationMs: null,
        MinimumConfidence: null,
        Cursor: null,
        Limit: 50);
}
