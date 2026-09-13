using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Abstractions.Storage;
using Mavi.Contracts.Worker;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionResultCompletionApiTests
{
    private static readonly DateTimeOffset Now =
        new(2026, 9, 13, 8, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task CompletePersistsAuthoritativeIntelligenceAndExactReplayIsIdempotent()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);

        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease);

        using var completed = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request);
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        var response = await completed.Content.ReadFromJsonAsync<VisionJobCompleteResponse>();
        Assert.NotNull(response);
        Assert.Equal(lease.JobId, response.JobId);
        Assert.Equal(lease.ProcessingRunId, response.ProcessingRunId);
        Assert.Equal(1, response.TracksAccepted);

        await AssertCompletedGraphAsync(factory, lease, videoId);
        await AssertAcceptedEvidenceIsSealedFromStagingAsync(factory, request);

        using var replay = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);

        using var conflictingReplay = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request with { ProcessingDurationMs = request.ProcessingDurationMs + 1 });
        Assert.Equal(HttpStatusCode.Conflict, conflictingReplay.StatusCode);
        Assert.Contains(
            "vision_job_completion_conflict",
            await conflictingReplay.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(1, await db.Tracks.CountAsync());
        Assert.Equal(1, await db.Observations.CountAsync());
        Assert.Equal(3, await db.Artifacts.CountAsync());
    }


    [Fact]
    public async Task ExactCompletedReplayRemainsIdempotentAfterVideoIsRequeued()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);

        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease);

        using (var completed = await client.PostAsJsonAsync(
                   $"/api/vision/jobs/{lease.JobId}/complete",
                   request))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);

        using (var requeued = await client.PostAsync($"/api/videos/{videoId}/process", null))
            requeued.EnsureSuccessStatusCode();

        using var replay = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var completedJob = await db.VisionJobs.SingleAsync(x => x.Id == lease.JobId);
        var completedRun = await db.ProcessingRuns.SingleAsync(x => x.Id == lease.ProcessingRunId);
        var video = await db.VideoAssets.SingleAsync(x => x.Id == videoId);

        Assert.Equal(VisionJobStatus.Completed, completedJob.Status);
        Assert.Equal(ProcessingRunStatus.Completed, completedRun.Status);
        Assert.Equal(VideoProcessingStatus.Queued, video.ProcessingStatus);
        Assert.Equal(2, await db.ProcessingRuns.CountAsync(x => x.VideoAssetId == videoId));
    }

    [Fact]
    public async Task ConcurrentExactCompletionSerializesToOneAuthoritativeGraph()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);

        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease);

        using var clientA = factory.CreateClient();
        using var clientB = factory.CreateClient();
        var responses = await Task.WhenAll(
            clientA.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request),
            clientB.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        try
        {
            Assert.All(responses, response => Assert.Equal(HttpStatusCode.OK, response.StatusCode));

            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            Assert.Equal(1, await db.Tracks.CountAsync());
            Assert.Equal(1, await db.Observations.CountAsync());
            Assert.Equal(3, await db.Artifacts.CountAsync());
            Assert.Equal(VisionJobStatus.Completed, (await db.VisionJobs.SingleAsync()).Status);
            Assert.Equal(ProcessingRunStatus.Completed, (await db.ProcessingRuns.SingleAsync()).Status);
            Assert.Equal(VideoProcessingStatus.Processed, (await db.VideoAssets.SingleAsync()).ProcessingStatus);
        }
        finally
        {
            foreach (var response in responses) response.Dispose();
        }
    }

    [Fact]
    public async Task LeaseExpiryDuringEvidenceSealingUsesLockedAuthorityTime()
    {
        var clock = new MutableTimeProvider(Now);
        var sealer = new AdvancingAcceptedEvidenceStore(clock);
        using var factory = new ApiTestFactory
        {
            Clock = clock,
            OverrideServices = services =>
            {
                services.RemoveAll<IAcceptedEvidenceStore>();
                services.AddSingleton<IAcceptedEvidenceStore>(sealer);
            }
        };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);

        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await LeaseAsync(client, "gpu-sdd-01");
        sealer.AdvanceToUtc = lease.LeaseExpiresAtUtc;
        var request = await BuildRequestAsync(factory, lease);

        using var completed = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request);

        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        Assert.Equal(2, sealer.SealCount);
        Assert.True(clock.GetUtcNow() >= lease.LeaseExpiresAtUtc);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(1, await db.Tracks.CountAsync());
        Assert.Equal(1, await db.Observations.CountAsync());
        Assert.Equal(3, await db.Artifacts.CountAsync());
        Assert.Equal(VisionJobStatus.Completed, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Equal(ProcessingRunStatus.Completed, (await db.ProcessingRuns.SingleAsync()).Status);
        Assert.Equal(VideoProcessingStatus.Processed, (await db.VideoAssets.SingleAsync()).ProcessingStatus);
    }

    [Fact]
    public async Task ExpiredLeaseCannotComplete()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);

        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease);
        clock.Advance(lease.LeaseExpiresAtUtc - clock.GetUtcNow());

        using var rejected = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request);

        Assert.Equal(HttpStatusCode.Conflict, rejected.StatusCode);
        Assert.Contains(
            "vision_job_lease_invalid",
            await rejected.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);
    }

    [Fact]
    public async Task ArtifactIntegrityFailureRollsBackAllIntelligenceAndLeavesLeaseActive()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);

        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease);
        var track = request.Tracks!.Single();
        request = request with
        {
            Tracks =
            [
                track with
                {
                    TrajectoryArtifact = track.TrajectoryArtifact! with
                    {
                        Sha256 = new string('0', 64)
                    }
                }
            ]
        };

        using var rejected = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request);

        Assert.Equal(HttpStatusCode.Conflict, rejected.StatusCode);
        Assert.Contains(
            "vision_result_artifact_integrity_failed",
            await rejected.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Empty(await db.Tracks.ToListAsync());
        Assert.Empty(await db.Observations.ToListAsync());
        Assert.Equal(1, await db.Artifacts.CountAsync());
        Assert.Equal(VisionJobStatus.Leased, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Equal(ProcessingRunStatus.Running, (await db.ProcessingRuns.SingleAsync()).Status);
        Assert.Equal(VideoProcessingStatus.Processing, (await db.VideoAssets.SingleAsync()).ProcessingStatus);
        Assert.Empty(Directory.Exists(factory.EvidenceRoot)
            ? Directory.GetFiles(factory.EvidenceRoot, "*", SearchOption.AllDirectories)
            : []);
    }

    [Fact]
    public async Task FailedCompletionDoesNotDeletePreExistingIdempotentEvidence()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);

        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease);
        var track = request.Tracks!.Single();
        var thumbnail = track.Representative!.Thumbnail!;
        var acceptedKey =
            $"evidence/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}/thumbnails/" +
            $"person-000001-{thumbnail.Sha256}.jpg";

        using (var scope = factory.Services.CreateScope())
        {
            var sealer = scope.ServiceProvider.GetRequiredService<IAcceptedEvidenceStore>();
            var preExisting = await sealer.SealAsync(
                thumbnail.StorageKey!,
                acceptedKey,
                thumbnail.SizeBytes!.Value,
                thumbnail.Sha256!,
                CancellationToken.None);
            Assert.Equal(AcceptedEvidenceSealStatus.Sealed, preExisting.Status);
            Assert.True(preExisting.CreatedNew);
        }

        request = request with
        {
            Tracks =
            [
                track with
                {
                    TrajectoryArtifact = track.TrajectoryArtifact! with
                    {
                        Sha256 = new string('0', 64)
                    }
                }
            ]
        };

        using var rejected = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request);

        Assert.Equal(HttpStatusCode.Conflict, rejected.StatusCode);
        var acceptedPath = Path.Combine(
            factory.EvidenceRoot,
            acceptedKey["evidence/".Length..].Replace('/', Path.DirectorySeparatorChar));
        Assert.True(File.Exists(acceptedPath));
    }

    [Fact]
    public async Task StaleAttemptIsRejectedBeforeArtifactInspection()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();
        var videoId = await SeedVideoAsync(factory);

        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await LeaseAsync(client, "gpu-sdd-01");
        var request = Request(
            lease,
            attemptCount: lease.AttemptCount + 1,
            thumbnail: Descriptor(
                $"staging/{lease.JobId:D}/attempt-0002/thumbnails/person-000001.jpg",
                "image/jpeg",
                4,
                new string('a', 64)),
            trajectory: Descriptor(
                $"staging/{lease.JobId:D}/attempt-0002/trajectories/person-000001.msgpack",
                "application/msgpack",
                4,
                new string('b', 64)));

        using var rejected = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete",
            request);

        Assert.Equal(HttpStatusCode.Conflict, rejected.StatusCode);
        Assert.Contains(
            "vision_job_attempt_mismatch",
            await rejected.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);
    }

    private static async Task AssertCompletedGraphAsync(
        ApiTestFactory factory,
        VisionJobLeaseContract lease,
        Guid videoId)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();

        var job = await db.VisionJobs.SingleAsync();
        var run = await db.ProcessingRuns.SingleAsync();
        var video = await db.VideoAssets.SingleAsync();
        var track = await db.Tracks.SingleAsync();
        var observation = await db.Observations.SingleAsync();

        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(100, job.ProgressPercent);
        Assert.NotNull(job.CompletedAtUtc);
        Assert.NotNull(job.CompletionDigest);
        Assert.Equal(64, job.CompletionDigest!.Length);

        Assert.Equal(ProcessingRunStatus.Completed, run.Status);
        Assert.Equal("rtmdet-m", run.DetectorName);
        Assert.Equal("1", run.DetectorVersion);
        Assert.Equal("ByteTrack", run.TrackerName);
        Assert.Equal("2.6.0", run.TrackerVersion);
        Assert.Equal(3, run.FramesProcessed);
        Assert.Equal(1, run.TracksCreated);
        Assert.Equal(1250, run.ProcessingDurationMs);
        Assert.NotNull(run.RuntimeProvenanceJson);
        using (var provenance = JsonDocument.Parse(run.RuntimeProvenanceJson!))
            Assert.Equal("rtmdet-m", provenance.RootElement.GetProperty("modelId").GetString());

        Assert.Equal(videoId, video.Id);
        Assert.Equal(VideoProcessingStatus.Processed, video.ProcessingStatus);

        Assert.Equal(1, track.LocalTrackNumber);
        Assert.Equal(3, track.DetectionCount);
        Assert.Equal(.85, track.MeanConfidence, 6);
        Assert.Equal(.9, track.MaxConfidence, 6);
        Assert.NotNull(track.TrajectoryArtifactId);
        Assert.Equal(observation.Id, track.RepresentativeObservationId);
        Assert.NotNull(observation.ThumbnailArtifactId);

        Assert.Equal(3, await db.Artifacts.CountAsync());
        Assert.Equal(2, await db.Artifacts.CountAsync(x =>
            x.ArtifactType == ArtifactType.Thumbnail ||
            x.ArtifactType == ArtifactType.TrackTrajectory));
    }

    private static async Task AssertAcceptedEvidenceIsSealedFromStagingAsync(
        ApiTestFactory factory,
        VisionJobCompleteRequest request)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var evidence = await db.Artifacts
            .Where(x => x.ArtifactType == ArtifactType.Thumbnail ||
                        x.ArtifactType == ArtifactType.TrackTrajectory)
            .OrderBy(x => x.StorageKey)
            .ToListAsync();

        Assert.Equal(2, evidence.Count);
        Assert.All(evidence, artifact => Assert.StartsWith("evidence/", artifact.StorageKey, StringComparison.Ordinal));

        var track = request.Tracks!.Single();
        var stagingThumbnailPath = Path.Combine(
            factory.MediaRoot,
            track.Representative!.Thumbnail!.StorageKey!.Replace('/', Path.DirectorySeparatorChar));
        await File.WriteAllBytesAsync(stagingThumbnailPath, Encoding.UTF8.GetBytes("mutated-after-acceptance"));

        foreach (var artifact in evidence)
        {
            var relative = artifact.StorageKey["evidence/".Length..]
                .Replace('/', Path.DirectorySeparatorChar);
            var acceptedPath = Path.Combine(factory.EvidenceRoot, relative);
            Assert.True(File.Exists(acceptedPath));
            var bytes = await File.ReadAllBytesAsync(acceptedPath);
            Assert.Equal(artifact.SizeBytes, bytes.LongLength);
            Assert.Equal(
                artifact.Sha256,
                Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
        }
    }

    private static async Task<VisionJobLeaseContract> LeaseAsync(
        HttpClient client,
        string workerId)
    {
        using var leaseResponse = await client.PostAsJsonAsync(
            "/api/vision/jobs/lease",
            new VisionJobLeaseRequest("2.0", workerId));
        leaseResponse.EnsureSuccessStatusCode();
        return (await leaseResponse.Content.ReadFromJsonAsync<VisionJobLeaseContract>())!;
    }

    private static async Task<VisionJobCompleteRequest> BuildRequestAsync(
        ApiTestFactory factory,
        VisionJobLeaseContract lease)
    {
        using var scope = factory.Services.CreateScope();
        var store = scope.ServiceProvider.GetRequiredService<IMediaStore>();

        var thumbnailKey =
            $"staging/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}/thumbnails/person-000001.jpg";
        var trajectoryKey =
            $"staging/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}/trajectories/person-000001.msgpack";

        var thumbnail = await store.WriteAsync(
            thumbnailKey,
            new MemoryStream(Encoding.UTF8.GetBytes("jpeg-evidence")),
            CancellationToken.None);
        var trajectory = await store.WriteAsync(
            trajectoryKey,
            new MemoryStream(Encoding.UTF8.GetBytes("trajectory-evidence")),
            CancellationToken.None);

        return Request(
            lease,
            lease.AttemptCount,
            Descriptor(
                thumbnailKey,
                "image/jpeg",
                thumbnail.SizeBytes,
                thumbnail.Sha256),
            Descriptor(
                trajectoryKey,
                "application/msgpack",
                trajectory.SizeBytes,
                trajectory.Sha256));
    }

    private static VisionJobCompleteRequest Request(
        VisionJobLeaseContract lease,
        int attemptCount,
        VisionArtifactDescriptorContract thumbnail,
        VisionArtifactDescriptorContract trajectory) =>
        new(
            "2.0",
            lease.JobId,
            lease.WorkerId,
            lease.LeaseToken,
            attemptCount,
            3,
            1250,
            Provenance(),
            [
                new VisionTrackResultContract(
                    "person-000001",
                    "person",
                    0,
                    1000,
                    3,
                    .85,
                    .9,
                    new VisionRepresentativeObservationContract(
                        500,
                        10,
                        .88,
                        .8,
                        new VisionBoundingBoxContract(.1, .2, .3, .4),
                        thumbnail),
                    trajectory)
            ]);

    private static VisionArtifactDescriptorContract Descriptor(
        string key,
        string mediaType,
        long sizeBytes,
        string sha256) =>
        new(key, mediaType, sizeBytes, sha256);

    private static VisionRuntimeProvenanceContract Provenance() =>
        new(
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
            new string('6', 64),
            "mmdetection",
            new Dictionary<string, string>
            {
                ["python"] = "3.12.14",
                ["trackers"] = "2.6.0",
            },
            null,
            new VisionPlatformIdentityContract(
                "Linux",
                "6.8",
                "qualified",
                "x86_64",
                "x86_64",
                "3.12.14",
                "CPython",
                ["main", "Sep 2026"],
                "GCC"),
            "cpu",
            0,
            "cpu",
            null,
            "build-a",
            new string('a', 40),
            "every-frame",
            new VisionTrackerParametersContract(30, .25, .1, .2, 2, 1),
            "RGB");

    private static async Task<Guid> SeedVideoAsync(ApiTestFactory factory)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();

        var camera = Camera.Create("CAM-COMPLETE", "Completion", "UTC", Now);
        var source = Artifact.Create(
            ArtifactType.SourceVideo,
            $"source/{Guid.CreateVersion7()}.mp4",
            "video/mp4",
            100,
            new string('c', 64),
            createdAtUtc: Now);
        var video = VideoAsset.Create(
            camera.Id,
            source.Id,
            "source.mp4",
            Now,
            60_000,
            25,
            1,
            1920,
            1080,
            "h264",
            TimestampSource.Manual,
            1,
            importedAtUtc: Now);

        db.AddRange(camera, source, video);
        await db.SaveChangesAsync();
        return video.Id;
    }
}

internal sealed class AdvancingAcceptedEvidenceStore(MutableTimeProvider clock) : IAcceptedEvidenceStore
{
    public DateTimeOffset? AdvanceToUtc { get; set; }
    public int SealCount { get; private set; }

    public Task<AcceptedEvidenceSealResult> SealAsync(
        string sourceStorageKey,
        string acceptedStorageKey,
        long expectedSizeBytes,
        string expectedSha256,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        Assert.StartsWith("staging/", sourceStorageKey, StringComparison.Ordinal);
        Assert.StartsWith("evidence/", acceptedStorageKey, StringComparison.Ordinal);
        SealCount++;

        if (SealCount == 2 && AdvanceToUtc is { } expiry && clock.GetUtcNow() < expiry)
            clock.Advance(expiry - clock.GetUtcNow());

        return Task.FromResult(new AcceptedEvidenceSealResult(
            AcceptedEvidenceSealStatus.Sealed,
            acceptedStorageKey,
            expectedSizeBytes,
            expectedSha256));
    }

    public Task DeleteAcceptedAsync(
        string acceptedStorageKey,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.CompletedTask;
    }
}
