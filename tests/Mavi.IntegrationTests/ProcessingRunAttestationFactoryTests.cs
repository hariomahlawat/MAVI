using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Processing;
using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.AspNetCore.Http.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

/// <summary>
/// The shared attestation factory is the endpoint's construction: for the same persisted
/// run, its response serialises to exactly the endpoint's JSON, including the members
/// that are nullable or omitted.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ProcessingRunAttestationFactoryTests
{
    private static readonly JsonSerializerOptions WebJson = new(JsonSerializerDefaults.Web);

    public static TheoryData<string> Provenances() => new()
    {
        // Completion 3.2+ component identity, no GPU.
        "component",
        // Earlier completion: component identity omitted.
        "earlier",
        // A physical GPU attested.
        "gpu",
    };

    [Theory]
    [MemberData(nameof(Provenances))]
    public async Task FactoryResponseSerialisesToTheEndpointJson(string variant)
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory, $"CAM-ATTF-{variant.ToUpperInvariant()}");
        var runId = await SeedCompletedRunAsync(factory, video.VideoId, Provenance(variant));

        using var client = factory.CreateClient();
        var endpoint = JsonNode.Parse(await client.GetStringAsync($"/api/processing/runs/{runId}/attestation"));

        using var scope = factory.Services.CreateScope();
        var orchestrator = scope.ServiceProvider.GetRequiredService<IProcessingOrchestrator>();
        var parser = scope.ServiceProvider.GetRequiredService<VisionRuntimeProvenanceParser>();
        var apiJson = scope.ServiceProvider.GetRequiredService<IOptions<JsonOptions>>().Value.SerializerOptions;
        var source = await orchestrator.GetCompletedRunAttestationAsync(runId, CancellationToken.None);
        Assert.NotNull(source);
        var built = ProcessingRunAttestationFactory.Build(source, parser.ParsePersisted(source.RuntimeProvenanceJson!));

        Assert.True(JsonNode.DeepEquals(endpoint, JsonSerializer.SerializeToNode(built, apiJson)));
        Assert.Equal(variant == "earlier", endpoint!["componentBindingSha256"] is null);
        Assert.Equal(variant == "gpu", endpoint["gpu"] is not null);
    }

    [Fact]
    public void InvalidPersistedDependenciesAreAValidationFailure()
    {
        var parser = new VisionRuntimeProvenanceParser();
        var parsed = parser.ParsePersisted(Provenance("component"));
        var broken = parsed with { Contract = parsed.Contract with { DependencyVersions = new Dictionary<string, string> { ["unlisted"] = "1" } } };
        var source = new ProcessingRunAttestationSource(
            Guid.NewGuid(), Guid.NewGuid(), DateTimeOffset.UnixEpoch, "phase1-v1", null, null, null, null, 0, 0, 0, null);

        Assert.Throws<VisionResultValidationException>(() => ProcessingRunAttestationFactory.Build(source, broken));
    }

    private static string Provenance(string variant)
    {
        var contract = JsonSerializer.Deserialize<VisionRuntimeProvenanceContract>(
            SubclassMeasurementExportWorld.ProvenanceJson(new string('4', 64)), WebJson)!;
        return variant switch
        {
            "component" => JsonSerializer.Serialize(contract, WebJson),
            "earlier" => JsonSerializer.Serialize(contract with
            {
                CapabilityId = null,
                ModelPackId = null,
                RuntimePackId = null,
                RuntimePackSource = null,
                ComponentBindingSha256 = null,
            }, WebJson),
            "gpu" => JsonSerializer.Serialize(contract with
            {
                RuntimeVariant = "windows-x86_64-cuda",
                ConfiguredDevicePolicy = "cuda",
                ConfiguredDeviceIndex = 0,
                ActualDevice = "cuda:0",
                DeviceResolutionReason = "explicit_cuda",
                Gpu = new VisionGpuIdentityContract(
                    "NVIDIA GeForce GTX 1650 Ti", 0, 4L * 1024 * 1024 * 1024, "576.83", "12.4", "GPU-test", "00000000:01:00.0", "7.5"),
            }, WebJson),
            _ => throw new ArgumentOutOfRangeException(nameof(variant)),
        };
    }

    private static async Task<Guid> SeedCompletedRunAsync(ApiTestFactory factory, Guid videoId, string provenanceJson)
    {
        var now = new DateTimeOffset(2026, 10, 3, 12, 0, 0, TimeSpan.Zero);
        var run = ProcessingRun.Create(videoId, "phase1-detection-tracking-v1", "{}", now.AddMinutes(-1));
        run.MarkRunning("worker-att", now.AddSeconds(-30));
        run.MarkCompleted(
            framesProcessed: 10,
            tracksCreated: 0,
            durationMs: 1000,
            detectorName: "rtmdet-m",
            detectorVersion: "1",
            trackerName: "ByteTrack",
            trackerVersion: "2.6.0",
            runtimeProvenanceJson: provenanceJson,
            completedAtUtc: now);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.ProcessingRuns.Add(run);
        await db.SaveChangesAsync();
        return run.Id;
    }
}
