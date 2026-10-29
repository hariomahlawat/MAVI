using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests.VisualAttributes;

/// <summary>
/// PoC S5 attribute search: the predicate grammar and canonical order (E6), the v4 cursor's <c>attributes</c> pin
/// (E5: signed, pins identity and coverage, refused by every other decoder, inside 1024 characters at its worst
/// case) and the committed zero-shot release as the platform reads it.
/// </summary>
public sealed class TrackAttributeSearchTests
{
    private static readonly TrackCursorSigningKey Key =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(0, 32).Select(x => (byte)x).ToArray());
    private static readonly TrackCursorSigningKey OtherKey =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(50, 32).Select(x => (byte)x).ToArray());
    private static readonly DateTimeOffset At = new(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
    private const string Fingerprint = "aa9a83bc423dd2b0a0214cd51f5e469c80566fbf253087b79af5e46c7d92d82a";
    private static readonly Guid Camera = Guid.Parse("0199a1f0-0000-7000-8000-00000000c001");
    private static readonly Guid Revision = Guid.Parse("0199a1f0-0000-7000-8000-00000000b001");
    private static readonly Guid Zone = Guid.Parse("0199a1f0-0000-7000-8000-00000000d001");

    private static TrackAttributeQuery Parse(params string[] raw)
    {
        Assert.True(TrackAttributeQueryRules.TryParse(raw, out var query));
        return query!;
    }

    private static TrackSearchQuery Query(TrackAttributeQuery attributes) =>
        new(null, null, null, ObjectClass.Person, null, null, null, null, null, 50, Attributes: attributes);

    private static TrackAttributeCoverage Coverage(int predicates) =>
        new(Fingerprint, "zero-shot, Development", 40, 30, 4, 6, Enumerable.Range(1, predicates).ToArray());

    private static TrackAttributeCursorPosition Position(TrackSearchQuery query, TrackAnalyticsPinnedIdentity? identity = null,
        TrackAnalyticsCoverage? analytics = null) =>
        new(
            new TrackCursorPosition(At, 42, At.AddMinutes(-5), Guid.CreateVersion7(),
                TrackCursorCodec.ComputeAttributeFilterFingerprint(query, Fingerprint, identity, Key)),
            Fingerprint,
            Coverage(query.Attributes!.Predicates.Count),
            identity,
            analytics);

    // --- Grammar ---------------------------------------------------------------------------------

    [Fact]
    public void PredicatesAreCanonicalSoAnyOrderIsOneSearch()
    {
        var forward = Parse("person-upper-colour:red", "person-carried-bag:present");
        var reversed = Parse("person-carried-bag:present", "person-upper-colour:red");

        Assert.Equal(["person-carried-bag:present", "person-upper-colour:red"], forward.Wire);
        Assert.Equal(forward.Wire, reversed.Wire);
        Assert.Equal(
            TrackCursorCodec.ComputeAttributeFilterFingerprint(Query(forward), Fingerprint, null, Key),
            TrackCursorCodec.ComputeAttributeFilterFingerprint(Query(reversed), Fingerprint, null, Key));
    }

    [Theory]
    [InlineData("person-upper-colour")]
    [InlineData("person-upper-colour:")]
    [InlineData(":red")]
    [InlineData("person-upper-colour:red:dark")]
    [InlineData("Person-upper-colour:red")]
    [InlineData("person-upper-colour:Red")]
    [InlineData("person--upper:red")]
    [InlineData("person-upper-:red")]
    [InlineData("1person:red")]
    public void AMalformedPredicateIsRefused(string raw) =>
        Assert.False(TrackAttributeQueryRules.TryParse([raw], out _));

    [Fact]
    public void ARepeatedTypeOrMoreThanFourPredicatesIsRefused()
    {
        Assert.False(TrackAttributeQueryRules.TryParse(["person-upper-colour:red", "person-upper-colour:blue"], out _));
        Assert.False(TrackAttributeQueryRules.TryParse(["a:b", "c:d", "e:f", "g:h", "i:j"], out _));
        Assert.True(TrackAttributeQueryRules.TryParse(["a:b", "c:d", "e:f", "g:h"], out _));
        Assert.True(TrackAttributeQueryRules.TryParse(null, out var none));
        Assert.Null(none);
    }

    [Fact]
    public void ThePredicatesMustNameValuesOfTheBoundSchemaOfOneClass()
    {
        var schema = new AttributeSchemaDefinition("s", "1.0.0", new string('a', 64),
        [
            new AttributeDefinition("person-upper-colour", "person-attributes", "person", ["blue", "red"]),
            new AttributeDefinition("vehicle-colour", "vehicle-attributes", "vehicle", ["red", "white"]),
        ]);

        Assert.True(TrackAttributeQueryRules.TryResolveObjectClass(Parse("vehicle-colour:white"), schema, out var vehicle));
        Assert.Equal(ObjectClass.Vehicle, vehicle);
        Assert.True(TrackAttributeQueryRules.TryResolveObjectClass(Parse("person-upper-colour:red"), schema, out var person));
        Assert.Equal(ObjectClass.Person, person);
        Assert.False(TrackAttributeQueryRules.TryResolveObjectClass(Parse("person-upper-colour:white"), schema, out _));
        Assert.False(TrackAttributeQueryRules.TryResolveObjectClass(Parse("person-headwear:present"), schema, out _));
        Assert.False(TrackAttributeQueryRules.TryResolveObjectClass(Parse("person-upper-colour:red", "vehicle-colour:red"), schema, out _));
    }

    // --- Cursor ----------------------------------------------------------------------------------

    [Fact]
    public void AnAttributeCursorRoundTripsItsIdentityAndCoverage()
    {
        var query = Query(Parse("person-upper-colour:red", "person-carried-bag:present"));
        var position = Position(query);

        var encoded = TrackCursorCodec.EncodeAttribute(position, Key);

        Assert.True(TrackCursorCodec.TryDecodeAttribute(encoded, Key, "zero-shot, Development", out var decoded));
        Assert.Equal(position.Position, decoded!.Position);
        Assert.Equal(Fingerprint, decoded.AttributeIdentityFingerprint);
        Assert.Equal(position.AttributeCoverage.Unknown, decoded.AttributeCoverage.Unknown);
        Assert.Equal((40, 30, 4, 6), (decoded.AttributeCoverage.TracksInScope, decoded.AttributeCoverage.Analysed,
            decoded.AttributeCoverage.Unavailable, decoded.AttributeCoverage.NotAnalysed));
        Assert.False(decoded.IsAnalytic);
    }

    [Fact]
    public void ACombinedCursorPinsTheAnalyticsIdentityToo()
    {
        var query = Query(Parse("person-upper-colour:red")) with { CameraId = Camera, Analytics = TrackAnalyticsQuery.Empty with { ZoneId = Zone } };
        var identity = new TrackAnalyticsPinnedIdentity(Camera, Revision, "scene-analytics-v1");
        var analytics = new TrackAnalyticsCoverage(Revision, "scene-analytics-v1", 1, 0, 0, 0, 0, 0, 5, 0);

        var encoded = TrackCursorCodec.EncodeAttribute(Position(query, identity, analytics), Key);

        Assert.True(TrackCursorCodec.TryDecodeAttribute(encoded, Key, null, out var decoded));
        Assert.Equal(identity, decoded!.AnalyticsIdentity);
        Assert.Equal(analytics, decoded.AnalyticsCoverage);
        // The fingerprint covers the analytics identity: another camera is another search.
        Assert.NotEqual(
            TrackCursorCodec.ComputeAttributeFilterFingerprint(query, Fingerprint, identity, Key),
            TrackCursorCodec.ComputeAttributeFilterFingerprint(query, Fingerprint, identity with { CameraId = Guid.CreateVersion7() }, Key));
    }

    [Fact]
    public void TheFingerprintCoversTheValueAndThePinnedIdentity()
    {
        var red = Query(Parse("person-upper-colour:red"));
        var blue = Query(Parse("person-upper-colour:blue"));
        var at = TrackCursorCodec.ComputeAttributeFilterFingerprint(red, Fingerprint, null, Key);

        Assert.NotEqual(at, TrackCursorCodec.ComputeAttributeFilterFingerprint(blue, Fingerprint, null, Key));
        Assert.NotEqual(at, TrackCursorCodec.ComputeAttributeFilterFingerprint(red, new string('1', 64), null, Key));
        Assert.NotEqual(at, TrackCursorCodec.ComputeAttributeFilterFingerprint(red, Fingerprint, null, OtherKey));
    }

    [Fact]
    public void TheWorstCaseAttributeCursorFitsTheV4Bound()
    {
        var max = int.MaxValue;
        var version = ("scene-analytics-v" + new string('9', 4)).PadRight(64, '9');
        var identity = new TrackAnalyticsPinnedIdentity(Camera, Revision, version);
        var analytics = new TrackAnalyticsCoverage(Revision, version, max, max, max, max, max, max, max, max);
        var query = Query(Parse("a-a:b", "c-c:d", "e-e:f", "g-g:h")) with { CameraId = Camera, Analytics = TrackAnalyticsQuery.Empty with { ZoneId = Zone } };
        var end = new DateTimeOffset(2026, 12, 31, 23, 59, 59, TimeSpan.Zero).AddTicks(9_999_999);
        var position = new TrackAttributeCursorPosition(
            new TrackCursorPosition(end, long.MaxValue, end, Guid.CreateVersion7(),
                TrackCursorCodec.ComputeAttributeFilterFingerprint(query, Fingerprint, identity, Key)),
            Fingerprint,
            // The counts must partition the scope, so the worst case splits int.MaxValue.
            new TrackAttributeCoverage(Fingerprint, null, max, max - 2, 1, 1, [max - 2, max - 2, max - 2, max - 2]),
            identity,
            analytics);

        var encoded = TrackCursorCodec.EncodeAttribute(position, Key);

        Assert.InRange(encoded.Length, 1, TrackCursorCodec.PlateMaximumEncodedLength);
        Assert.True(TrackCursorCodec.TryDecodeAttribute(encoded, Key, null, out _));
    }

    [Fact]
    public void ATamperedForeignKeyedOrInconsistentCursorIsRefused()
    {
        var query = Query(Parse("person-upper-colour:red"));
        var encoded = TrackCursorCodec.EncodeAttribute(Position(query), Key);
        var tampered = encoded[..40] + (encoded[40] == 'A' ? 'B' : 'A') + encoded[41..];

        Assert.False(TrackCursorCodec.TryDecodeAttribute(tampered, Key, null, out _));
        Assert.False(TrackCursorCodec.TryDecodeAttribute(encoded, OtherKey, null, out _));
        Assert.False(TrackCursorCodec.TryDecodeAttribute("", Key, null, out _));

        // Counts that do not partition the scope, or an Unknown count above the analysed Tracks, are refused.
        var broken = Position(query) with { AttributeCoverage = new TrackAttributeCoverage(Fingerprint, null, 40, 30, 4, 7, [1]) };
        Assert.False(TrackCursorCodec.TryDecodeAttribute(TrackCursorCodec.EncodeAttribute(broken, Key), Key, null, out _));
        var unknown = Position(query) with { AttributeCoverage = new TrackAttributeCoverage(Fingerprint, null, 40, 30, 4, 6, [31]) };
        Assert.False(TrackCursorCodec.TryDecodeAttribute(TrackCursorCodec.EncodeAttribute(unknown, Key), Key, null, out _));
    }

    [Fact]
    public void AttributeAndPlateCursorsAreRefusedByEachOthersDecoder()
    {
        var attribute = TrackCursorCodec.EncodeAttribute(Position(Query(Parse("person-upper-colour:red"))), Key);
        Assert.False(TrackCursorCodec.TryDecodePlate(attribute, Key, out _));
        Assert.False(TrackCursorCodec.TryDecodeAnalytic(attribute, Key, out _));
        Assert.False(TrackCursorCodec.TryDecode(attribute, out _));

        var plateQuery = new TrackSearchQuery(null, null, null, ObjectClass.Vehicle, null, null, null, null, null, 50,
            Plate: new TrackPlateQuery("KA01", TrackPlateMatch.Contains));
        var plate = TrackCursorCodec.EncodePlate(new TrackPlateCursorPosition(
            new TrackCursorPosition(At, 42, At, Guid.CreateVersion7(),
                TrackCursorCodec.ComputePlateFilterFingerprint(plateQuery, Fingerprint, null, Key)),
            Fingerprint, new TrackPlateCoverage(Fingerprint, 1, 1, 0, 0, 0, 0)), Key);
        Assert.False(TrackCursorCodec.TryDecodeAttribute(plate, Key, null, out _));
    }

    [Fact]
    public void TheOrdinaryAndAnalyticFingerprintsRefuseAnAttributeQuery() =>
        Assert.Throws<ArgumentException>(() => TrackCursorCodec.ComputeFilterFingerprint(Query(Parse("person-upper-colour:red"))));

    // --- The committed PoC release -----------------------------------------------------------------

    private static string Repository([System.Runtime.CompilerServices.CallerFilePath] string path = "") =>
        Path.GetFullPath(Path.Combine(Path.GetDirectoryName(path)!, "..", "..", ".."));

    [Fact]
    public void TheCommittedZeroShotReleaseIsTheIdentityBothLanguagesDerive()
    {
        var directory = Path.Combine(Repository(), "src", "vision", "config", "attributes");
        var resolution = VisualAttributeReleaseParser.Parse(
            File.ReadAllBytes(Path.Combine(directory, "development-attributes-siglip2-binding-v1.json")),
            () => File.ReadAllBytes(Path.Combine(directory, "development-attributes-siglip2-zero-shot-v1.json")),
            name => File.ReadAllBytes(Path.Combine(directory, name)));

        var definition = Assert.IsType<VisualAttributeReleaseDefinition>(resolution.Definition);
        using var vector = JsonDocument.Parse(File.ReadAllText(
            Path.Combine(Repository(), "contracts", "test-vectors", "poc-zero-shot-attribute-identity-v1.json")));
        Assert.Equal(vector.RootElement.GetProperty("fingerprint").GetString(), definition.Identity.Fingerprint);
        Assert.Equal(Fingerprint, definition.Identity.Fingerprint);
        Assert.True(definition.DevelopmentOnly);
        Assert.Equal("zero-shot, uncalibrated, Development", definition.Disclosure);
        Assert.Equal(
            ["person-carried-bag", "person-headwear", "person-lower-colour", "person-upper-colour", "vehicle-colour"],
            definition.Schema.Attributes.Select(item => item.AttributeType));
    }
}
