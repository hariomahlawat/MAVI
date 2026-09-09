using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Contracts.Worker;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ProcessingOrchestrationApiTests
{
    [Fact]
    public async Task QueueLeaseHeartbeatReclaimFailAndRequeuePreservesHistory()
    {
        var clock = new MutableTimeProvider(new DateTimeOffset(2026, 9, 9, 2, 30, 0, TimeSpan.Zero));
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);
        using var client = factory.CreateClient();

        using var queued = await client.PostAsync($"/api/videos/{videoId}/process", null);
        Assert.Equal(HttpStatusCode.Accepted, queued.StatusCode);
        using var duplicate = await client.PostAsync($"/api/videos/{videoId}/process", null);
        Assert.Equal(HttpStatusCode.Conflict, duplicate.StatusCode);
        using var leaseA = await client.PostAsJsonAsync("/api/vision/jobs/lease", new VisionJobLeaseRequest("2.0", "worker-a"));
        Assert.Equal(HttpStatusCode.OK, leaseA.StatusCode);
        using var leaseJson = JsonDocument.Parse(await leaseA.Content.ReadAsStringAsync());
        var jobId = leaseJson.RootElement.GetProperty("jobId").GetGuid();
        Assert.StartsWith("source/", leaseJson.RootElement.GetProperty("sourceStorageKey").GetString(), StringComparison.Ordinal);
        Assert.DoesNotContain(factory.MediaRoot, leaseJson.RootElement.GetRawText(), StringComparison.OrdinalIgnoreCase);

        clock.Advance(TimeSpan.FromSeconds(30));
        using var heartbeat = await client.PostAsJsonAsync($"/api/vision/jobs/{jobId}/heartbeat",
            new VisionJobHeartbeatRequest("2.0", "worker-a", leaseJson.RootElement.GetProperty("leaseToken").GetString(), 40));
        Assert.Equal(HttpStatusCode.OK, heartbeat.StatusCode);
        clock.Advance(TimeSpan.FromSeconds(120));
        DateTimeOffset? originalStart;
        using (var beforeScope = factory.Services.CreateScope())
            originalStart = await beforeScope.ServiceProvider.GetRequiredService<MaviDbContext>().ProcessingRuns.Select(x => x.StartedAtUtc).SingleAsync();
        using var leaseB = await client.PostAsJsonAsync("/api/vision/jobs/lease", new VisionJobLeaseRequest("2.0", "worker-a"));
        Assert.Equal(HttpStatusCode.OK, leaseB.StatusCode);
        var currentLease = (await leaseB.Content.ReadFromJsonAsync<VisionJobLeaseContract>())!;
        Assert.NotEqual(leaseJson.RootElement.GetProperty("leaseToken").GetString(), currentLease.LeaseToken);
        using (var afterScope = factory.Services.CreateScope())
        {
            var currentJob = await afterScope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionJobs.SingleAsync();
            Assert.Equal(originalStart, await afterScope.ServiceProvider.GetRequiredService<MaviDbContext>().ProcessingRuns.Select(x => x.StartedAtUtc).SingleAsync());
            Assert.Equal(2, currentJob.AttemptCount);
            Assert.Equal(0, currentJob.ProgressPercent);
            Assert.Null(currentJob.LastHeartbeatUtc);
            Assert.Equal(32, currentJob.LeaseTokenHash!.Length);
        }
        using var staleHeartbeat = await client.PostAsJsonAsync($"/api/vision/jobs/{jobId}/heartbeat",
            new VisionJobHeartbeatRequest("2.0", "worker-a", leaseJson.RootElement.GetProperty("leaseToken").GetString(), 50));
        Assert.Equal(HttpStatusCode.Conflict, staleHeartbeat.StatusCode);
        using var staleFail = await client.PostAsJsonAsync($"/api/vision/jobs/{jobId}/fail",
            new VisionJobFailRequest("2.0", "worker-a", leaseJson.RootElement.GetProperty("leaseToken").GetString(), "stale", null));
        Assert.Equal(HttpStatusCode.Conflict, staleFail.StatusCode);
        using var failed = await client.PostAsJsonAsync($"/api/vision/jobs/{jobId}/fail",
            new VisionJobFailRequest("2.0", "worker-a", currentLease.LeaseToken, "vision_dummy_not_implemented", "bounded diagnostic"));
        Assert.Equal(HttpStatusCode.OK, failed.StatusCode);
        DateTimeOffset? completedAtUtc;
        using (var failedScope = factory.Services.CreateScope())
            completedAtUtc = await failedScope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionJobs.Select(x => x.CompletedAtUtc).SingleAsync();
        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{jobId}/fail",
            new VisionJobFailRequest("2.0", "worker-a", currentLease.LeaseToken, "vision_dummy_not_implemented", "bounded diagnostic"));
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        using var changedReplay = await client.PostAsJsonAsync($"/api/vision/jobs/{jobId}/fail",
            new VisionJobFailRequest("2.0", "worker-a", currentLease.LeaseToken, "vision_dummy_not_implemented", "changed"));
        Assert.Equal(HttpStatusCode.Conflict, changedReplay.StatusCode);
        using (var replayScope = factory.Services.CreateScope())
            Assert.Equal(completedAtUtc, await replayScope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionJobs.Select(x => x.CompletedAtUtc).SingleAsync());

        using var requeued = await client.PostAsync($"/api/videos/{videoId}/process", null);
        Assert.Equal(HttpStatusCode.Accepted, requeued.StatusCode);
        using var status = await client.GetAsync($"/api/videos/{videoId}/processing");
        Assert.Equal(HttpStatusCode.OK, status.StatusCode);
        var statusJson = await status.Content.ReadAsStringAsync();
        Assert.DoesNotContain("leaseToken", statusJson, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("leaseTokenHash", statusJson, StringComparison.OrdinalIgnoreCase);
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(2, await db.ProcessingRuns.CountAsync());
        Assert.Equal(2, await db.VisionJobs.CountAsync());
        Assert.Equal(1, await db.ProcessingRuns.CountAsync(x => x.Status == Mavi.Domain.Processing.ProcessingRunStatus.Failed));
    }

    [Fact]
    public async Task TwoWorkersRaceForOneQueuedJobAndExactlyOneWins()
    {
        using var factory = new ApiTestFactory(); await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        using var clientA = factory.CreateClient(); using var clientB = factory.CreateClient();
        var calls = new[] {
            clientA.PostAsJsonAsync("/api/vision/jobs/lease", new VisionJobLeaseRequest("2.0", "worker-a")),
            clientB.PostAsJsonAsync("/api/vision/jobs/lease", new VisionJobLeaseRequest("2.0", "worker-b")) };
        var responses = await Task.WhenAll(calls);
        Assert.Single(responses, x => x.StatusCode == HttpStatusCode.OK);
        Assert.Single(responses, x => x.StatusCode == HttpStatusCode.NoContent);
        using (var scope = factory.Services.CreateScope())
        {
            var job = await scope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionJobs.SingleAsync();
            Assert.Equal(1, job.AttemptCount);
            Assert.NotNull(job.LeaseOwner);
            Assert.Equal(32, job.LeaseTokenHash!.Length);
        }
        foreach (var response in responses) response.Dispose();
    }

    [Fact]
    public async Task ConcurrentQueueIsProtectedAndAttemptExhaustionTerminalizesChain()
    {
        var clock = new MutableTimeProvider(new DateTimeOffset(2026, 9, 9, 2, 30, 0, TimeSpan.Zero));
        using var factory = new ApiTestFactory { Clock = clock }; await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);
        using var a = factory.CreateClient(); using var b = factory.CreateClient();
        var queueResponses = await Task.WhenAll(a.PostAsync($"/api/videos/{videoId}/process", null), b.PostAsync($"/api/videos/{videoId}/process", null));
        Assert.Single(queueResponses, x => x.StatusCode == HttpStatusCode.Accepted);
        Assert.Single(queueResponses, x => x.StatusCode == HttpStatusCode.Conflict);
        foreach (var response in queueResponses) response.Dispose();

        for (var attempt = 1; attempt <= 3; attempt++)
        {
            using var lease = await a.PostAsJsonAsync("/api/vision/jobs/lease", new VisionJobLeaseRequest("2.0", $"worker-{attempt}"));
            Assert.Equal(HttpStatusCode.OK, lease.StatusCode);
            clock.Advance(TimeSpan.FromSeconds(120));
        }
        using var exhausted = await a.PostAsJsonAsync("/api/vision/jobs/lease", new VisionJobLeaseRequest("2.0", "worker-4"));
        Assert.Equal(HttpStatusCode.NoContent, exhausted.StatusCode);
        using var scope = factory.Services.CreateScope(); var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal("vision_job_attempts_exhausted", (await db.VisionJobs.SingleAsync()).FailureCode);
        Assert.Equal(VideoProcessingStatus.Failed, (await db.VideoAssets.SingleAsync()).ProcessingStatus);
        Assert.Equal(Mavi.Domain.Processing.ProcessingRunStatus.Failed, (await db.ProcessingRuns.SingleAsync()).Status);
    }

    [Fact]
    public async Task NeverQueuedAndMissingStatusAreSafe()
    {
        using var factory = new ApiTestFactory(); await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory); using var client = factory.CreateClient();
        var json = await client.GetStringAsync($"/api/videos/{videoId}/processing");
        Assert.Contains("\"videoStatus\":\"NotQueued\"", json, StringComparison.Ordinal);
        Assert.Contains("\"latestRun\":null", json, StringComparison.Ordinal);
        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync($"/api/videos/{Guid.CreateVersion7()}/processing")).StatusCode);
    }

    private static async Task<Guid> SeedVideoAsync(ApiTestFactory factory)
    {
        using var scope = factory.Services.CreateScope(); var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var now = new DateTimeOffset(2026, 9, 9, 2, 30, 0, TimeSpan.Zero);
        var camera = Camera.Create("CAM-PROC", "Processing", "UTC", now);
        var artifact = Artifact.Create(ArtifactType.SourceVideo, $"source/{Guid.CreateVersion7()}.mp4", "video/mp4", 100,
            new string('a', 64), createdAtUtc: now);
        var video = VideoAsset.Create(camera.Id, artifact.Id, "source.mp4", now, 60_000, 25, 1, 1920, 1080,
            "h264", TimestampSource.Manual, 1, importedAtUtc: now);
        db.AddRange(camera, artifact, video); await db.SaveChangesAsync(); return video.Id;
    }
}

internal sealed class MutableTimeProvider(DateTimeOffset utcNow) : TimeProvider
{
    public override DateTimeOffset GetUtcNow() => utcNow;
    public void Advance(TimeSpan duration) => utcNow = utcNow.Add(duration);
}
