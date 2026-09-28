using System.Text;
using System.Text.Json;
using Mavi.Contracts.Worker.Attributes;

namespace Mavi.Application.Tests.VisualAttributes;

/// <summary>
/// The attribute control plane's numeric bounds (S2b plan §15; implementation record §4): the
/// literal worst-shape completion fits its route cap, and every bounded collection refuses
/// cap+1 while it is still being read.
/// </summary>
public sealed class VisualAttributeContractBoundTests
{
    private static readonly JsonSerializerOptions Web = new(JsonSerializerDefaults.Web);
    private static readonly string Token64 = "a" + new string('b', 63);

    private static VisualAttributeCompleteRequest WorstShape(int tracks, int rows) => new(
        VisualAttributeContractRules.SchemaVersion,
        Guid.NewGuid(),
        "attributes-" + new string('w', 50),
        int.MaxValue,
        new VisualAttributeProvenanceContract(
            VisualAttributeContractRules.ProvenanceContract, Token64,
            [
                new(VisualAttributeContractRules.CapabilityPersonAttributes, "mavi-model-v2-" + new string('1', 64), new string('2', 64), Token64, new string('3', 64), "unverified"),
                new(VisualAttributeContractRules.CapabilityVehicleAttributes, "mavi-model-v2-" + new string('4', 64), new string('5', 64), Token64, new string('6', 64), "unverified"),
            ],
            Token64, new string('7', 64), "windows-x86_64-cuda", "mavi-runtime-v2-" + new string('8', 64), "installed-pack",
            new string('9', 64), new string('0', 64), "auto", "cuda:15", new string('m', 128), new string('c', 128)),
        new VisualAttributeCompletionPayloadContract(
            new VisualAttributeArtifactDescriptorContract(VisualAttributeContractRules.PredictionsMediaType,
                VisualAttributeContractRules.MaximumPredictionArtifactBytes, new string('f', 64)),
            Enumerable.Range(0, tracks).Select(_ => new VisualAttributeTrackResultContract(
                Guid.NewGuid(), VisualAttributeContractRules.OutcomeAnalysed, null,
                Enumerable.Range(0, rows).Select(_ => new VisualAttributeRowContract(
                    Token64, VisualAttributeContractRules.OutcomeObserved, Token64, 0.12345678901234568, Guid.NewGuid())).ToList())).ToList()));

    [Fact]
    public void TheWorstShapeCompletionFitsTheCompletionRouteCap()
    {
        // 10,000 Tracks × 8 Observed rows of 64-character tokens, 17-digit confidences and the
        // longest provenance: the derived bound is ~27.5 MB against the 32 MiB cap.
        var bytes = JsonSerializer.SerializeToUtf8Bytes(
            WorstShape(VisualAttributeContractRules.MaximumAnalysisTracks, VisualAttributeContractRules.MaximumAttributeTypesPerObjectClass), Web);

        Assert.InRange(bytes.LongLength, 20_000_000, VisualAttributeContractRules.MaximumCompletionRequestBodyBytes);
        var read = JsonSerializer.Deserialize<VisualAttributeCompleteRequest>(bytes, Web);
        Assert.Equal(VisualAttributeContractRules.MaximumAnalysisTracks, read!.Payload!.Tracks!.Count);
    }

    [Fact]
    public void OneTrackOverTheBoundIsRefusedWhileReading()
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(WorstShape(1, 1), Web);
        var text = Encoding.UTF8.GetString(bytes);
        var track = text[(text.IndexOf("\"tracks\":[", StringComparison.Ordinal) + 10)..text.LastIndexOf("]}}", StringComparison.Ordinal)];
        var over = text.Replace(track, string.Join(",", Enumerable.Repeat(track, VisualAttributeContractRules.MaximumAnalysisTracks + 1)),
            StringComparison.Ordinal);
        var at = text.Replace(track, string.Join(",", Enumerable.Repeat(track, VisualAttributeContractRules.MaximumAnalysisTracks)),
            StringComparison.Ordinal);

        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<VisualAttributeCompleteRequest>(over, Web));
        Assert.Equal(VisualAttributeContractRules.MaximumAnalysisTracks,
            JsonSerializer.Deserialize<VisualAttributeCompleteRequest>(at, Web)!.Payload!.Tracks!.Count);
    }

    [Fact]
    public void OneRowOverThePerClassBoundIsRefused()
    {
        var at = JsonSerializer.Serialize(WorstShape(1, VisualAttributeContractRules.MaximumAttributeTypesPerObjectClass), Web);
        var row = JsonSerializer.Serialize(new VisualAttributeRowContract(Token64, "observed", Token64, 0.5, Guid.NewGuid()), Web);
        var over = at.Replace("\"attributes\":[", "\"attributes\":[" + row + ",", StringComparison.Ordinal);

        Assert.NotNull(JsonSerializer.Deserialize<VisualAttributeCompleteRequest>(at, Web));
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<VisualAttributeCompleteRequest>(over, Web));
    }

    [Fact]
    public void ABodyNamingTheCapabilityIsRefusedOnEveryControlRequest()
    {
        const string token = "\"leaseToken\":\"" + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + "\"";
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<VisualAttributeLeaseRequest>(
            "{\"schemaVersion\":\"x\",\"workerId\":\"w\",\"identityFingerprint\":\"f\"," + token + "}", Web));
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<VisualAttributeHeartbeatRequest>("{" + token + "}", Web));
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<VisualAttributeFailRequest>("{" + token + "}", Web));
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<VisualAttributeCompleteRequest>("{" + token + "}", Web));
    }
}
