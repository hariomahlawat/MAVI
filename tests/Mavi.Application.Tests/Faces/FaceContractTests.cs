using System.Text.Json;
using Mavi.Application.Modules.Embeddings;
using Mavi.Application.Modules.Faces;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker.Faces;
using Mavi.Domain.Common;
using Mavi.Domain.Faces;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests.Faces;

/// <summary>
/// The face contract pins (PoC S6; ADR-022): the cross-language identity vector, the worker's contract examples as
/// the platform reads them, the snapshot token's face kind, and the domain fences of query images and the gallery.
/// </summary>
public sealed class FaceContractTests
{
    private static readonly string Root = CompletionDigestGoldenTests.FindRepositoryRoot();

    private static readonly JsonSerializerOptions BodyJson = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.Strict,
    };

    public static TheoryData<string> IdentityVectors()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "contracts/test-vectors/face-identity-v1.json")));
        var data = new TheoryData<string>();
        foreach (var vector in document.RootElement.GetProperty("vectors").EnumerateArray())
            data.Add(vector.GetProperty("name").GetString()!);
        return data;
    }

    [Theory]
    [MemberData(nameof(IdentityVectors))]
    public void TheReleaseParserDerivesThePinnedCanonicalIdentityAndFingerprint(string name)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "contracts/test-vectors/face-identity-v1.json")));
        var vector = document.RootElement.GetProperty("vectors").EnumerateArray().Single(item => item.GetProperty("name").GetString() == name);
        var resolution = FaceReleaseParser.Parse(
            File.ReadAllBytes(Path.Combine(Root, vector.GetProperty("modelManifest").GetString()!)),
            File.ReadAllBytes(Path.Combine(Root, vector.GetProperty("pipelineProfile").GetString()!)));

        var definition = Assert.IsType<FaceReleaseDefinition>(resolution.Definition);
        Assert.Equal(vector.GetProperty("canonicalIdentity").GetString(), definition.CanonicalIdentity);
        Assert.Equal(vector.GetProperty("fingerprint").GetString(), definition.Identity.Fingerprint);
    }

    [Fact]
    public void TheDevelopmentReleaseIsAdaFaceAt512DimensionsWithItsThresholdAndFloor()
    {
        var definition = Development();
        Assert.Equal("faces-yunet-adaface-ir50-webface4m", definition.Identity.ModelId);
        Assert.Equal(512, definition.Identity.Dimension);
        Assert.True(definition.DevelopmentOnly);
        Assert.Equal(32, definition.MinimumFaceSide);
        Assert.Equal(0.9, definition.DetectorScoreThreshold);
        Assert.InRange(definition.ReferenceThreshold.Cosine, -1, 1);
        Assert.Contains("not calibrated on CCTV", definition.ReferenceThreshold.Provenance, StringComparison.Ordinal);
    }

    [Fact]
    public void AProfileThatIsNotPersonOnlyOrDisagreesWithTheManifestIsRefused()
    {
        var manifest = File.ReadAllBytes(Path.Combine(Root, "models/manifests/faces-yunet-adaface-ir50-dev-v1.json"));
        var profile = File.ReadAllText(Path.Combine(Root, "src/vision/config/faces/development-faces-adaface-v1.json"));
        foreach (var changed in new[]
                 {
                     profile.Replace("\"dimension\": 512", "\"dimension\": 128", StringComparison.Ordinal),
                     profile.Replace("\"Person\"", "\"Person\", \"Vehicle\"", StringComparison.Ordinal),
                     profile.Replace("\"minimumFaceSide\": 32", "\"minimumFaceSide\": 0", StringComparison.Ordinal),
                     profile.Replace("mavi-face-pipeline-v1", "mavi-embedding-pipeline-v1", StringComparison.Ordinal),
                 })
        {
            Assert.NotEqual(profile, changed);
            Assert.Equal(FaceReleaseParser.InvalidCode, FaceReleaseParser.Parse(manifest, System.Text.Encoding.UTF8.GetBytes(changed)).RefusalCode);
        }
    }

    [Fact]
    public void TheWorkerExamplesParseIntoThePlatformRecords()
    {
        var definition = Development();
        var lease = Example<FaceLeaseContract>("face-lease-v1");
        Assert.Equal(FaceContractRules.SchemaVersion, lease.SchemaVersion);
        Assert.Equal(definition.Identity.Fingerprint, lease.Identity.Fingerprint);
        Assert.All(lease.Tracks, track => Assert.Equal("Person", track.ObjectClass));

        var completion = Example<FaceCompleteRequest>("face-complete-v1");
        Assert.Equal(FaceContractRules.RoleId, completion.Provenance!.RoleId);
        Assert.All(completion.Tracks!, track => Assert.NotNull(track.Faces));
        var face = completion.Tracks![0].Faces![0];
        Assert.True(face.Usable);
        Assert.Equal(512, FaceContractRules.TryDecodeVector(face.Embedding, 512)!.Length);
        // The worker's usable flag agrees with the platform's rule on every example face.
        Assert.All(completion.Tracks.SelectMany(track => track.Faces!), item =>
            Assert.Equal(item.Usable, Math.Min(item.Box!.Width!.Value, item.Box.Height!.Value) >= definition.MinimumFaceSide));

        var queryLease = Example<FaceQueryLeaseContract>("face-query-lease-v1");
        Assert.Equal("image/jpeg", queryLease.Image.MimeType);
        var query = Example<FaceQueryCompleteRequest>("face-query-complete-v1");
        Assert.InRange(query.Faces!.Count, 1, FaceContractRules.MaximumQueryFaces);
        Assert.All(query.Faces.Where(item => item.Usable == true), item => Assert.NotNull(item.Thumbnail));
    }

    [Fact]
    public void TheSnapshotTokenCarriesTheFaceKindAndRefusesTampering()
    {
        var key = TrackCursorSigningKey.CreateEphemeral();
        var now = new DateTimeOffset(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
        var scope = new TrackSearchQuery(null, null, null, ObjectClass.Person, null, null, null, null, null, 20);
        var fingerprint = SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.FaceKind, "face:x", 20, scope, new string('a', 64), key);
        var token = SimilaritySnapshotCodec.Encode(new SimilaritySnapshot(SimilaritySnapshotCodec.FaceKind, fingerprint, new string('a', 64), 7, now), key);
        var decoded = SimilaritySnapshotCodec.TryDecode(token, key, now.AddMinutes(1))!;
        Assert.Equal(SimilaritySnapshotCodec.FaceKind, decoded.Kind);
        Assert.Equal(7, decoded.SnapshotVisibilitySequence);
        Assert.NotEqual(fingerprint,
            SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.FaceKind, "face:y", 20, scope, new string('a', 64), key));
        Assert.Null(SimilaritySnapshotCodec.TryDecode(token[..^2] + "AA", key, now.AddMinutes(1)));
        Assert.Null(SimilaritySnapshotCodec.TryDecode(token, key, now.AddMinutes(61)));
    }

    [Fact]
    public void AQueryImageIsErasedOnCompletionAndAfterItsLifetime()
    {
        var now = new DateTimeOffset(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
        var query = FaceQuery.Create(new string('a', 64), [0xFF, 0xD8, 0xFF, 1], "image/jpeg", now);
        Assert.Equal(now.AddHours(1), query.PurgeAfterUtc);
        query.Claim("faces-01", new byte[32], now, TimeSpan.FromSeconds(30));
        query.Complete("faces-01", true, 1, "[]", new string('b', 64), now.AddSeconds(5));
        Assert.Null(query.Image);
        Assert.Equal(FaceQueryStatus.Completed, query.Status);

        var stale = FaceQuery.Create(new string('a', 64), [0xFF, 0xD8, 0xFF, 1], "image/jpeg", now);
        Assert.False(stale.IsImageExpired(now.AddMinutes(14)));
        Assert.True(stale.IsImageExpired(now.AddMinutes(15)));
        stale.EraseImage(now.AddMinutes(15));
        Assert.Null(stale.Image);
        Assert.Equal(FaceQueryStatus.Failed, stale.Status);
        Assert.Equal(FaceQuery.ImageExpiredCode, stale.FailureCode);
        Assert.False(stale.CanClaim(now.AddMinutes(15)));

        Assert.Throws<DomainValidationException>(() => FaceQuery.Create(new string('a', 64), [1], "image/gif", now));
        Assert.Throws<DomainValidationException>(() => FaceQuery.Create(new string('a', 64), [0xFF, 0xD8, 0xFF, 1], "image/jpeg", now, Guid.Empty));
        var fixedId = Guid.CreateVersion7();
        Assert.Equal(fixedId, FaceQuery.Create(new string('a', 64), [0xFF, 0xD8, 0xFF, 1], "image/jpeg", now, fixedId).Id);
        Assert.Throws<DomainValidationException>(() => FaceQuery.Create(new string('a', 64), new byte[FaceQuery.MaximumImageBytes + 1], "image/png", now));
    }

    [Fact]
    public void AGalleryEntryNeedsALabelAndATemplateKeepsAThumbnailOnlyFromAnUpload()
    {
        var now = new DateTimeOffset(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
        Assert.Throws<DomainValidationException>(() => EnrolledPerson.Create("  ", null, now));
        Assert.Throws<DomainValidationException>(() => EnrolledPerson.Create("Visitor A", null, now, Guid.Empty));
        Assert.Throws<DomainValidationException>(() => EnrolledPerson.Create(new string('x', 101), null, now));
        var person = EnrolledPerson.Create(" Visitor A ", " note ", now);
        Assert.Equal("Visitor A", person.Label);
        person.Update(null, null, noteGiven: true, now);
        Assert.Null(person.Note);

        var vector = new float[512];
        vector[0] = 1;
        Assert.Throws<DomainValidationException>(() =>
            EnrolledPersonFace.Create(person.Id, new string('a', 64), vector, EnrolledFaceSource.Evidence, Guid.NewGuid(), [0xFF], now));
        Assert.Throws<DomainValidationException>(() =>
            EnrolledPersonFace.Create(person.Id, new string('a', 64), vector, EnrolledFaceSource.Query, Guid.NewGuid(), null, now));
        Assert.Null(EnrolledPersonFace.Create(person.Id, new string('a', 64), vector, EnrolledFaceSource.Evidence, Guid.NewGuid(), null, now).Thumbnail);
    }

    private static FaceReleaseDefinition Development() => FaceReleaseParser.Parse(
        File.ReadAllBytes(Path.Combine(Root, "models/manifests/faces-yunet-adaface-ir50-dev-v1.json")),
        File.ReadAllBytes(Path.Combine(Root, "src/vision/config/faces/development-faces-adaface-v1.json"))).Definition!;

    private static T Example<T>(string stem) =>
        JsonSerializer.Deserialize<T>(File.ReadAllText(Path.Combine(Root, "contracts/examples", stem + ".example.json")), BodyJson)!;
}
