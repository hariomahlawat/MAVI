using System.Text.Json;
using Mavi.Application.Modules.Embeddings;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker.Embeddings;
using Mavi.Domain.Embeddings;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests.Embeddings;

/// <summary>
/// The embedding contract pins (PoC S4; ADR-021): the cross-language identity vector, vector encoding and validation,
/// appearance-text normalisation, the snapshot token's authentication, expiry and keyed fingerprint, and the domain
/// lifecycle's fences.
/// </summary>
public sealed class EmbeddingContractTests
{
    private static readonly string Root = CompletionDigestGoldenTests.FindRepositoryRoot();

    public static TheoryData<string> IdentityVectors()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "contracts/test-vectors/embedding-identity-v1.json")));
        var data = new TheoryData<string>();
        foreach (var vector in document.RootElement.GetProperty("vectors").EnumerateArray())
            data.Add(vector.GetProperty("name").GetString()!);
        return data;
    }

    [Theory]
    [MemberData(nameof(IdentityVectors))]
    public void TheReleaseParserDerivesThePinnedCanonicalIdentityAndFingerprint(string name)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "contracts/test-vectors/embedding-identity-v1.json")));
        var vector = document.RootElement.GetProperty("vectors").EnumerateArray().Single(item => item.GetProperty("name").GetString() == name);
        var resolution = EmbeddingReleaseParser.Parse(
            File.ReadAllBytes(Path.Combine(Root, vector.GetProperty("modelManifest").GetString()!)),
            File.ReadAllBytes(Path.Combine(Root, vector.GetProperty("pipelineProfile").GetString()!)));

        var definition = Assert.IsType<EmbeddingReleaseDefinition>(resolution.Definition);
        Assert.Equal(vector.GetProperty("canonicalIdentity").GetString(), definition.CanonicalIdentity);
        Assert.Equal(vector.GetProperty("fingerprint").GetString(), definition.Identity.Fingerprint);
        Assert.Equal(80, definition.MinimumCropSide);
        Assert.Equal(["Person", "Vehicle"], definition.ObjectClasses);
    }

    [Fact]
    public void TheDevelopmentReleaseIsSigLip2At768DimensionsAndDevelopmentOnly()
    {
        var definition = EmbeddingReleaseParser.Parse(
            File.ReadAllBytes(Path.Combine(Root, "models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json")),
            File.ReadAllBytes(Path.Combine(Root, "src/vision/config/embeddings/development-embeddings-siglip2-v1.json"))).Definition!;
        Assert.Equal("siglip2-base-patch16-224", definition.Identity.ModelId);
        Assert.Equal(768, definition.Identity.Dimension);
        Assert.True(definition.DevelopmentOnly);
    }

    [Fact]
    public void AProfileWhoseDimensionDisagreesWithTheManifestIsRefused()
    {
        var profile = File.ReadAllText(Path.Combine(Root, "src/vision/config/embeddings/development-embeddings-siglip2-v1.json"))
            .Replace("\"dimension\": 768", "\"dimension\": 512", StringComparison.Ordinal);
        var resolution = EmbeddingReleaseParser.Parse(
            File.ReadAllBytes(Path.Combine(Root, "models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json")),
            System.Text.Encoding.UTF8.GetBytes(profile));
        Assert.Null(resolution.Definition);
        Assert.Equal(EmbeddingReleaseParser.InvalidCode, resolution.RefusalCode);
    }

    [Fact]
    public void TheCompleteExampleVectorDecodesAndInvalidVectorsAreRefused()
    {
        using var example = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "contracts/examples/embedding-complete-v1.example.json")));
        var encoded = example.RootElement.GetProperty("tracks")[0].GetProperty("embedding").GetString();
        var vector = EmbeddingContractRules.TryDecodeVector(encoded, 768);
        Assert.NotNull(vector);
        Assert.Equal(encoded, EmbeddingContractRules.EncodeVector(vector));

        Assert.Null(EmbeddingContractRules.TryDecodeVector(encoded, 512));
        Assert.Null(EmbeddingContractRules.TryDecodeVector(EmbeddingContractRules.EncodeVector(new float[768]), 768));
        var unnormalised = Enumerable.Repeat(1f, 768).ToArray();
        Assert.Null(EmbeddingContractRules.TryDecodeVector(EmbeddingContractRules.EncodeVector(unnormalised), 768));
        var nan = vector!.ToArray();
        nan[3] = float.NaN;
        Assert.Null(EmbeddingContractRules.TryDecodeVector(EmbeddingContractRules.EncodeVector(nan), 768));
        Assert.Null(EmbeddingContractRules.TryDecodeVector("not base64!", 768));
        Assert.Null(EmbeddingContractRules.TryDecodeVector(null, 768));
    }

    [Theory]
    [InlineData("  Red   Jacket ", "red jacket")]
    [InlineData("white\tVAN\n", "white van")]
    [InlineData("a", "a")]
    public void AppearanceTextIsTrimmedCollapsedAndLowerCased(string input, string expected) =>
        Assert.Equal(expected, EmbeddingContractRules.NormaliseAppearanceText(input));

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("bell\u0007")]
    public void EmptyOrControlTextIsRefused(string input) => Assert.Null(EmbeddingContractRules.NormaliseAppearanceText(input));

    [Fact]
    public void TextLongerThan200CharactersIsRefused()
    {
        Assert.NotNull(EmbeddingContractRules.NormaliseAppearanceText(new string('a', 200)));
        Assert.Null(EmbeddingContractRules.NormaliseAppearanceText(new string('a', 201)));
    }

    private static readonly TrackSearchQuery Scope = new(Guid.Parse("01a1a000-0000-7000-8000-0000000000aa"), null, null, ObjectClass.Person,
        null, null, null, null, null, 20);

    [Fact]
    public void ASnapshotRoundTripsAndATamperedOrExpiredOneIsRefused()
    {
        var key = TrackCursorSigningKey.CreateEphemeral();
        var now = new DateTimeOffset(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
        var fingerprint = SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.SimilarKind, "track", 20, Scope, new string('a', 64), key);
        var snapshot = new SimilaritySnapshot(SimilaritySnapshotCodec.SimilarKind, fingerprint, new string('a', 64), 42, now);
        var token = SimilaritySnapshotCodec.Encode(snapshot, key);

        Assert.Equal(snapshot, SimilaritySnapshotCodec.TryDecode(token, key, now.AddMinutes(59)));
        Assert.Null(SimilaritySnapshotCodec.TryDecode(token, key, now.AddMinutes(61)));
        Assert.Null(SimilaritySnapshotCodec.TryDecode(token, TrackCursorSigningKey.CreateEphemeral(), now));
        var flipped = (token[10] == 'A' ? "B" : "A");
        Assert.Null(SimilaritySnapshotCodec.TryDecode(token[..10] + flipped + token[11..], key, now));
        Assert.Null(SimilaritySnapshotCodec.TryDecode(token + "!", key, now));
    }

    [Fact]
    public void TheFilterFingerprintIsKeyedAndCoversKindTargetTakeScopeAndIdentity()
    {
        var key = TrackCursorSigningKey.CreateEphemeral();
        var identity = new string('a', 64);
        var baseline = SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.AppearanceKind, "red jacket", 20, Scope, identity, key);
        Assert.Equal(baseline, SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.AppearanceKind, "red jacket", 20, Scope, identity, key));
        Assert.NotEqual(baseline, SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.AppearanceKind, "red jacket", 20, Scope, identity,
            TrackCursorSigningKey.CreateEphemeral()));
        Assert.NotEqual(baseline, SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.SimilarKind, "red jacket", 20, Scope, identity, key));
        Assert.NotEqual(baseline, SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.AppearanceKind, "blue jacket", 20, Scope, identity, key));
        Assert.NotEqual(baseline, SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.AppearanceKind, "red jacket", 21, Scope, identity, key));
        Assert.NotEqual(baseline, SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.AppearanceKind, "red jacket", 20,
            Scope with { ObjectClass = ObjectClass.Vehicle }, identity, key));
        Assert.NotEqual(baseline, SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.AppearanceKind, "red jacket", 20, Scope,
            new string('b', 64), key));
    }

    private static readonly EmbeddingLeasePolicy Policy = new(TimeSpan.FromMinutes(2), TimeSpan.FromMinutes(2), 2, TimeSpan.FromHours(1));

    private static EmbeddingIdentityFields Identity() => new(new string('a', 64), "siglip2-base-patch16-224", "75de2d55-dev.1",
        new string('b', 64), 768, "embeddings-siglip2-dev", "1.0.0", new string('c', 64));

    [Fact]
    public void ACompletionNeedsTheActiveLeaseAndAFailureNeverOutlivesItsAttempts()
    {
        var now = new DateTimeOffset(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
        var unit = EmbeddingAnalysis.Queue(Guid.CreateVersion7(), Identity(), now);
        var hash = new byte[32];
        unit.Claim("worker-1", hash, now, Policy);
        var completion = new EmbeddingCompletion(new string('d', 64), 7, "{}", 1, 0);

        // A completion after the lease expired is refused, though the attempt still owns the unit.
        var expired = Assert.Throws<Domain.Common.DomainValidationException>(() =>
            unit.Complete("worker-1", true, 1, now.AddMinutes(3), completion, true));
        Assert.Equal(EmbeddingAnalysis.LeaseInvalidCode, expired.Code);
        Assert.Throws<Domain.Common.DomainValidationException>(() => unit.Complete("worker-2", true, 1, now, completion, true));

        Assert.Equal(EmbeddingFailOutcome.Requeued,
            unit.FailAttempt("worker-1", true, 1, "embedding_runtime_failed", true, null, now, Policy));
        unit.Claim("worker-1", hash, now, Policy);
        Assert.Equal(EmbeddingFailOutcome.Failed,
            unit.FailAttempt("worker-1", true, 2, "embedding_runtime_failed", true, null, now, Policy));
        Assert.Equal(EmbeddingAnalysisStatus.Failed, unit.Status);
        Assert.False(unit.CanClaim(now, Policy));
    }

    [Fact]
    public void APublishedUnitIsSupersededOnlyFromCompleted()
    {
        var now = new DateTimeOffset(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
        var unit = EmbeddingAnalysis.Queue(Guid.CreateVersion7(), Identity(), now);
        unit.Claim("worker-1", new byte[32], now, Policy);
        unit.Complete("worker-1", true, 1, now, new EmbeddingCompletion(new string('d', 64), 7, "{}", 3, 1), true);
        Assert.True(unit.IsFactBearing);
        Assert.Equal(3, unit.TracksEmbedded);
        unit.Supersede();
        Assert.Equal(EmbeddingAnalysisStatus.Superseded, unit.Status);
        Assert.True(unit.IsFactBearing);
        Assert.Throws<Domain.Common.DomainValidationException>(unit.Supersede);
    }
}
