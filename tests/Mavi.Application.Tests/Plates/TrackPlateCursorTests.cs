using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests.Plates;

/// <summary>
/// The v4 plate cursor (ADR-013 §16; plan §5.4): signed like v3, pins the snapshot, the
/// capability-tagged plate identity with its coverage and — when combined — the analytics identity,
/// stays inside 1024 characters at its worst case, and is refused by every other decoder.
/// </summary>
public sealed class TrackPlateCursorTests
{
    private static readonly TrackCursorSigningKey Key =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(0, 32).Select(x => (byte)x).ToArray());
    private static readonly TrackCursorSigningKey OtherKey =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(50, 32).Select(x => (byte)x).ToArray());
    private static readonly DateTimeOffset At = new(2026, 10, 13, 12, 0, 0, TimeSpan.Zero);
    private const string Fingerprint = "521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25";
    private const string OtherFingerprint = "1111111111111111111111111111111111111111111111111111111111111111";
    private static readonly Guid Camera = Guid.Parse("0199a1f0-0000-7000-8000-00000000c001");
    private static readonly Guid Revision = Guid.Parse("0199a1f0-0000-7000-8000-00000000b001");
    private static readonly Guid Zone = Guid.Parse("0199a1f0-0000-7000-8000-00000000d001");
    private static readonly TrackPlateCoverage Coverage = new(Fingerprint, 840, 812, 20, 3, 4, 1);

    private static TrackSearchQuery PlateQuery(string text = "KA01", TrackPlateMatch match = TrackPlateMatch.Contains) =>
        new(null, null, null, ObjectClass.Vehicle, null, null, null, null, null, 50, Plate: new TrackPlateQuery(text, match));

    private static TrackSearchQuery CombinedQuery() =>
        PlateQuery() with { CameraId = Camera, Analytics = TrackAnalyticsQuery.Empty with { ZoneId = Zone } };

    private static TrackPlateCursorPosition Position(TrackSearchQuery query, TrackAnalyticsPinnedIdentity? identity = null,
        TrackAnalyticsCoverage? analyticsCoverage = null) =>
        new(
            new TrackCursorPosition(At, 42, At.AddMinutes(-5), Guid.CreateVersion7(),
                TrackCursorCodec.ComputePlateFilterFingerprint(query, Fingerprint, identity, Key)),
            Fingerprint,
            Coverage,
            identity,
            analyticsCoverage);

    [Fact]
    public void APlateOnlyCursorRoundTrips()
    {
        var position = Position(PlateQuery());
        var encoded = TrackCursorCodec.EncodePlate(position, Key);

        Assert.True(TrackCursorCodec.TryDecodePlate(encoded, Key, out var decoded));
        Assert.Equal(position.Position, decoded!.Position);
        Assert.Equal(Fingerprint, decoded.PlateIdentityFingerprint);
        Assert.Equal(Coverage, decoded.PlateCoverage);
        Assert.Null(decoded.AnalyticsIdentity);
        Assert.Null(decoded.AnalyticsCoverage);
        Assert.False(decoded.IsAnalytic);
    }

    [Fact]
    public void ACombinedCursorCarriesTheAnalyticsIdentityAndCoverage()
    {
        var identity = new TrackAnalyticsPinnedIdentity(Camera, Revision, "scene-analytics-v1");
        var analytics = new TrackAnalyticsCoverage(Revision, "scene-analytics-v1", 3, 1, 0, 0, 0, 0, 27, 2);
        var position = Position(CombinedQuery(), identity, analytics);

        Assert.True(TrackCursorCodec.TryDecodePlate(TrackCursorCodec.EncodePlate(position, Key), Key, out var decoded));
        Assert.Equal(identity, decoded!.AnalyticsIdentity);
        Assert.Equal(analytics, decoded.AnalyticsCoverage);
        Assert.Equal(Coverage, decoded.PlateCoverage);
    }

    [Fact]
    public void ANeverConfiguredRevisionIsPinnedAsNull()
    {
        var identity = new TrackAnalyticsPinnedIdentity(Camera, null, "scene-analytics-v1");
        var analytics = new TrackAnalyticsCoverage(null, "scene-analytics-v1", 0, 0, 0, 2, 0, 0, 0, 0);
        var position = Position(CombinedQuery(), identity, analytics);

        Assert.True(TrackCursorCodec.TryDecodePlate(TrackCursorCodec.EncodePlate(position, Key), Key, out var decoded));
        Assert.Null(decoded!.AnalyticsIdentity!.SceneRevisionId);
    }

    /// <summary>
    /// The worst case: every count at its maximum, the longest algorithm version the grammar allows and
    /// the analytics pin present. The encoded length is the contract bound (plan §5.4).
    /// </summary>
    [Fact]
    public void TheWorstCaseCursorFitsTheBound()
    {
        var version = "scene-analytics-v" + new string('9', 4);
        var longest = TrackCursorCodec.PlateMaximumEncodedLength;
        var max = int.MaxValue;
        var identity = new TrackAnalyticsPinnedIdentity(Camera, Revision, version.PadRight(64, '9'));
        var analytics = new TrackAnalyticsCoverage(Revision, identity.AlgorithmVersion, max, max, max, max, max, max, max, max);
        var query = CombinedQuery();
        var position = new TrackPlateCursorPosition(
            new TrackCursorPosition(
                new DateTimeOffset(2026, 12, 31, 23, 59, 59, TimeSpan.Zero).AddTicks(9_999_999),
                long.MaxValue,
                new DateTimeOffset(2026, 12, 31, 23, 59, 59, TimeSpan.Zero).AddTicks(9_999_999),
                Guid.CreateVersion7(),
                TrackCursorCodec.ComputePlateFilterFingerprint(query, Fingerprint, identity, Key)),
            Fingerprint,
            // The plate counts must partition the scope, so the worst case splits int.MaxValue.
            new TrackPlateCoverage(Fingerprint, max, max - 4, 1, 1, 1, 1),
            identity,
            analytics);

        var encoded = TrackCursorCodec.EncodePlate(position, Key);

        Assert.InRange(encoded.Length, 1, longest);
        Assert.True(TrackCursorCodec.TryDecodePlate(encoded, Key, out _));
    }

    [Fact]
    public void ATamperedForeignKeyedOrMalformedCursorIsRefused()
    {
        var encoded = TrackCursorCodec.EncodePlate(Position(PlateQuery()), Key);
        var flipped = (encoded[40] == 'A' ? 'B' : 'A') + "";
        var tampered = encoded[..40] + flipped + encoded[41..];

        Assert.False(TrackCursorCodec.TryDecodePlate(tampered, Key, out _));
        Assert.False(TrackCursorCodec.TryDecodePlate(encoded, OtherKey, out _));
        Assert.False(TrackCursorCodec.TryDecodePlate(encoded + "A", Key, out _));
        Assert.False(TrackCursorCodec.TryDecodePlate(new string('A', TrackCursorCodec.PlateMaximumEncodedLength + 1), Key, out _));
        Assert.False(TrackCursorCodec.TryDecodePlate("not a cursor", Key, out _));
        Assert.False(TrackCursorCodec.TryDecodePlate("", Key, out _));
    }

    [Fact]
    public void EachVersionIsRefusedByEveryOtherDecoder()
    {
        var v4 = TrackCursorCodec.EncodePlate(Position(PlateQuery()), Key);
        Assert.False(TrackCursorCodec.TryDecode(v4, out _));
        Assert.False(TrackCursorCodec.TryDecodeAnalytic(v4, Key, out _));

        var ordinary = PlateQuery() with { Plate = null };
        var v2 = TrackCursorCodec.Encode(new TrackCursorPosition(At, 42, At, Guid.CreateVersion7(),
            TrackCursorCodec.ComputeFilterFingerprint(ordinary)));
        Assert.False(TrackCursorCodec.TryDecodePlate(v2, Key, out _));

        var analytic = ordinary with { CameraId = Camera, Analytics = TrackAnalyticsQuery.Empty with { ZoneId = Zone } };
        var identity = new TrackAnalyticsPinnedIdentity(Camera, Revision, "scene-analytics-v1");
        var v3 = TrackCursorCodec.EncodeAnalytic(new TrackAnalyticsCursorPosition(
                new TrackCursorPosition(At, 42, At, Guid.CreateVersion7(), TrackCursorCodec.ComputeAnalyticFilterFingerprint(analytic, identity)),
                identity,
                new TrackAnalyticsCoverage(Revision, "scene-analytics-v1", 1, 0, 0, 0, 0, 0, 1, 0)),
            Key);
        Assert.False(TrackCursorCodec.TryDecodePlate(v3, Key, out _));
    }

    [Theory]
    // An unknown capability tag: a later derived predicate joins the list in code, never by accident.
    [InlineData("""{"K":"person-attributes","F":"521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25","G":[1,1,0,0,0,0]}""")]
    // Plate counts that do not partition the scope.
    [InlineData("""{"K":"plates","F":"521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25","G":[5,1,1,0,0,0]}""")]
    // A short count list, and a negative count.
    [InlineData("""{"K":"plates","F":"521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25","G":[1,1,0,0,0]}""")]
    [InlineData("""{"K":"plates","F":"521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25","G":[0,1,-1,0,0,0]}""")]
    // A fingerprint that is not 64 lower-case hex.
    [InlineData("""{"K":"plates","F":"521D596506F98622A5D4E49E8B8A6F7D51C0EC7D8199F257EF097E4DB723EB25","G":[1,1,0,0,0,0]}""")]
    public void AnAuthenticatedPayloadWithAnInvalidPinIsStillRefused(string pin)
    {
        var payload = $$"""{"V":4,"S":"2026-10-13T12:00:00+00:00","Q":42,"T":"2026-10-13T11:55:00+00:00","I":"{{Guid.CreateVersion7()}}","F":"{{Fingerprint}}","D":[{{pin}}]}""";
        Assert.False(TrackCursorCodec.TryDecodePlate(Sign(payload), Key, out _));
    }

    [Fact]
    public void ASignedHandWrittenPayloadOfTheRightShapeIsAccepted()
    {
        // The control for the theory above: the same envelope with a valid pin decodes.
        var payload = $$"""{"V":4,"S":"2026-10-13T12:00:00+00:00","Q":42,"T":"2026-10-13T11:55:00+00:00","I":"{{Guid.CreateVersion7()}}","F":"{{Fingerprint}}","D":[{"K":"plates","F":"{{Fingerprint}}","G":[1,1,0,0,0,0]}]}""";
        Assert.True(TrackCursorCodec.TryDecodePlate(Sign(payload), Key, out var decoded));
        Assert.Equal(1, decoded!.PlateCoverage.VehicleTracksInScope);
    }

    [Fact]
    public void AnUnknownMemberOrTwoPinsAreRefused()
    {
        var pin = $$"""{"K":"plates","F":"{{Fingerprint}}","G":[1,1,0,0,0,0]}""";
        var extra = $$"""{"V":4,"S":"2026-10-13T12:00:00+00:00","Q":42,"T":"2026-10-13T11:55:00+00:00","I":"{{Guid.CreateVersion7()}}","F":"{{Fingerprint}}","D":[{{pin}}],"X":1}""";
        var twice = $$"""{"V":4,"S":"2026-10-13T12:00:00+00:00","Q":42,"T":"2026-10-13T11:55:00+00:00","I":"{{Guid.CreateVersion7()}}","F":"{{Fingerprint}}","D":[{{pin}},{{pin}}]}""";
        Assert.False(TrackCursorCodec.TryDecodePlate(Sign(extra), Key, out _));
        Assert.False(TrackCursorCodec.TryDecodePlate(Sign(twice), Key, out _));
    }

    // --- Filter fingerprint -------------------------------------------------------------------

    [Fact]
    public void TheFingerprintCoversTextMatchIdentityAndAnalytics()
    {
        var baseline = TrackCursorCodec.ComputePlateFilterFingerprint(PlateQuery(), Fingerprint, null, Key);

        Assert.Equal(baseline, TrackCursorCodec.ComputePlateFilterFingerprint(PlateQuery(), Fingerprint, null, Key));
        Assert.NotEqual(baseline, TrackCursorCodec.ComputePlateFilterFingerprint(PlateQuery("KA02"), Fingerprint, null, Key));
        Assert.NotEqual(baseline, TrackCursorCodec.ComputePlateFilterFingerprint(PlateQuery(match: TrackPlateMatch.Prefix), Fingerprint, null, Key));
        Assert.NotEqual(baseline, TrackCursorCodec.ComputePlateFilterFingerprint(PlateQuery(), OtherFingerprint, null, Key));
        Assert.NotEqual(baseline, TrackCursorCodec.ComputePlateFilterFingerprint(
            PlateQuery() with { MinimumConfidence = 0.5 }, Fingerprint, null, Key));

        var identity = new TrackAnalyticsPinnedIdentity(Camera, Revision, "scene-analytics-v1");
        var combined = TrackCursorCodec.ComputePlateFilterFingerprint(CombinedQuery(), Fingerprint, identity, Key);
        Assert.NotEqual(combined, TrackCursorCodec.ComputePlateFilterFingerprint(
            CombinedQuery(), Fingerprint, identity with { SceneRevisionId = Guid.CreateVersion7() }, Key));
    }

    [Fact]
    public void ThePlateFingerprintIsKeyedSoACursorDoesNotRevealTheText()
    {
        // The fingerprint travels in the (readable) base64 payload. Unkeyed, a short plate text could be
        // recovered by enumerating 36^n candidates offline; keyed, the same query fingerprints differently
        // under another installation's key and cannot be recomputed without it.
        var mine = TrackCursorCodec.ComputePlateFilterFingerprint(PlateQuery(), Fingerprint, null, Key);
        var theirs = TrackCursorCodec.ComputePlateFilterFingerprint(PlateQuery(), Fingerprint, null, OtherKey);

        Assert.NotEqual(mine, theirs);
        Assert.Matches("^[0-9a-f]{64}$", mine);
        var encoded = TrackCursorCodec.EncodePlate(Position(PlateQuery()), Key);
        var payload = Convert.FromBase64String(encoded.Replace('-', '+').Replace('_', '/').PadRight((encoded.Length + 3) / 4 * 4, '='));
        Assert.DoesNotContain("KA01", Encoding.UTF8.GetString(payload), StringComparison.Ordinal);
    }

    [Fact]
    public void APlateQueryIsNeverFingerprintedByTheOlderCursors()
    {
        Assert.Throws<ArgumentException>(() => TrackCursorCodec.ComputeFilterFingerprint(PlateQuery()));
        Assert.Throws<ArgumentException>(() => TrackCursorCodec.ComputeAnalyticFilterFingerprint(
            CombinedQuery(), new TrackAnalyticsPinnedIdentity(Camera, Revision, "scene-analytics-v1")));
        Assert.Throws<ArgumentException>(() => TrackCursorCodec.ComputePlateFilterFingerprint(
            PlateQuery(), Fingerprint, new TrackAnalyticsPinnedIdentity(Camera, Revision, "scene-analytics-v1"), Key));
        Assert.Throws<ArgumentException>(() => TrackCursorCodec.ComputePlateFilterFingerprint(CombinedQuery(), Fingerprint, null, Key));
    }

    [Fact]
    public void AnOrdinaryFingerprintIsUnchangedByTheStage4Grammar()
    {
        // The v2 fingerprint of a query without a plate predicate is byte-for-byte the pre-Stage-4 one:
        // the plate member is not part of the v2 payload at all.
        var ordinary = PlateQuery() with { Plate = null };
        var payload = JsonSerializer.SerializeToUtf8Bytes(new
        {
            CameraId = (Guid?)null,
            VideoAssetId = (Guid?)null,
            ProcessingRunId = (Guid?)null,
            ObjectClass = (ObjectClass?)ObjectClass.Vehicle,
            FromUtc = (DateTimeOffset?)null,
            ToUtc = (DateTimeOffset?)null,
            MinimumDurationMs = (long?)null,
            MinimumConfidence = (double?)null,
        });
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(payload)), TrackCursorCodec.ComputeFilterFingerprint(ordinary));
    }

    [Fact]
    public void EachPurposeUsesItsOwnDerivedKey()
    {
        // The envelope is authenticated with HMAC(key, "…/mac"); a cursor signed with the raw key (as v4 did
        // before the derivation) or with the fingerprint key is refused, so neither purpose's output can stand
        // in for the other's.
        var payload = $$"""{"V":4,"S":"2026-10-13T12:00:00+00:00","Q":42,"T":"2026-10-13T11:55:00+00:00","I":"{{Guid.CreateVersion7()}}","F":"{{Fingerprint}}","D":[{"K":"plates","F":"{{Fingerprint}}","G":[1,1,0,0,0,0]}]}""";
        var raw = Enumerable.Range(0, 32).Select(x => (byte)x).ToArray();

        Assert.True(TrackCursorCodec.TryDecodePlate(Sign(payload), Key, out _));
        Assert.False(TrackCursorCodec.TryDecodePlate(SignWith(raw, payload), Key, out _));
        Assert.False(TrackCursorCodec.TryDecodePlate(SignWith(Derive(raw, TrackCursorCodec.PlateFingerprintKeyLabel), payload), Key, out _));

        // The fingerprint is keyed by the fingerprint key, never by the raw key or the MAC key.
        var fingerprint = TrackCursorCodec.ComputePlateFilterFingerprint(PlateQuery(), Fingerprint, null, Key);
        Assert.NotEqual(Derive(raw, TrackCursorCodec.PlateMacKeyLabel), Derive(raw, TrackCursorCodec.PlateFingerprintKeyLabel));
        Assert.Matches("^[0-9a-f]{64}$", fingerprint);
    }

    private static byte[] Derive(byte[] key, string label) => HMACSHA256.HashData(key, Encoding.ASCII.GetBytes(label));

    private static string Sign(string payload) =>
        SignWith(Derive(Enumerable.Range(0, 32).Select(x => (byte)x).ToArray(), TrackCursorCodec.PlateMacKeyLabel), payload);

    private static string SignWith(byte[] macKey, string payload)
    {
        var bytes = Encoding.UTF8.GetBytes(payload);
        var envelope = new byte[32 + bytes.Length];
        HMACSHA256.HashData(macKey, bytes, envelope.AsSpan(0, 32));
        bytes.CopyTo(envelope, 32);
        return Convert.ToBase64String(envelope).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    }
}
