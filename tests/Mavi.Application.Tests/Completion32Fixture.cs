using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;

namespace Mavi.Application.Tests;

/// <summary>Completion 3.2 golden examples and their pinned digest vectors (S2a plan §4.5).</summary>
internal static class Completion32Fixture
{
    public const string InstalledExample = "contracts/examples/vision-job-complete-v3.2.example.json";
    public const string UnpackedExample = "contracts/examples/vision-job-complete-v3.2-unpacked-environment.example.json";
    public const string DigestVectors = "contracts/test-vectors/vision-job-complete-v3.2-digest.json";
    public const long VideoDurationMs = 3_600_000;

    public static readonly string[] ComponentIdentityFields =
        ["capabilityId", "modelPackId", "runtimePackId", "runtimePackSource", "componentBindingSha256"];

    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public static JsonObject Node(string relativePath) =>
        JsonNode.Parse(File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(), relativePath)))!.AsObject();

    public static JsonObject Provenance(JsonObject body) => body["provenance"]!.AsObject();

    public static VisionJobCompleteRequest Request(JsonObject body) => body.Deserialize<VisionJobCompleteRequest>(Json)!;

    public static VisionJobCompleteRequest Request(string relativePath) => Request(Node(relativePath));

    public static ValidatedVisionResult Validate(VisionJobCompleteRequest request) =>
        new VisionResultValidator().Validate(request.JobId!.Value, request, VideoDurationMs);

    public static ValidatedVisionResult Validate(JsonObject body) => Validate(Request(body));

    public static string Rejection(JsonObject body) =>
        Assert.Throws<VisionResultValidationException>(() => Validate(body)).ReasonCode;

    /// <summary>The body with every 3.2 component-identity member removed and a different version.</summary>
    public static JsonObject WithoutComponentIdentity(JsonObject body, string schemaVersion)
    {
        var copy = body.DeepClone().AsObject();
        copy["schemaVersion"] = schemaVersion;
        foreach (var field in ComponentIdentityFields)
            Provenance(copy).Remove(field);
        return copy;
    }
}
