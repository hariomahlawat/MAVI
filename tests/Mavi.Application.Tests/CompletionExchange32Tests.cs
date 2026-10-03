using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using static Mavi.Application.Tests.Completion32Fixture;

namespace Mavi.Application.Tests;

/// <summary>
/// Completion 3.2 (Stage 2 S2a plan P-7, §4.5): the 3.1 asynchronous exchange plus five
/// component-identity provenance members under the <c>v3.2</c> digest domain. The platform
/// accepts it from S2a.2; nothing emits it until S2a.3.
/// </summary>
public sealed class CompletionExchange32Tests
{
    private static readonly Guid JobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");
    private static readonly Guid RunId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd762");
    private static readonly DateTimeOffset Accepted = new(2026, 9, 25, 2, 0, 0, TimeSpan.Zero);

    [Fact]
    public void V32ExamplesMatchTheirPinnedFileHashesAndDigests()
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
            var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(bytes, Json)!;
            var result = new VisionResultValidator().Validate(
                request.JobId!.Value, request, vector.GetProperty("videoDurationMs").GetInt64());

            Assert.Equal(vector.GetProperty("exampleSha256").GetString(), Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
            Assert.Equal(CompletionSchema.V32, result.Schema);
            Assert.Equal(vector.GetProperty("completionDigest").GetString(), result.CompletionDigest);
            Assert.True(digests.Add(result.CompletionDigest));
        }
    }

    [Fact]
    public void EveryShared32InvalidCaseIsRefusedWithItsCode()
    {
        using var corpus = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            CompletionDigestGoldenTests.FindRepositoryRoot(), "contracts/test-vectors/control-plane-v3.2-invalid.json")));
        var cases = corpus.RootElement.GetProperty("cases").EnumerateArray().ToArray();
        Assert.True(cases.Length >= 20);
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
                    Assert.True(Provenance(body).Remove(field.GetString()!), name);
            if (item.TryGetProperty("set", out var set))
                foreach (var member in set.EnumerateObject())
                    Provenance(body)[member.Name] = JsonNode.Parse(member.Value.GetRawText());

            var error = Assert.Throws<VisionResultValidationException>(() => Validate(body));
            Assert.True(item.GetProperty("code").GetString() == error.ReasonCode, $"{name}: {error.ReasonCode}");
        }
    }

    [Fact]
    public void TheExamplesAreThe31ExampleWithOnlyComponentIdentityAdded()
    {
        var v31 = Node("contracts/examples/vision-job-complete-v3.1.example.json");
        foreach (var example in new[] { InstalledExample, UnpackedExample })
            Assert.True(JsonNode.DeepEquals(v31, WithoutComponentIdentity(Node(example), "3.1")), example);
    }

    [Fact]
    public void TheV32DomainIsSeparateFromTheV3DomainForTheSameBody()
    {
        // The 3.2 example minus its component identity is exactly the 3.1 golden body, whose
        // digest is the pinned v3 vector. Same remaining content, different domain: never equal.
        using var v3Vector = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            CompletionDigestGoldenTests.FindRepositoryRoot(), "contracts/test-vectors/vision-job-complete-v3-digest.json")));
        var body = Node(InstalledExample);
        var asV31 = Validate(WithoutComponentIdentity(body, "3.1"));

        Assert.Equal(CompletionSchema.V3, asV31.Schema);
        Assert.Equal(v3Vector.RootElement.GetProperty("completionDigest").GetString(), asV31.CompletionDigest);
        Assert.NotEqual(asV31.CompletionDigest, Validate(body).CompletionDigest);
    }

    [Fact]
    public void AnAbsentAndANullRuntimePackIdAreTheSameBody()
    {
        var withNull = Node(UnpackedExample);
        Assert.True(Provenance(withNull).ContainsKey("runtimePackId"));
        Assert.Null(Provenance(withNull)["runtimePackId"]);
        var absent = withNull.DeepClone().AsObject();
        Provenance(absent).Remove("runtimePackId");

        Assert.Equal(Validate(withNull).CompletionDigest, Validate(absent).CompletionDigest);
        // And a null member re-serialises as absent, so the persisted provenance never carries it.
        Assert.DoesNotContain("runtimePackId", Validate(withNull).RuntimeProvenanceJson, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("capabilityId", "\"embedding\"")]
    [InlineData("modelPackId", "\"mavi-model-v2-7777777777777777777777777777777777777777777777777777777777777778\"")]
    [InlineData("runtimePackId", "\"mavi-runtime-v2-8888888888888888888888888888888888888888888888888888888888888889\"")]
    [InlineData("componentBindingSha256", "\"9999999999999999999999999999999999999999999999999999999999999998\"")]
    public void EveryComponentIdentityMemberIsInTheDigest(string field, string replacement)
    {
        var body = Node(InstalledExample);
        var baseline = Validate(body).CompletionDigest;
        Provenance(body)[field] = JsonNode.Parse(replacement);

        Assert.NotEqual(baseline, Validate(body).CompletionDigest);
    }

    [Fact]
    public void TheRuntimePackSourceIsInTheDigest()
    {
        // The only unverified pairing change that keeps the body valid: drop the pack and
        // declare the unpacked environment. That differs from the installed example in both
        // members, so compare against the unpacked example directly instead.
        var installed = Node(InstalledExample);
        Provenance(installed)["runtimePackSource"] = "unpacked-environment";
        Provenance(installed)["runtimePackId"] = null;

        Assert.Equal(Validate(Node(UnpackedExample)).CompletionDigest, Validate(installed).CompletionDigest);
        Assert.NotEqual(Validate(Node(InstalledExample)).CompletionDigest, Validate(installed).CompletionDigest);
    }

    [Fact]
    public void ADerivedIdentityIsNeverReadAsTheOther()
    {
        // A copied id in the wrong slot is refused, not coerced: model and runtime ids have
        // disjoint grammars even though both end in the same 64-hex form.
        var swapped = Node(InstalledExample);
        var modelPackId = Provenance(swapped)["modelPackId"]!.GetValue<string>();
        var runtimePackId = Provenance(swapped)["runtimePackId"]!.GetValue<string>();
        Provenance(swapped)["modelPackId"] = runtimePackId;
        Assert.Equal("provenance_model_pack_invalid", Rejection(swapped));

        Provenance(swapped)["modelPackId"] = modelPackId;
        Provenance(swapped)["runtimePackId"] = modelPackId;
        Assert.Equal("provenance_runtime_pack_invalid", Rejection(swapped));

        // The prefix is checked, not only the length: right length, wrong namespace.
        Provenance(swapped)["runtimePackId"] = runtimePackId;
        Provenance(swapped)["modelPackId"] = "mavi-other-v2-" + modelPackId["mavi-model-v2-".Length..];
        Assert.Equal("provenance_model_pack_invalid", Rejection(swapped));
        Provenance(swapped)["modelPackId"] = modelPackId;
        Provenance(swapped)["runtimePackId"] = "mavi-models-v2-" + runtimePackId["mavi-runtime-v2-".Length..] + "8";
        Assert.Equal("provenance_runtime_pack_invalid", Rejection(swapped));
    }

    [Fact]
    public void ThePublishedCapabilityEnumIsThePlatformRegistry()
    {
        using var schema = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            CompletionDigestGoldenTests.FindRepositoryRoot(), "contracts/schemas/vision-job-complete-v3.2.schema.json")));
        var published = schema.RootElement.GetProperty("$defs").GetProperty("capabilityId").GetProperty("enum")
            .EnumerateArray().Select(item => item.GetString()!).ToArray();

        Assert.Equal(published.Order(StringComparer.Ordinal), published);
        Assert.Equal(published, VisionRuntimeProvenanceParser.KnownCapabilityIds.Order(StringComparer.Ordinal));
        foreach (var capability in published)
        {
            var body = Node(InstalledExample);
            Provenance(body)["capabilityId"] = capability;
            Assert.Equal(CompletionSchema.V32, Validate(body).Schema);
        }
    }

    [Fact]
    public void ReplayOfTheSameBodyUnderADifferentVersionIsAConflictNotAMatch()
    {
        // The submission store's idempotency check is digest equality. A 3.2 body presented
        // again as 3.1 (members stripped) or a 3.1 body presented as 3.2 never matches.
        var v32 = Node(InstalledExample);
        var v31 = WithoutComponentIdentity(v32, "3.1");
        Assert.NotEqual(Validate(v32).CompletionDigest, Validate(v31).CompletionDigest);

        var v31As32 = v31.DeepClone().AsObject();
        v31As32["schemaVersion"] = "3.2";
        Assert.Equal("provenance_capability_invalid", Rejection(v31As32));
    }

    [Fact]
    public void TheHandOffEchoesTheAsynchronousVersionTheWorkerSpoke()
    {
        foreach (var version in new[] { "3.1", "3.2", "3.3" })
        {
            var finalizing = VisionJobFinalizationResponse.Finalizing(version, JobId, RunId, Accepted, 3);
            var completed = VisionJobFinalizationResponse.Completed(version, JobId, RunId, Accepted, 3, Accepted.AddSeconds(90));
            Assert.Equal(version, finalizing.SchemaVersion);
            Assert.Equal(version, completed.SchemaVersion);
            Assert.Equal(finalizing, JsonSerializer.Deserialize<VisionJobFinalizationResponse>(JsonSerializer.Serialize(finalizing, Json), Json));
        }

        // A hand-off never answers a synchronous or unknown version.
        foreach (var version in new[] { "2.0", "3.0", "3.4", "" })
        {
            Assert.Throws<ArgumentException>(() => VisionJobFinalizationResponse.Finalizing(version, JobId, RunId, Accepted, 3));
            Assert.Throws<ArgumentException>(() =>
                VisionJobFinalizationResponse.Completed(version, JobId, RunId, Accepted, 3, Accepted.AddSeconds(90)));
        }
    }

    [Fact]
    public void TheV32ResponseExampleIsTheFactoryOutput()
    {
        var example = JsonSerializer.Deserialize<VisionJobFinalizationResponse>(
            File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(),
                "contracts/examples/vision-job-finalization-response-v3.2.example.json")), Json)!;

        Assert.Equal(
            VisionJobFinalizationResponse.Finalizing("3.2", example.JobId, example.ProcessingRunId, example.AcceptedAtUtc, example.TracksSubmitted),
            example);
    }

    [Fact]
    public void A31ContractSerialisesByteIdenticallyWithTheNewMembersPresentButNull()
    {
        var text = File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(),
            "contracts/examples/vision-job-complete-v3.1.example.json"));
        var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(text, Json)!;
        var provenanceJson = JsonSerializer.Serialize(request.Provenance, Json);

        foreach (var field in ComponentIdentityFields)
            Assert.DoesNotContain($"\"{field}\"", provenanceJson, StringComparison.Ordinal);
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse(text)!["provenance"], JsonNode.Parse(provenanceJson)));
    }
}
