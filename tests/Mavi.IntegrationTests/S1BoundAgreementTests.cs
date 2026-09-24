using System.Text.Json;
using Mavi.Contracts.Worker;

namespace Mavi.IntegrationTests;

/// <summary>
/// S1.4 B3 (plan §7): the worker's configured evidence bounds agree with the
/// platform's enforced ones, and the 10,000-Track completion bound holds at its
/// edge for completion 3.0.
/// <para>
/// The worker takes its per-role caps and run quota from the pipeline profile,
/// and the platform takes them from <see cref="WorkerContractRules"/>. A profile
/// that drifted above the platform bound would produce completions the platform
/// rejects at run end. Drift below it would silently lose evidence the contract
/// allows. <c>test_s1_bound_agreement.py</c> checks the same values from the
/// worker side.
/// </para>
/// </summary>
public sealed class S1BoundAgreementTests
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow,
    };

    [Fact]
    public void PipelineProfileEvidenceBoundsEqualThePlatformBounds()
    {
        using var profile = JsonDocument.Parse(File.ReadAllText(
            Path.Combine(FindRepositoryRoot(), "src/vision/config/pipelines/phase1-detection-tracking-v1.json")));
        var evidence = profile.RootElement.GetProperty("evidence");
        var encoder = evidence.GetProperty("encoder");

        Assert.Equal(WorkerContractRules.MaximumRepresentativeCropBytes, encoder.GetProperty("representativeCapBytes").GetInt64());
        Assert.Equal(WorkerContractRules.MaximumSupplementalCropBytes, encoder.GetProperty("supplementalCapBytes").GetInt64());
        Assert.Equal(WorkerContractRules.MaximumCompletionEvidenceCropBytes, evidence.GetProperty("runEvidenceCropQuotaBytes").GetInt64());
    }

    [Fact]
    public void V3CompletionTrackCollectionIsBoundedAtTenThousandDuringJsonBinding()
    {
        static string Body(int tracks) =>
            "{\"schemaVersion\":\"3.0\",\"tracks\":[" + string.Join(',', Enumerable.Repeat("{}", tracks)) + "]}";

        Assert.Equal(10_000, WorkerContractRules.MaximumCompletionTracks);
        var bound = JsonSerializer.Deserialize<VisionJobCompleteRequest>(Body(WorkerContractRules.MaximumCompletionTracks), Json)!;
        Assert.Equal(WorkerContractRules.MaximumCompletionTracks, bound.Tracks!.Count);
        Assert.Throws<JsonException>(() =>
            JsonSerializer.Deserialize<VisionJobCompleteRequest>(Body(WorkerContractRules.MaximumCompletionTracks + 1), Json));
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
                return directory.FullName;

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("MAVI repository root could not be located.");
    }
}
