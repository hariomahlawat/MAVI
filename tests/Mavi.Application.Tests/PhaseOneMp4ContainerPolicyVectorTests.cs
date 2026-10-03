using System.Text.Json;
using Mavi.Application.Modules.Media;

namespace Mavi.Application.Tests;

/// <summary>
/// Pins <c>PhaseOneMp4ContainerPolicy</c> to the shared vector that the S3.2 probe port
/// (<c>tools/stage3/probe_media.container_supported</c>) also consumes, so a change to either
/// implementation without the vector fails one side.
/// </summary>
public sealed class PhaseOneMp4ContainerPolicyVectorTests
{
    private const string VectorPath = "contracts/test-vectors/phase1-mp4-container-policy-v1.json";

    public static TheoryData<string> CaseNames()
    {
        var data = new TheoryData<string>();
        foreach (var item in LoadCases()) data.Add(item.GetProperty("name").GetString()!);
        return data;
    }

    [Fact]
    public void VectorIsTheExpectedPolicyAndNonEmpty()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(), VectorPath)));
        Assert.Equal("phase1-mp4-container-policy-vector-v1", document.RootElement.GetProperty("schemaVersion").GetString());
        Assert.Equal("phase1-mp4-container-v1", document.RootElement.GetProperty("policy").GetString());
        Assert.True(document.RootElement.GetProperty("cases").GetArrayLength() >= 30);
    }

    [Theory]
    [MemberData(nameof(CaseNames))]
    public void PolicyMatchesTheSharedVector(string name)
    {
        var item = LoadCases().Single(candidate => candidate.GetProperty("name").GetString() == name);
        var brand = item.GetProperty("majorBrand");
        var metadata = new VideoMetadata(
            DurationMs: 1000,
            Width: 16,
            Height: 16,
            FrameRateNumerator: 25,
            FrameRateDenominator: 1,
            CodecName: "h264",
            FormatName: item.GetProperty("formatName").GetString()!,
            MajorBrand: brand.ValueKind == JsonValueKind.Null ? null : brand.GetString());

        Assert.Equal(item.GetProperty("supported").GetBoolean(), PhaseOneMp4ContainerPolicy.IsSupported(metadata));
    }

    private static List<JsonElement> LoadCases()
    {
        var text = File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(), VectorPath));
        using var document = JsonDocument.Parse(text);
        return document.RootElement.GetProperty("cases").EnumerateArray().Select(item => item.Clone()).ToList();
    }
}
