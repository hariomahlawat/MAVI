using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

/// <summary>
/// The analytic (v3) cursor: authenticated before it is trusted, bounded in size, and
/// separate from the ordinary v2 cursor in both directions (plan §S, ADR-011 decision 6).
/// </summary>
public sealed class TrackAnalyticCursorCodecTests
{
    private static readonly TrackCursorSigningKey Key =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(0, 32).Select(x => (byte)x).ToArray());

    private static readonly TrackCursorSigningKey OtherKey =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(100, 32).Select(x => (byte)x).ToArray());

    private static readonly Guid Camera = Guid.Parse("0199a1f0-0000-7000-8000-00000000c001");
    private static readonly Guid Revision = Guid.Parse("0199a1f0-0000-7000-8000-00000000b001");
    private static readonly Guid Zone = Guid.Parse("0199a1f0-0000-7000-8000-00000000d001");

    private static TrackSearchQuery Query() => new(
        Camera, null, null, ObjectClass.Person, null, null, null, null, null, 50,
        TrackAnalyticsQuery.Empty with { ZoneId = Zone, MinDwellMs = 1_000 });

    private static TrackAnalyticsPinnedIdentity Identity(Guid? revision = null) =>
        new(Camera, revision ?? Revision, "scene-analytics-v1");

    private static TrackAnalyticsCoverage Coverage(TrackAnalyticsPinnedIdentity identity) =>
        new(identity.SceneRevisionId, identity.AlgorithmVersion, 3, 1, 0, 0, 1, 2, 27, 2);

    private static TrackAnalyticsCursorPosition Cursor(
        TrackAnalyticsPinnedIdentity? identity = null,
        TrackAnalyticsCoverage? coverage = null)
    {
        var pinned = identity ?? Identity();
        return new TrackAnalyticsCursorPosition(
            new TrackCursorPosition(
                new DateTimeOffset(2026, 9, 21, 11, 0, 0, TimeSpan.Zero),
                42,
                new DateTimeOffset(2026, 9, 21, 10, 20, 30, TimeSpan.Zero),
                Guid.CreateVersion7(),
                TrackCursorCodec.ComputeAnalyticFilterFingerprint(Query(), pinned)),
            pinned,
            coverage ?? Coverage(pinned));
    }

    [Fact]
    public void RoundTripPreservesPositionIdentityAndCoverage()
    {
        var cursor = Cursor();

        var encoded = TrackCursorCodec.EncodeAnalytic(cursor, Key);

        Assert.InRange(encoded.Length, 1, TrackCursorCodec.AnalyticMaximumEncodedLength);
        Assert.True(TrackCursorCodec.TryDecodeAnalytic(encoded, Key, out var decoded));
        Assert.Equal(cursor.Position, decoded!.Position);
        Assert.Equal(cursor.Identity, decoded.Identity);
        Assert.Equal(cursor.Coverage, decoded.Coverage);
    }

    [Fact]
    public void ANeverConfiguredCameraPinsANullRevision()
    {
        var identity = new TrackAnalyticsPinnedIdentity(Camera, null, "scene-analytics-v1");
        var coverage = new TrackAnalyticsCoverage(null, "scene-analytics-v1", 0, 0, 0, 4, 0, 0, 0, 0);
        var cursor = Cursor(identity, coverage);

        Assert.True(TrackCursorCodec.TryDecodeAnalytic(TrackCursorCodec.EncodeAnalytic(cursor, Key), Key, out var decoded));
        Assert.Null(decoded!.Identity.SceneRevisionId);
        Assert.Equal(4, decoded.Coverage.NotConfiguredRuns);
        Assert.False(decoded.Coverage.Complete);
    }

    [Fact]
    public void ATamperedPayloadIsRejected()
    {
        var encoded = TrackCursorCodec.EncodeAnalytic(Cursor(), Key);
        var envelope = FromBase64Url(encoded);

        // Flip one bit of the coverage counts, deep inside the payload. Without the MAC
        // this would still be perfectly valid JSON that claims different coverage.
        var payloadText = Encoding.UTF8.GetString(envelope, 32, envelope.Length - 32);
        var tamperedText = payloadText.Replace("\"G\":[3,", "\"G\":[9,", StringComparison.Ordinal);
        Assert.NotEqual(payloadText, tamperedText);
        var tampered = envelope[..32].Concat(Encoding.UTF8.GetBytes(tamperedText)).ToArray();

        Assert.False(TrackCursorCodec.TryDecodeAnalytic(ToBase64Url(tampered), Key, out var position));
        Assert.Null(position);
    }

    [Fact]
    public void ATamperedMacIsRejected()
    {
        var envelope = FromBase64Url(TrackCursorCodec.EncodeAnalytic(Cursor(), Key));
        envelope[5] ^= 0x01;

        Assert.False(TrackCursorCodec.TryDecodeAnalytic(ToBase64Url(envelope), Key, out _));
    }

    [Fact]
    public void ACursorSignedUnderAnotherKeyIsRejected()
    {
        var encoded = TrackCursorCodec.EncodeAnalytic(Cursor(), Key);

        // Key rotation invalidates outstanding v3 cursors and nothing else.
        Assert.False(TrackCursorCodec.TryDecodeAnalytic(encoded, OtherKey, out _));
        Assert.True(TrackCursorCodec.TryDecodeAnalytic(encoded, Key, out _));
    }

    [Fact]
    public void AForgedPayloadWithNoValidMacIsNeverParsed()
    {
        // A structurally perfect payload prefixed with a zero MAC. If the codec parsed
        // before verifying, this would decode; it must not.
        var forged = Encoding.UTF8.GetBytes(
            """{"V":3,"S":"2026-09-21T11:00:00+00:00","Q":42,"T":"2026-09-21T10:20:30+00:00","I":"0199479a-f71c-7c55-a1be-11798d372ce0","F":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","C":"0199a1f0-0000-7000-8000-00000000c001","R":"0199a1f0-0000-7000-8000-00000000b001","A":"scene-analytics-v1","G":[1,0,0,0,0,0,1,0]}""");
        var envelope = new byte[32].Concat(forged).ToArray();

        Assert.False(TrackCursorCodec.TryDecodeAnalytic(ToBase64Url(envelope), Key, out _));
    }

    [Fact]
    public void TheTwoEnvelopesRefuseEachOther()
    {
        var ordinary = TrackCursorCodec.Encode(Cursor().Position);
        var analytic = TrackCursorCodec.EncodeAnalytic(Cursor(), Key);

        Assert.False(TrackCursorCodec.TryDecodeAnalytic(ordinary, Key, out _));
        Assert.False(TrackCursorCodec.TryDecode(analytic, out _));
        // And the ordinary path is exactly what it was.
        Assert.True(TrackCursorCodec.TryDecode(ordinary, out _));
        Assert.InRange(ordinary.Length, 1, TrackCursorCodec.MaximumEncodedLength);
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData("***")]
    [InlineData("AAAA")]
    public void MalformedAnalyticCursorsAreRejected(string cursor) =>
        Assert.False(TrackCursorCodec.TryDecodeAnalytic(cursor, Key, out _));

    [Fact]
    public void RejectsOverlongAnalyticCursor() =>
        Assert.False(TrackCursorCodec.TryDecodeAnalytic(
            new string('A', TrackCursorCodec.AnalyticMaximumEncodedLength + 1), Key, out _));

    /// <summary>
    /// The worst case the codec can be asked to carry: every count at its maximum, the
    /// longest algorithm version the contract allows, a pinned revision present. It must
    /// fit the published bound with room, so the coverage snapshot cannot grow without
    /// somebody noticing here.
    /// </summary>
    [Fact]
    public void WorstCaseAnalyticCursorStaysInsideThePublishedEnvelope()
    {
        var longestVersion = "scene-analytics-v9999";
        var identity = new TrackAnalyticsPinnedIdentity(Camera, Revision, longestVersion);
        var coverage = new TrackAnalyticsCoverage(
            Revision, longestVersion,
            int.MaxValue, int.MaxValue, int.MaxValue, int.MaxValue,
            int.MaxValue, int.MaxValue, int.MaxValue, int.MaxValue);
        var cursor = new TrackAnalyticsCursorPosition(
            new TrackCursorPosition(
                new DateTimeOffset(2026, 12, 31, 23, 59, 59, 999, TimeSpan.Zero).AddTicks(9999),
                long.MaxValue,
                new DateTimeOffset(2026, 12, 31, 23, 59, 59, 999, TimeSpan.Zero).AddTicks(9999),
                Guid.CreateVersion7(),
                new string('f', 64)),
            identity,
            coverage);

        var encoded = TrackCursorCodec.EncodeAnalytic(cursor, Key);

        Assert.InRange(encoded.Length, 1, TrackCursorCodec.AnalyticMaximumEncodedLength);
        Assert.True(TrackCursorCodec.TryDecodeAnalytic(encoded, Key, out var decoded));
        Assert.Equal(coverage, decoded!.Coverage);
    }

    [Fact]
    public void AnalyticFingerprintSeesThePinnedPairAndCanonicalForm()
    {
        var baseline = TrackCursorCodec.ComputeAnalyticFilterFingerprint(Query(), Identity());

        // Same filters, different pinned revision: a different search.
        var otherRevision = TrackCursorCodec.ComputeAnalyticFilterFingerprint(Query(), Identity(Guid.CreateVersion7()));
        Assert.NotEqual(baseline, otherRevision);

        // Same filters, different engine version: a different search.
        var otherVersion = TrackCursorCodec.ComputeAnalyticFilterFingerprint(
            Query(), Identity() with { AlgorithmVersion = "scene-analytics-v2" });
        Assert.NotEqual(baseline, otherVersion);

        // An explicit `dwelled` and an omitted relation are the same search.
        var explicitDwelled = Query() with
        {
            Analytics = Query().Analytics! with { ZoneRelation = TrackZoneRelation.Dwelled },
        };
        Assert.Equal(baseline, TrackCursorCodec.ComputeAnalyticFilterFingerprint(explicitDwelled, Identity()));

        // A changed analytic predicate is a different search.
        var changed = Query() with { Analytics = Query().Analytics! with { MinDwellMs = 2_000 } };
        Assert.NotEqual(baseline, TrackCursorCodec.ComputeAnalyticFilterFingerprint(changed, Identity()));

        // And it is not the ordinary fingerprint of the same base filters.
        Assert.NotEqual(baseline, TrackCursorCodec.ComputeFilterFingerprint(Query()));
    }

    [Fact]
    public void AnalyticFingerprintRequiresAnAnalyticQuery() =>
        Assert.Throws<ArgumentException>(() =>
            TrackCursorCodec.ComputeAnalyticFilterFingerprint(Query() with { Analytics = null }, Identity()));

    private static byte[] FromBase64Url(string value)
    {
        var base64 = value.Replace('-', '+').Replace('_', '/');
        var padding = base64.Length % 4;
        if (padding != 0) base64 = base64.PadRight(base64.Length + (4 - padding), '=');
        return Convert.FromBase64String(base64);
    }

    private static string ToBase64Url(byte[] bytes) =>
        Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}
