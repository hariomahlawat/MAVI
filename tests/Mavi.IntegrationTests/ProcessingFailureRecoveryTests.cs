using System.Net;
using System.Net.Http.Json;
using Mavi.Contracts.Api.Processing;
using Mavi.Contracts.Api.Tracks;
using Mavi.Contracts.Worker;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ProcessingFailureRecoveryTests
{
    [Fact]
    public async Task FailedRunPreservesSourceRequeuesNewAuthorityAndRejectsStaleCompletion()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-RECOVERY");

        using var client = factory.CreateClient();

        using var firstQueue = await client.PostAsync($"/api/videos/{video.VideoId}/process", null);
        Assert.Equal(HttpStatusCode.Accepted, firstQueue.StatusCode);
        var firstQueued = await firstQueue.Content.ReadFromJsonAsync<QueueProcessingResponse>();
        Assert.NotNull(firstQueued);

        using var firstLeaseResponse = await client.PostAsJsonAsync(
            "/api/vision/jobs/lease",
            new VisionJobLeaseRequest("2.0", "recovery-worker"));
        firstLeaseResponse.EnsureSuccessStatusCode();
        var firstLease = await firstLeaseResponse.Content.ReadFromJsonAsync<VisionJobLeaseContract>();
        Assert.NotNull(firstLease);
        Assert.Equal(firstQueued.ProcessingRunId, firstLease.ProcessingRunId);

        using var failed = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{firstLease.JobId}/fail",
            new VisionJobFailRequest(
                "2.0",
                firstLease.WorkerId,
                firstLease.LeaseToken,
                "vision_processing_failed",
                "controlled Task-17 failure"));
        Assert.Equal(HttpStatusCode.OK, failed.StatusCode);

        // The managed source remains authoritative and readable after processing failure.
        using var source = await client.GetAsync($"/api/videos/{video.VideoId}/content");
        Assert.Equal(HttpStatusCode.OK, source.StatusCode);
        Assert.Equal(video.SourceBytes, await source.Content.ReadAsByteArrayAsync());

        using var noTracksResponse = await client.GetAsync(
            $"/api/tracks/?videoAssetId={video.VideoId:D}&processingRunId={firstLease.ProcessingRunId:D}");
        Assert.Equal(HttpStatusCode.OK, noTracksResponse.StatusCode);
        var noTracks = await noTracksResponse.Content.ReadFromJsonAsync<TrackSearchResponse>();
        Assert.NotNull(noTracks);
        Assert.Empty(noTracks.Items);

        using var secondQueue = await client.PostAsync($"/api/videos/{video.VideoId}/process", null);
        Assert.Equal(HttpStatusCode.Accepted, secondQueue.StatusCode);
        var secondQueued = await secondQueue.Content.ReadFromJsonAsync<QueueProcessingResponse>();
        Assert.NotNull(secondQueued);
        Assert.NotEqual(firstQueued.ProcessingRunId, secondQueued.ProcessingRunId);

        using var secondLeaseResponse = await client.PostAsJsonAsync(
            "/api/vision/jobs/lease",
            new VisionJobLeaseRequest("2.0", "recovery-worker-2"));
        secondLeaseResponse.EnsureSuccessStatusCode();
        var secondLease = await secondLeaseResponse.Content.ReadFromJsonAsync<VisionJobLeaseContract>();
        Assert.NotNull(secondLease);
        Assert.NotEqual(firstLease.JobId, secondLease.JobId);
        Assert.Equal(secondQueued.ProcessingRunId, secondLease.ProcessingRunId);

        // A stale terminal request against the failed authority cannot publish into
        // either the failed run or the new run. Lifecycle rejection precedes
        // expensive result validation.
        var staleCompletion = new VisionJobCompleteRequest(
            "2.0",
            firstLease.JobId,
            firstLease.WorkerId,
            firstLease.LeaseToken,
            firstLease.AttemptCount,
            1,
            1,
            null,
            null);

        using var stale = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{firstLease.JobId}/complete",
            staleCompletion);
        Assert.Equal(HttpStatusCode.Conflict, stale.StatusCode);
        Assert.Contains(
            "vision_job_not_leased",
            await stale.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(2, await db.ProcessingRuns.CountAsync(x => x.VideoAssetId == video.VideoId));
        Assert.Equal(2, await db.VisionJobs.CountAsync());
        Assert.Empty(await db.Tracks.Where(x => x.VideoAssetId == video.VideoId).ToListAsync());
        Assert.Equal(
            Mavi.Domain.Processing.ProcessingRunStatus.Failed,
            (await db.ProcessingRuns.SingleAsync(x => x.Id == firstLease.ProcessingRunId)).Status);
        Assert.Equal(
            Mavi.Domain.Processing.ProcessingRunStatus.Running,
            (await db.ProcessingRuns.SingleAsync(x => x.Id == secondLease.ProcessingRunId)).Status);
    }
}
