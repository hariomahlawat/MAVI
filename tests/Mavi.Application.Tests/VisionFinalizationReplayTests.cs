using System.Text;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Intelligence;
using static Mavi.Application.Tests.Completion32Fixture;

namespace Mavi.Application.Tests;

/// <summary>
/// Replay rule (S2a plan §4.5): a retained finalization payload keeps the completion version
/// the worker spoke, and replay selects the digest domain from that stored version, never
/// from the platform's current default.
/// </summary>
public sealed class VisionFinalizationReplayTests
{
    [Fact]
    public void Stored31And32PayloadsReplayUnderTheirOwnDomain()
    {
        foreach (var (example, version, schema) in new[]
        {
            ("contracts/examples/vision-job-complete-v3.1.example.json", "3.1", CompletionSchema.V3),
            (InstalledExample, "3.2", CompletionSchema.V32),
            (UnpackedExample, "3.2", CompletionSchema.V32),
        })
        {
            var request = Request(example);
            var accepted = Validate(request);
            var stored = VisionFinalizationPayloadCodec.Encode(request);

            var decoded = VisionFinalizationPayloadCodec.Decode(stored);
            var replay = Validate(decoded);

            Assert.Equal(version, decoded.SchemaVersion);
            Assert.Equal(version, JsonNode.Parse(stored)!["schemaVersion"]!.GetValue<string>());
            Assert.Equal(schema, replay.Schema);
            Assert.Equal(accepted.CompletionDigest, replay.CompletionDigest);
            Assert.Equal(accepted.RuntimeProvenanceJson, replay.RuntimeProvenanceJson);
        }
    }

    [Fact]
    public void AStored32PayloadNeverMatchesItsDigestUnderTheV3Domain()
    {
        var request = Request(InstalledExample);
        var storedDigest = Validate(request).CompletionDigest;
        var stored = Encoding.UTF8.GetString(VisionFinalizationPayloadCodec.Encode(request));

        // Re-labelled as 3.1 with the component identity intact: refused, not re-digested.
        var relabelled = stored.Replace("\"schemaVersion\":\"3.2\"", "\"schemaVersion\":\"3.1\"", StringComparison.Ordinal);
        Assert.NotEqual(stored, relabelled);
        Assert.Equal("provenance_v32_field_in_v3_body",
            Assert.Throws<VisionResultValidationException>(() =>
                Validate(VisionFinalizationPayloadCodec.Decode(Encoding.UTF8.GetBytes(relabelled)))).ReasonCode);

        // Re-labelled and stripped to a valid 3.1 document: it replays, under v3, to a
        // different digest, so the executor's stored-digest check fails closed.
        var stripped = WithoutComponentIdentity(JsonNode.Parse(stored)!.AsObject(), "3.1");
        var underV3 = Validate(VisionFinalizationPayloadCodec.Decode(Encoding.UTF8.GetBytes(stripped.ToJsonString())));
        Assert.Equal(CompletionSchema.V3, underV3.Schema);
        Assert.NotEqual(storedDigest, underV3.CompletionDigest);
    }

    [Fact]
    public void AStored31PayloadNeverMatchesItsDigestUnderTheV32Domain()
    {
        var request = Request("contracts/examples/vision-job-complete-v3.1.example.json");
        var stored = Encoding.UTF8.GetString(VisionFinalizationPayloadCodec.Encode(request));
        var relabelled = stored.Replace("\"schemaVersion\":\"3.1\"", "\"schemaVersion\":\"3.2\"", StringComparison.Ordinal);

        Assert.NotEqual(stored, relabelled);
        Assert.Equal("provenance_capability_invalid",
            Assert.Throws<VisionResultValidationException>(() =>
                Validate(VisionFinalizationPayloadCodec.Decode(Encoding.UTF8.GetBytes(relabelled)))).ReasonCode);
    }

    [Fact]
    public void TheStoredDocumentOmitsANullRuntimePackId()
    {
        var stored = Encoding.UTF8.GetString(VisionFinalizationPayloadCodec.Encode(Request(UnpackedExample)));

        Assert.DoesNotContain("runtimePackId", stored, StringComparison.Ordinal);
        Assert.Contains("\"runtimePackSource\":\"unpacked-environment\"", stored, StringComparison.Ordinal);
    }
}
