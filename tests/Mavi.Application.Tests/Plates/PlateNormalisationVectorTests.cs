using System.Text.Json;
using Mavi.Application.Modules.Plates;

namespace Mavi.Application.Tests.Plates;

/// <summary>
/// Pins <see cref="PlateNormalisation"/> to the shared <c>mavi-plate-normalisation-v1</c> vectors that the Python
/// benchmark tooling (<c>tools/benchmarks/plates/normalisation.py</c>) also consumes, so a change to either
/// implementation without the vectors fails one side.
/// </summary>
public sealed class PlateNormalisationVectorTests
{
    private const string VectorPath = "contracts/test-vectors/plate-normalisation-v1.json";

    public static TheoryData<string> VectorIds()
    {
        var data = new TheoryData<string>();
        foreach (var item in LoadVectors()) data.Add(item.GetProperty("id").GetString()!);
        return data;
    }

    [Fact]
    public void VectorFileIsTheV1ContractAndCoversEveryRule()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(), VectorPath)));
        Assert.Equal("plate-normalisation-test-vectors-v1", document.RootElement.GetProperty("schemaVersion").GetString());
        Assert.Equal(PlateNormalisation.NormalisationId, document.RootElement.GetProperty("normalisationId").GetString());
        var vectors = LoadVectors();
        Assert.True(vectors.Count >= 30);
        Assert.Contains(vectors, item => item.GetProperty("reason").ValueKind == JsonValueKind.String && item.GetProperty("reason").GetString() == PlateNormalisation.Empty);
        Assert.Contains(vectors, item => item.GetProperty("reason").ValueKind == JsonValueKind.String && item.GetProperty("reason").GetString() == PlateNormalisation.NonAlphanumeric);
        foreach (var formatClass in new[] { "in-standard", "in-bh", "other" })
            Assert.Contains(vectors, item => item.GetProperty("formatClass").ValueKind == JsonValueKind.String && item.GetProperty("formatClass").GetString() == formatClass);
    }

    [Theory]
    [MemberData(nameof(VectorIds))]
    public void NormalisationMatchesTheSharedVector(string id)
    {
        var item = LoadVectors().Single(candidate => candidate.GetProperty("id").GetString() == id);
        var raw = item.GetProperty("raw").GetString()!;

        var result = PlateNormalisation.Normalise(raw);

        Assert.Equal(raw, result.Raw);
        Assert.Equal(Text(item, "normalised"), result.Normalised);
        Assert.Equal(item.GetProperty("outcome").GetString(), result.Outcome);
        Assert.Equal(Text(item, "reason"), result.Reason);
        Assert.Equal(Text(item, "formatClass"), result.FormatClass);
    }

    [Fact]
    public void IllFormedInputIsRefused()
    {
        Assert.Throws<ArgumentException>(() => PlateNormalisation.Normalise("KA01\ud800AB"));
        Assert.Throws<ArgumentException>(() => PlateNormalisation.Normalise("KA01\udc00AB"));
        Assert.Throws<ArgumentException>(() => PlateNormalisation.Normalise("KA01\ud800"));
    }

    private static string? Text(JsonElement item, string name)
    {
        var value = item.GetProperty(name);
        return value.ValueKind == JsonValueKind.Null ? null : value.GetString();
    }

    private static List<JsonElement> LoadVectors()
    {
        var text = File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(), VectorPath));
        using var document = JsonDocument.Parse(text);
        return document.RootElement.GetProperty("vectors").EnumerateArray().Select(item => item.Clone()).ToList();
    }
}
