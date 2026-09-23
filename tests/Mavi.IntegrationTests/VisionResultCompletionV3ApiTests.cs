using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using Mavi.Application.Abstractions.Storage;
using Mavi.Contracts.Worker;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>Completion 3.0 end to end: Evidence Set persistence, replay, compensation and serving.</summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionResultCompletionV3ApiTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 23, 8, 0, 0, TimeSpan.Zero);
    private static readonly string[] Roles = ["representative", "near-view", "early-diverse", "late-diverse"];

    [Fact]
    public async Task EvidenceSetIsPersistedInRankOrderAndExactReplayIsIdempotent()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease, Roles);

        using var completed = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        var response = await completed.Content.ReadFromJsonAsync<VisionJobCompleteResponse>();
        Assert.Equal("3.0", response!.SchemaVersion);
        Assert.Equal(1, response.TracksAccepted);

        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            var track = await db.Tracks.SingleAsync();
            var observations = await db.Observations.OrderBy(x => x.EvidenceRank).ToListAsync();
            Assert.Equal(
                [ObservationType.Representative, ObservationType.NearView, ObservationType.EarlyDiverse, ObservationType.LateDiverse],
                observations.Select(x => x.ObservationType));
            Assert.Equal([0, 1, 2, 3], observations.Select(x => x.EvidenceRank));
            Assert.Equal(observations[0].Id, track.RepresentativeObservationId);
            Assert.Equal([.8, .7, .6, .5], observations.Select(x => Math.Round(x.SelectionScore, 6)));
            Assert.All(observations, x => Assert.NotNull(x.ThumbnailArtifactId));

            var crops = await db.Artifacts.Where(x => x.ArtifactType == ArtifactType.EvidenceCrop).ToListAsync();
            Assert.Equal(4, crops.Count);
            Assert.Equal(0, await db.Artifacts.CountAsync(x => x.ArtifactType == ArtifactType.Thumbnail));
            foreach (var (observation, role) in observations.Zip(Roles))
            {
                var crop = crops.Single(x => x.Id == observation.ThumbnailArtifactId);
                Assert.Equal(
                    $"evidence/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}/crops/person-000001-{role}-{crop.Sha256}.jpg",
                    crop.StorageKey);
                var bytes = await File.ReadAllBytesAsync(Path.Combine(
                    factory.EvidenceRoot, crop.StorageKey["evidence/".Length..].Replace('/', Path.DirectorySeparatorChar)));
                Assert.Equal(crop.Sha256, Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());

                // Every admitted crop is readable through its authoritative observation relation.
                using var content = await client.GetAsync($"/api/artifacts/{crop.Id:D}/content");
                Assert.Equal(HttpStatusCode.OK, content.StatusCode);
                Assert.Equal("image/jpeg", content.Content.Headers.ContentType?.MediaType);
                Assert.Equal(bytes, await content.Content.ReadAsByteArrayAsync());
            }

            Assert.Equal(VisionJobStatus.Completed, (await db.VisionJobs.SingleAsync()).Status);
        }

        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        Assert.Equal("3.0", (await replay.Content.ReadFromJsonAsync<VisionJobCompleteResponse>())!.SchemaVersion);

        // Accounting participates in the digest: a different candidate count is a conflicting replay.
        var accounting = request.EvidenceAccounting!;
        using var conflicting = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with
        {
            EvidenceAccounting = accounting with
            {
                NearView = accounting.NearView! with
                {
                    Candidates = accounting.NearView.Candidates + 1,
                    Omitted = 1,
                    CandidateBytes = accounting.NearView.CandidateBytes + 1,
                },
            },
        });
        Assert.Equal(HttpStatusCode.Conflict, conflicting.StatusCode);
        Assert.Contains("vision_job_completion_conflict", await conflicting.Content.ReadAsStringAsync(), StringComparison.Ordinal);

        using var verify = factory.Services.CreateScope();
        var verifyDb = verify.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(4, await verifyDb.Observations.CountAsync());
        Assert.Equal(6, await verifyDb.Artifacts.CountAsync());
    }

    [Fact]
    public async Task RepresentativeOnlyV3TrackIsPersisted()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");

        using var completed = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete", await BuildRequestAsync(factory, lease, ["representative"]));

        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var observation = await db.Observations.SingleAsync();
        Assert.Equal(ObservationType.Representative, observation.ObservationType);
        Assert.Equal(0, observation.EvidenceRank);
    }

    [Fact]
    public async Task IntegrityFailureOnTheLastCropRollsBackAndCompensatesEveryEarlierSeal()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease, Roles);
        var track = request.Tracks!.Single();
        var observations = track.Observations!.ToArray();
        observations[3] = observations[3] with { Crop = observations[3].Crop! with { Sha256 = new string('0', 64) } };
        request = request with { Tracks = [track with { Observations = observations }] };

        using var rejected = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);

        Assert.Equal(HttpStatusCode.Conflict, rejected.StatusCode);
        Assert.Contains("vision_result_artifact_integrity_failed", await rejected.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        await AssertNothingAcceptedAsync(factory);
    }

    [Fact]
    public async Task PersistenceFailureCompensatesEveryNewlySealedCrop()
    {
        var interceptor = new FailNextSaveChangesInterceptor();
        using var factory = new ApiTestFactory
        {
            Clock = new MutableTimeProvider(Now),
            ConfigureDbContext = options => options.AddInterceptors(interceptor),
        };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease, Roles);

        interceptor.FailNextSaveChanges = true;
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        await AssertNothingAcceptedAsync(factory);
    }

    [Fact]
    public async Task InvalidEvidenceSetIsRejectedBeforeAnySealAndLeavesTheLeaseActive()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await BuildRequestAsync(factory, lease, Roles);
        var track = request.Tracks!.Single();
        request = request with
        {
            Tracks = [track with { Observations = [.. track.Observations!.Select(o => o.Role == "late-diverse" ? o with { Rank = 5 } : o)] }],
        };

        using var rejected = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);

        Assert.Equal(HttpStatusCode.BadRequest, rejected.StatusCode);
        Assert.Contains("vision_result_invalid", await rejected.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        await AssertNothingAcceptedAsync(factory);
    }

    [Fact]
    public async Task V2CompletionIsStillAcceptedAndEchoesItsOwnVersion()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var v3 = await BuildRequestAsync(factory, lease, ["representative"]);
        var track = v3.Tracks!.Single();
        var representative = track.Observations!.Single();
        await using (var scope = factory.Services.CreateAsyncScope())
        {
            var thumbnailKey = $"staging/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}/thumbnails/person-000001.jpg";
            var stored = await scope.ServiceProvider.GetRequiredService<IMediaStore>().WriteAsync(
                thumbnailKey, new MemoryStream(CropBytes("representative")), CancellationToken.None);
            representative = representative with
            {
                Crop = new VisionArtifactDescriptorContract(thumbnailKey, "image/jpeg", stored.SizeBytes, stored.Sha256),
            };
        }

        var v2 = v3 with
        {
            SchemaVersion = "2.0",
            EvidenceAccounting = null,
            Tracks =
            [
                track with
                {
                    Observations = null,
                    Representative = new VisionRepresentativeObservationContract(
                        representative.OffsetMs, representative.SourceFrameNumber, representative.Confidence,
                        representative.QualityScore, representative.BoundingBox, representative.Crop),
                },
            ],
        };

        using var completed = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", v2);

        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        Assert.Equal("2.0", (await completed.Content.ReadFromJsonAsync<VisionJobCompleteResponse>())!.SchemaVersion);
        using var verify = factory.Services.CreateScope();
        var db = verify.ServiceProvider.GetRequiredService<MaviDbContext>();
        var thumbnail = await db.Artifacts.SingleAsync(x => x.ArtifactType == ArtifactType.Thumbnail);
        Assert.Contains("/thumbnails/person-000001-", thumbnail.StorageKey, StringComparison.Ordinal);
        var observation = await db.Observations.SingleAsync();
        Assert.Equal(0, observation.EvidenceRank);
        Assert.Equal(observation.QualityScore, observation.SelectionScore);
    }

    // Helpers
    private static async Task AssertNothingAcceptedAsync(ApiTestFactory factory)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Empty(await db.Tracks.ToListAsync());
        Assert.Empty(await db.Observations.ToListAsync());
        Assert.Equal(1, await db.Artifacts.CountAsync());
        Assert.Equal(VisionJobStatus.Leased, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Empty(Directory.Exists(factory.EvidenceRoot)
            ? Directory.GetFiles(factory.EvidenceRoot, "*", SearchOption.AllDirectories)
            : []);
    }

    private static byte[] CropBytes(string role) => Encoding.UTF8.GetBytes($"jpeg-evidence-{role}");

    private static async Task<VisionJobCompleteRequest> BuildRequestAsync(
        ApiTestFactory factory,
        VisionJobLeaseContract lease,
        string[] roles)
    {
        using var scope = factory.Services.CreateScope();
        var store = scope.ServiceProvider.GetRequiredService<IMediaStore>();
        var prefix = $"staging/{lease.JobId:D}/attempt-{lease.AttemptCount:0000}";

        var observations = new List<VisionTrackObservationContract>();
        var accounting = new Dictionary<string, VisionEvidenceRoleAccountingContract>();
        foreach (var role in Roles)
            accounting[role] = new VisionEvidenceRoleAccountingContract(0, 0, 0, 0, 0);
        for (var rank = 0; rank < roles.Length; rank++)
        {
            var role = roles[rank];
            var key = $"{prefix}/evidence/person-000001-{role}.jpg";
            var stored = await store.WriteAsync(key, new MemoryStream(CropBytes(role)), CancellationToken.None);
            observations.Add(new VisionTrackObservationContract(
                role, rank, 250 + rank * 250, rank, .88, .8 - rank * .1, .8 - rank * .1,
                new VisionBoundingBoxContract(.1, .2, .3, .4),
                new VisionArtifactDescriptorContract(key, "image/jpeg", stored.SizeBytes, stored.Sha256)));
            accounting[role] = new VisionEvidenceRoleAccountingContract(1, 1, 0, stored.SizeBytes, stored.SizeBytes);
        }

        var trajectoryKey = $"{prefix}/trajectories/person-000001.msgpack";
        var trajectory = await store.WriteAsync(
            trajectoryKey, new MemoryStream(Encoding.UTF8.GetBytes("trajectory-evidence")), CancellationToken.None);

        return new VisionJobCompleteRequest(
            "3.0",
            lease.JobId,
            lease.WorkerId,
            lease.LeaseToken,
            lease.AttemptCount,
            4,
            1250,
            VisionResultCompletionApiTests.Provenance(),
            [
                new VisionTrackResultContract(
                    "person-000001", "person", 0, 1000, 4, .85, .9, null,
                    new VisionArtifactDescriptorContract(trajectoryKey, "application/msgpack", trajectory.SizeBytes, trajectory.Sha256),
                    observations),
            ],
            new VisionEvidenceAccountingContract(
                accounting["representative"], accounting["near-view"], accounting["early-diverse"], accounting["late-diverse"]));
    }
}
