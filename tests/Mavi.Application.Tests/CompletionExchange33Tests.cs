using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;

namespace Mavi.Application.Tests;

/// <summary>
/// Completion 3.3 (Stage 3, ADR-016): the 3.2 body plus the detector-native vehicle
/// subclass under the <c>v3.3</c> digest domain. The body states the vocabulary and the
/// source once; a Track carries <c>objectSubclass</c> only when its vote resolved one.
/// </summary>
public sealed class CompletionExchange33Tests
{
    private const string InstalledExample = "contracts/examples/vision-job-complete-v3.3.example.json";
    private const string UnpackedExample = "contracts/examples/vision-job-complete-v3.3-unpacked-environment.example.json";
    private const string DigestVectors = "contracts/test-vectors/vision-job-complete-v3.3-digest.json";
    private const string InvalidCorpus = "contracts/test-vectors/control-plane-v3.3-invalid.json";
    private static readonly string[] SubclassBodyFields = ["objectSubclassVocabulary", "objectSubclassSource"];

    private static JsonObject Node(string relativePath) => Completion32Fixture.Node(relativePath);

    private static ValidatedVisionResult Validate(JsonObject body) => Completion32Fixture.Validate(body);

    private static string Rejection(JsonObject body) => Completion32Fixture.Rejection(body);

    private static JsonObject Track(JsonObject body, int index) => body["tracks"]!.AsArray()[index]!.AsObject();

    /// <summary>The body relabelled as 3.2 with every subclass member removed.</summary>
    private static JsonObject As32(JsonObject body)
    {
        var copy = body.DeepClone().AsObject();
        copy["schemaVersion"] = "3.2";
        foreach (var field in SubclassBodyFields)
            copy.Remove(field);
        foreach (var track in copy["tracks"]!.AsArray())
            track!.AsObject().Remove("objectSubclass");
        return copy;
    }

    [Fact]
    public void V33ExamplesMatchTheirPinnedFileHashesAndDigests()
    {
        var root = CompletionDigestGoldenTests.FindRepositoryRoot();
        using var pinned = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, DigestVectors)));
        var vectors = pinned.RootElement.GetProperty("vectors").EnumerateArray().ToArray();
        Assert.Equal(
            new[] { InstalledExample, UnpackedExample }.Order(StringComparer.Ordinal),
            vectors.Select(vector => vector.GetProperty("example").GetString()!).Order(StringComparer.Ordinal));

        var digests = new HashSet<string>(StringComparer.Ordinal);
        foreach (var vector in vectors)
        {
            var bytes = File.ReadAllBytes(Path.Combine(root, vector.GetProperty("example").GetString()!));
            var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(bytes, Completion32Fixture.Json)!;
            var result = new VisionResultValidator().Validate(
                request.JobId!.Value, request, vector.GetProperty("videoDurationMs").GetInt64());

            Assert.Equal(vector.GetProperty("exampleSha256").GetString(), Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
            Assert.Equal(CompletionSchema.V33, result.Schema);
            var name = vector.GetProperty("name").GetString();
            Assert.True(vector.GetProperty("completionDigest").GetString() == result.CompletionDigest,
                $"{name} digest is {result.CompletionDigest}");
            Assert.True(digests.Add(result.CompletionDigest));
        }
    }

    [Fact]
    public void EveryShared33InvalidCaseIsRefusedWithItsCode()
    {
        using var corpus = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            CompletionDigestGoldenTests.FindRepositoryRoot(), InvalidCorpus)));
        var cases = corpus.RootElement.GetProperty("cases").EnumerateArray().ToArray();
        Assert.True(cases.Length >= 10);
        Assert.Equal(cases.Length, cases.Select(item => item.GetProperty("name").GetString()).Distinct().Count());

        foreach (var item in cases)
        {
            var name = item.GetProperty("name").GetString()!;
            var body = Node(item.GetProperty("base").GetString() switch
            {
                "installed" => InstalledExample,
                "unpacked" => UnpackedExample,
                var other => throw new InvalidOperationException($"Unknown base '{other}' in case '{name}'."),
            });
            if (item.TryGetProperty("schemaVersion", out var version))
                body["schemaVersion"] = version.GetString();
            if (item.TryGetProperty("remove", out var remove))
                foreach (var field in remove.EnumerateArray())
                    Assert.True(body.Remove(field.GetString()!), name);
            if (item.TryGetProperty("set", out var set))
                foreach (var member in set.EnumerateObject())
                    body[member.Name] = JsonNode.Parse(member.Value.GetRawText());
            if (item.TryGetProperty("tracks", out var tracks))
                foreach (var edit in tracks.EnumerateArray())
                {
                    var track = Track(body, edit.GetProperty("index").GetInt32());
                    if (edit.TryGetProperty("remove", out var trackRemove))
                        foreach (var field in trackRemove.EnumerateArray())
                            Assert.True(track.Remove(field.GetString()!), name);
                    if (edit.TryGetProperty("set", out var trackSet))
                        foreach (var member in trackSet.EnumerateObject())
                            track[member.Name] = JsonNode.Parse(member.Value.GetRawText());
                }

            var error = Assert.Throws<VisionResultValidationException>(() => Validate(body));
            Assert.True(item.GetProperty("code").GetString() == error.ReasonCode, $"{name}: {error.ReasonCode}");
        }
    }

    [Fact]
    public void TheExamplesAreThe32BodiesWithOnlyAVehicleTrackAndTheSubclassMembersAdded()
    {
        // Removing the subclass members leaves a valid 3.2 body: nothing else in 3.3 differs.
        foreach (var example in new[] { InstalledExample, UnpackedExample })
            Assert.Equal(CompletionSchema.V32, Validate(As32(Node(example))).Schema);
    }

    [Fact]
    public void TheResolvedTruckAndTheAbstainedVehicleAreRecorded()
    {
        var installed = Validate(Node(InstalledExample));
        Assert.Equal(WorkerContractRules.VehicleSubclassVocabularyV1, installed.ObjectSubclassVocabulary);
        Assert.Equal(
            WorkerContractRules.DetectorNativeSubclassSourcePrefix + Node(InstalledExample)["provenance"]!["pipelineProfileSha256"]!.GetValue<string>(),
            installed.ObjectSubclassSource);
        Assert.Equal(new string?[] { null, "truck" }, installed.Tracks.Select(track => track.ObjectSubclass));

        var unpacked = Validate(Node(UnpackedExample));
        Assert.Equal(WorkerContractRules.VehicleSubclassVocabularyV1, unpacked.ObjectSubclassVocabulary);
        Assert.All(unpacked.Tracks, track => Assert.Null(track.ObjectSubclass));
        Assert.Contains(unpacked.Tracks, track => track.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Vehicle);
    }

    [Fact]
    public void AnOlderBodyRecordsNoSubclassMembers()
    {
        var v32 = Validate(As32(Node(InstalledExample)));
        Assert.Null(v32.ObjectSubclassVocabulary);
        Assert.Null(v32.ObjectSubclassSource);
        Assert.All(v32.Tracks, track => Assert.Null(track.ObjectSubclass));
    }

    [Fact]
    public void TheV33DomainIsSeparateFromTheV32DomainForTheSameRemainingBody()
    {
        var body = Node(InstalledExample);
        Assert.NotEqual(Validate(As32(body)).CompletionDigest, Validate(body).CompletionDigest);
    }

    [Theory]
    [InlineData("car")]
    [InlineData("bus")]
    [InlineData(null)]
    public void TheTrackSubclassIsInTheDigest(string? replacement)
    {
        var body = Node(InstalledExample);
        var baseline = Validate(body).CompletionDigest;
        if (replacement is null)
            Track(body, 1).Remove("objectSubclass");
        else
            Track(body, 1)["objectSubclass"] = replacement;

        Assert.NotEqual(baseline, Validate(body).CompletionDigest);
    }

    [Theory]
    [InlineData("objectSubclass")]
    [InlineData("objectSubclassVocabulary")]
    [InlineData("objectSubclassSource")]
    public void AnExplicitNullSubclassMemberIsRefusedWhenTheBodyIsRead(string field)
    {
        var body = Node(InstalledExample);
        if (field == "objectSubclass")
            Track(body, 1)[field] = null;
        else
            body[field] = null;

        Assert.ThrowsAny<JsonException>(() => Completion32Fixture.Request(body));
    }

    [Fact]
    public void A33ContractRoundTripsAndOlderContractsGainNoMembers()
    {
        var root = CompletionDigestGoldenTests.FindRepositoryRoot();
        var v33 = File.ReadAllText(Path.Combine(root, InstalledExample));
        var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(v33, Completion32Fixture.Json)!;
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse(v33), JsonNode.Parse(JsonSerializer.Serialize(request, Completion32Fixture.Json))));

        var v32 = File.ReadAllText(Path.Combine(root, Completion32Fixture.InstalledExample));
        var old = JsonSerializer.Serialize(JsonSerializer.Deserialize<VisionJobCompleteRequest>(v32, Completion32Fixture.Json), Completion32Fixture.Json);
        foreach (var field in SubclassBodyFields.Append("objectSubclass"))
            Assert.DoesNotContain($"\"{field}\"", old, StringComparison.Ordinal);
    }

    [Fact]
    public void AStored33PayloadKeepsItsSubclassMembersAndReplaysToTheSameDigest()
    {
        var request = Completion32Fixture.Request(Node(InstalledExample));
        var decoded = VisionFinalizationPayloadCodec.Decode(VisionFinalizationPayloadCodec.Encode(request));

        var original = new VisionResultValidator().Validate(request.JobId!.Value, request, Completion32Fixture.VideoDurationMs);
        var replayed = new VisionResultValidator().Validate(decoded.JobId!.Value, decoded, Completion32Fixture.VideoDurationMs);
        Assert.Equal(original.CompletionDigest, replayed.CompletionDigest);
        Assert.Equal(original.ObjectSubclassSource, replayed.ObjectSubclassSource);
        Assert.Equal(original.Tracks.Select(track => track.ObjectSubclass), replayed.Tracks.Select(track => track.ObjectSubclass));
    }

    [Fact]
    public void AStored32PayloadKeepsItsBytes()
    {
        var request = Completion32Fixture.Request(Node(Completion32Fixture.InstalledExample));
        var encoded = System.Text.Encoding.UTF8.GetString(VisionFinalizationPayloadCodec.Encode(request));
        foreach (var field in SubclassBodyFields.Append("objectSubclass"))
            Assert.DoesNotContain($"\"{field}\"", encoded, StringComparison.Ordinal);
    }

    [Fact]
    public void ThePublishedSubclassEnumIsThePlatformVocabulary()
    {
        using var schema = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            CompletionDigestGoldenTests.FindRepositoryRoot(), "contracts/schemas/vision-job-complete-v3.3.schema.json")));
        var published = schema.RootElement.GetProperty("$defs").GetProperty("objectSubclass").GetProperty("enum")
            .EnumerateArray().Select(item => item.GetString()!).ToArray();

        Assert.Equal(WorkerContractRules.VehicleSubclassValuesV1, published);
        Assert.Equal(Mavi.Domain.Intelligence.VehicleSubclass.ValuesV1, published);
        foreach (var value in published)
        {
            var body = Node(InstalledExample);
            Track(body, 1)["objectSubclass"] = value;
            Assert.Equal(value, Validate(body).Tracks[1].ObjectSubclass);
        }
    }

    [Theory]
    [InlineData(InstalledExample, "truck")]
    [InlineData(UnpackedExample, null)]
    public void TheGraphRecordsTheSubclassStateOnVehicleTracksOnly(string example, string? vehicleSubclass)
    {
        var tracks = Graph(Validate(Node(example)));
        var person = Assert.Single(tracks, track => track.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Person);
        var vehicle = Assert.Single(tracks, track => track.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Vehicle);

        // A Person Track carries none of the three; a 3.3 Vehicle always carries vocabulary and
        // source, and a subclass only when its vote resolved one.
        Assert.Null(person.ObjectSubclass);
        Assert.Null(person.ObjectSubclassVocabulary);
        Assert.Null(person.ObjectSubclassSource);
        Assert.Equal(vehicleSubclass, vehicle.ObjectSubclass);
        Assert.Equal(Mavi.Domain.Intelligence.VehicleSubclass.VocabularyV1, vehicle.ObjectSubclassVocabulary);
        Assert.StartsWith(WorkerContractRules.DetectorNativeSubclassSourcePrefix, vehicle.ObjectSubclassSource, StringComparison.Ordinal);
    }

    [Fact]
    public void AnOlderBodyBuildsTracksWithNoSubclassState()
    {
        Assert.All(Graph(Validate(As32(Node(InstalledExample)))), track =>
        {
            Assert.Null(track.ObjectSubclass);
            Assert.Null(track.ObjectSubclassVocabulary);
            Assert.Null(track.ObjectSubclassSource);
        });
    }

    private static Mavi.Domain.Intelligence.Track[] Graph(ValidatedVisionResult result)
    {
        var jobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");
        var start = new DateTimeOffset(2026, 10, 2, 6, 0, 0, TimeSpan.Zero);
        var accepted = EvidenceSealingPlan.Build(jobId, result)
            .ToDictionary(unit => unit.SourceStorageKey, unit => unit.AcceptedStorageKey, StringComparer.Ordinal);
        return FinalizationGraphBuilder.Build(result, accepted, Guid.CreateVersion7(), Guid.CreateVersion7(), start, start.AddMinutes(1))
            .Tracks.Select(track => track.Track).ToArray();
    }

    [Fact]
    public void TheV33ResponseExampleIsTheFactoryOutput()
    {
        var example = JsonSerializer.Deserialize<VisionJobFinalizationResponse>(
            File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(),
                "contracts/examples/vision-job-finalization-response-v3.3.example.json")), Completion32Fixture.Json)!;

        Assert.Equal(
            VisionJobFinalizationResponse.Finalizing("3.3", example.JobId, example.ProcessingRunId, example.AcceptedAtUtc, example.TracksSubmitted),
            example);
    }
}
