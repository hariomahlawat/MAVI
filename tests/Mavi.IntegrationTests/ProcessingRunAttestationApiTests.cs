using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Contracts.Api.Processing;
using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ProcessingRunAttestationApiTests
{
    private static readonly JsonSerializerOptions WebJsonOptions = new(JsonSerializerDefaults.Web);

    [Fact]
    public async Task CompletedRunReturnsAllowlistedValidatedAttestation()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-ATT");
        var runId = await SeedCompletedRunAsync(factory, video.VideoId, ValidProvenanceJson());

        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/processing/runs/{runId}/attestation");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var value = await response.Content.ReadFromJsonAsync<ProcessingRunAttestationResponse>();
        Assert.NotNull(value);
        Assert.Equal(runId, value.ProcessingRunId);
        Assert.Equal(video.VideoId, value.VideoAssetId);
        Assert.Equal("rtmdet-m", value.ModelId);
        Assert.Equal("unverified", value.VerificationStatus);
        Assert.Equal("linux-x86_64-cpu", value.RuntimeVariant);
        Assert.Null(value.PlatformLockSha256);
        Assert.Equal("cpu", value.ActualDevice);
        Assert.Equal("Linux", value.Platform.System);
        Assert.Equal("3.12.14", value.DependencyVersions["python"]);
        Assert.Equal("2.6.0", value.DependencyVersions["trackers"]);

        var json = await response.Content.ReadAsStringAsync();
        Assert.DoesNotContain("runtimeProvenanceJson", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("leaseToken", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("storageKey", json, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task UnknownAndNonCompletedRunsAreNonDisclosingNotFound()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-ATT-NC");
        var running = ProcessingRun.Create(video.VideoId, "phase1-detection-tracking-v1", "{}", DateTimeOffset.UtcNow);
        running.MarkRunning("worker-att", DateTimeOffset.UtcNow);
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            db.ProcessingRuns.Add(running);
            await db.SaveChangesAsync();
        }

        using var client = factory.CreateClient();
        using var unknown = await client.GetAsync($"/api/processing/runs/{Guid.NewGuid()}/attestation");
        using var nonCompleted = await client.GetAsync($"/api/processing/runs/{running.Id}/attestation");

        Assert.Equal(HttpStatusCode.NotFound, unknown.StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, nonCompleted.StatusCode);
        Assert.Contains("processing_run_not_found", await unknown.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        Assert.Contains("processing_run_not_found", await nonCompleted.Content.ReadAsStringAsync(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task MalformedPersistedProvenanceIsIntegrityFailure()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-ATT-BAD");
        var runId = await SeedCompletedRunAsync(factory, video.VideoId, "{}");

        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/processing/runs/{runId}/attestation");

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Contains("processing_attestation_integrity_failure", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);
    }

    private static async Task<Guid> SeedCompletedRunAsync(
        ApiTestFactory factory,
        Guid videoId,
        string provenanceJson)
    {
        var now = new DateTimeOffset(2026, 9, 14, 12, 0, 0, TimeSpan.Zero);
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

    private static string ValidProvenanceJson()
    {
        var contract = new VisionRuntimeProvenanceContract(
            "rtmdet-m",
            "1",
            new string('1', 64),
            new string('2', 64),
            new string('3', 64),
            "phase1",
            "1",
            new string('4', 64),
            null,
            null,
            "unverified",
            "runtime-v1",
            new string('5', 64),
            "linux-x86_64-cpu",
            null,
            "mmdetection",
            new Dictionary<string, string>
            {
                ["python"] = "3.12.14",
                ["torch"] = "2.6.0",
                ["torchvision"] = "0.21.0",
                ["mmdet"] = "3.3.0",
                ["mmcv"] = "2.1.0",
                ["mmengine"] = "0.10.7",
                ["trackers"] = "2.6.0",
                ["supervision"] = "0.30.2",
                ["scipy"] = "1.18.1",
                ["numpy"] = "2.5.3",
                ["opencv"] = "5.0.0",
                ["opencvPython"] = "5.0.0.93",
                ["av"] = "16.1.0",
                ["pillow"] = "11.3.0"
            },
            "ffmpeg-7",
            new VisionPlatformIdentityContract(
                "Linux", "6.8", "qualified", "x86_64", "x86_64",
                "3.12.14", "CPython", ["main", "Sep 2026"], "GCC"),
            "cpu",
            0,
            "cpu",
            null,
            "build-attestation",
            new string('a', 40),
            "every-frame",
            new VisionTrackerParametersContract(30, .25, .1, .2, 2, 1),
            "RGB");

        return JsonSerializer.Serialize(contract, WebJsonOptions);
    }
}
