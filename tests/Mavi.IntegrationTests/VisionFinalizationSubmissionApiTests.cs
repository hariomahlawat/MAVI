using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Abstractions.Storage;
using Mavi.Contracts.Worker;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// Completion 3.1 end to end (S1.4 B3 asynchronous finalization plan §5, §6, §10.1–§10.2; slice F2):
/// the durable hand-off, its replay and conflict rules, its concurrency, the protocol switch, and
/// the things the request must no longer do. Every test here runs with the activation gate on
/// (<c>VisionFinalization:Enabled</c>), the state the F3 release switches to; the default
/// (gate off) state is <see cref="VisionFinalizationActivationGateTests"/>.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationSubmissionApiTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 25, 8, 0, 0, TimeSpan.Zero);
    private static readonly string[] Roles = ["representative", "near-view", "early-diverse", "late-diverse"];
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    // -- the hand-off -------------------------------------------------------------------------

    [Fact]
    public async Task ValidSubmissionHandsOffAtomicallyWithoutSealingOrPublishingAnything()
    {
        var sealer = new SealingTrap();
        var logs = new CapturingLoggerProvider();
        var clock = new MutableTimeProvider(Now);
        using var factory = Factory(clock, sealer, logs);
        var (client, lease, request) = await LeasedAsync(factory);
        clock.Advance(TimeSpan.FromSeconds(5));

        using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        var ack = JsonSerializer.Deserialize<VisionJobFinalizationResponse>(body, Json)!;
        Assert.Equal("3.1", ack.SchemaVersion);
        Assert.Equal("finalizing", ack.State);
        Assert.Equal(lease.JobId, ack.JobId);
        Assert.Equal(lease.ProcessingRunId, ack.ProcessingRunId);
        Assert.Equal(Now.AddSeconds(5), ack.AcceptedAtUtc);
        Assert.Equal(1, ack.TracksSubmitted);
        Assert.Null(ack.CompletedAtUtc);
        Assert.DoesNotContain("completedAtUtc", body, StringComparison.Ordinal);
        Assert.DoesNotContain("tracksAccepted", body, StringComparison.Ordinal);

        Assert.Equal(0, sealer.Calls);
        Assert.Empty(EvidenceFiles(factory));
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal(Now.AddSeconds(5), job.FinalizationAcceptedAtUtc);
        Assert.NotNull(job.CompletionDigest);
        Assert.Equal("gpu-sdd-01", job.LeaseOwner);
        Assert.NotNull(job.LeaseTokenHash);
        Assert.Equal(lease.AttemptCount, job.AttemptCount);
        Assert.Equal(0, job.FinalizationAttemptCount);
        Assert.Null(job.FinalizationClaimTokenHash);
        Assert.Null(job.CompletedAtUtc);

        var payload = await db.VisionFinalizationPayloads.SingleAsync();
        Assert.Equal(job.Id, payload.JobId);
        Assert.Equal(job.AttemptCount, payload.AttemptCount);
        Assert.Equal(job.CompletionDigest, payload.CompletionDigest);
        Assert.Equal(Now.AddSeconds(5), payload.AcceptedAtUtc);
        Assert.Equal(payload.Payload.LongLength, payload.PayloadLength);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(payload.Payload)), payload.PayloadSha256);

        // Nothing published: no graph, no completion, no visibility sequence, counters unpublished.
        Assert.Equal(0, await db.Tracks.CountAsync());
        Assert.Equal(0, await db.Observations.CountAsync());
        Assert.Equal(1, await db.Artifacts.CountAsync()); // the source video only
        var run = await db.ProcessingRuns.SingleAsync();
        Assert.Equal(ProcessingRunStatus.Running, run.Status);
        Assert.Null(run.CompletedAtUtc);
        Assert.Null(run.VisibilitySequence);
        Assert.Equal(0, run.TracksCreated);
        Assert.Equal(0, run.FramesProcessed);
        Assert.Equal(VideoProcessingStatus.Processing, (await db.VideoAssets.SingleAsync()).ProcessingStatus);
        Assert.Equal(0L, await VisibilitySequenceAllocationsAsync(factory));

        // The operator sees the truthful phase; the run itself is still Running.
        using var status = await client.GetAsync($"/api/videos/{run.VideoAssetId}/processing");
        using var statusBody = JsonDocument.Parse(await status.Content.ReadAsStringAsync());
        var latest = statusBody.RootElement.GetProperty("latestRun");
        Assert.Equal("Running", latest.GetProperty("status").GetString());
        Assert.Equal("finalizing", latest.GetProperty("phase").GetString());
        Assert.Equal(0, latest.GetProperty("tracksCreated").GetInt32());
        Assert.Equal(JsonValueKind.Null, latest.GetProperty("completedAtUtc").ValueKind);

        // The hand-off is instrumented, and nothing that is logged carries the capability.
        var handOff = Assert.Single(logs.Entries, x => x.EventId.Id == 1310);
        Assert.Contains("validation", handOff.Message, StringComparison.Ordinal);
        Assert.Contains("persistence", handOff.Message, StringComparison.Ordinal);
        Assert.DoesNotContain(lease.LeaseToken, string.Join('\n', logs.Entries.Select(x => x.Message)), StringComparison.Ordinal);
    }

    [Fact]
    public async Task RetainedPayloadIsTheSemanticDocumentWithoutTheCapabilityEnvelope()
    {
        const string workerId = "probe-worker-7f3a1c";
        using var factory = Factory(new MutableTimeProvider(Now));
        var (client, lease, request) = await LeasedAsync(factory, workerId);
        Assert.Equal(workerId, lease.WorkerId);

        using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        // Straight from the bytea, not through the entity: the bytes PostgreSQL holds.
        await using var connection = new NpgsqlConnection(factory.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT payload, payload_length, payload_sha256 FROM vision_finalization_payloads WHERE job_id = $1", connection);
        command.Parameters.AddWithValue(lease.JobId);
        await using var reader = await command.ExecuteReaderAsync();
        Assert.True(await reader.ReadAsync());
        var stored = (byte[])reader[0];
        Assert.Equal(stored.LongLength, reader.GetInt64(1));
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(stored)), reader.GetString(2));

        var tokenBytes = Encoding.UTF8.GetBytes(lease.LeaseToken);
        var workerBytes = Encoding.UTF8.GetBytes(workerId);
        Assert.Equal(-1, stored.AsSpan().IndexOf(tokenBytes));
        Assert.Equal(-1, stored.AsSpan().IndexOf(workerBytes));
        var text = Encoding.UTF8.GetString(stored);
        Assert.DoesNotContain("leaseToken", text, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("workerId", text, StringComparison.OrdinalIgnoreCase);

        // And it is exactly the codec's document, so the finalizer re-validates to the same digest.
        using var document = JsonDocument.Parse(stored);
        Assert.Equal("3.1", document.RootElement.GetProperty("schemaVersion").GetString());
        Assert.Equal(1, document.RootElement.GetProperty("tracks").GetArrayLength());
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        var revalidated = new Mavi.Application.Modules.Intelligence.VisionResultValidator().Validate(
            job.Id, Mavi.Application.Modules.Intelligence.VisionFinalizationPayloadCodec.Decode(stored), 60_000);
        Assert.Equal(job.CompletionDigest, revalidated.CompletionDigest);
    }

    [Fact]
    public async Task InvalidBodyIsRejectedAndLeavesTheLeaseAndNoPayload()
    {
        using var factory = Factory(new MutableTimeProvider(Now));
        var (client, lease, request) = await LeasedAsync(factory);
        var track = request.Tracks!.Single();
        // Two observations claiming the same rank: the validator refuses it.
        var observations = track.Observations!.ToArray();
        observations[1] = observations[1] with { Rank = 0 };

        using var rejected = await client.PostAsJsonAsync(
            $"/api/vision/jobs/{lease.JobId}/complete", request with { Tracks = [track with { Observations = observations }] });

        Assert.Contains("vision_result_invalid", await AssertStatusAsync(rejected, HttpStatusCode.BadRequest), StringComparison.Ordinal);
        await AssertStillLeasedAsync(factory);

        // The lease is intact, so the corrected body hands off normally.
        using var accepted = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, accepted.StatusCode);
    }

    [Fact]
    public async Task ExpiredLeaseOrWrongCapabilityCannotHandOff()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = Factory(clock);
        var (client, lease, request) = await LeasedAsync(factory);

        using var wrongWorker = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { WorkerId = "gpu-sdd-02" });
        Assert.Contains("vision_job_lease_invalid", await AssertStatusAsync(wrongWorker, HttpStatusCode.Conflict), StringComparison.Ordinal);

        var otherToken = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA";
        using var wrongToken = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { LeaseToken = otherToken });
        Assert.DoesNotContain(otherToken, await AssertStatusAsync(wrongToken, HttpStatusCode.Conflict), StringComparison.Ordinal);

        using var wrongAttempt = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { AttemptCount = lease.AttemptCount + 1 });
        Assert.Contains("vision_job_attempt_mismatch", await AssertStatusAsync(wrongAttempt, HttpStatusCode.Conflict), StringComparison.Ordinal);

        clock.Advance(lease.LeaseExpiresAtUtc - Now + TimeSpan.FromSeconds(1));
        using var expired = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Contains("vision_job_lease_invalid", await AssertStatusAsync(expired, HttpStatusCode.Conflict), StringComparison.Ordinal);

        await AssertStillLeasedAsync(factory);
    }

    // -- replay and conflict (plan §5.3) -------------------------------------------------------

    [Fact]
    public async Task ExactReplayWhileFinalizingIsIdempotentAndPreservesTheAcceptedTime()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = Factory(clock);
        var (client, lease, request) = await LeasedAsync(factory);
        var first = await HandOffAsync(client, lease, request);

        // Later than the lease could ever be valid, and the finalizer may already hold a claim:
        // the replay authenticates against the retained capability only and writes nothing.
        clock.Advance(TimeSpan.FromHours(3));
        byte[] claimHash;
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            var job = await db.VisionJobs.SingleAsync();
            claimHash = SHA256.HashData(RandomNumberGenerator.GetBytes(32));
            job.ClaimFinalization(claimHash, clock.GetUtcNow(), TimeSpan.FromMinutes(5), 3);
            await db.SaveChangesAsync();
        }

        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        var replayed = (await replay.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!;
        Assert.Equal("finalizing", replayed.State);
        Assert.Equal(first.AcceptedAtUtc, replayed.AcceptedAtUtc);
        Assert.Equal(first.TracksSubmitted, replayed.TracksSubmitted);
        Assert.Null(replayed.CompletedAtUtc);

        using var verify = factory.Services.CreateScope();
        var verifyDb = verify.ServiceProvider.GetRequiredService<MaviDbContext>();
        var after = await verifyDb.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Finalizing, after.Status);
        Assert.Equal(first.AcceptedAtUtc, after.FinalizationAcceptedAtUtc);
        Assert.Equal(1, after.FinalizationAttemptCount);
        Assert.Equal(claimHash, after.FinalizationClaimTokenHash); // claim state untouched
        Assert.Equal(1, await verifyDb.VisionFinalizationPayloads.CountAsync());
    }

    [Fact]
    public async Task ExactReplayOfACompletedJobReportsCompletedWithTheStoredTime()
    {
        var clock = new MutableTimeProvider(Now);
        using var factory = Factory(clock);
        var (client, lease, request) = await LeasedAsync(factory);
        var first = await HandOffAsync(client, lease, request);

        // The F3 finalizer's outcome, modelled at the domain level: claim, then publish.
        clock.Advance(TimeSpan.FromMinutes(2));
        var completedAt = clock.GetUtcNow();
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            var job = await db.VisionJobs.SingleAsync();
            var token = RandomNumberGenerator.GetBytes(32);
            job.ClaimFinalization(SHA256.HashData(token), completedAt, TimeSpan.FromMinutes(5), 3);
            job.CompleteFinalization(token, completedAt);
            var run = await db.ProcessingRuns.SingleAsync();
            run.MarkCompleted(4, 1, 1250, completedAt);
            await db.SaveChangesAsync();
        }

        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        var body = await replay.Content.ReadAsStringAsync();
        var replayed = JsonSerializer.Deserialize<VisionJobFinalizationResponse>(body, Json)!;
        Assert.Equal("completed", replayed.State);
        Assert.Equal(completedAt, replayed.CompletedAtUtc);
        Assert.Equal(first.AcceptedAtUtc, replayed.AcceptedAtUtc);
        Assert.Equal(1, replayed.TracksSubmitted);
        Assert.Contains("completedAtUtc", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ReplayWithWrongCapabilityOrDifferentContentConflicts()
    {
        using var factory = Factory(new MutableTimeProvider(Now));
        var (client, lease, request) = await LeasedAsync(factory);
        var first = await HandOffAsync(client, lease, request);

        foreach (var (name, replay) in new (string, VisionJobCompleteRequest)[]
                 {
                     ("wrong worker", request with { WorkerId = "gpu-sdd-02" }),
                     ("wrong token", request with { LeaseToken = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA" }),
                     ("wrong attempt", request with { AttemptCount = lease.AttemptCount + 1 }),
                     ("same attempt, different digest", request with { FramesProcessed = request.FramesProcessed + 1 }),
                 })
        {
            using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", replay);
            Assert.Contains("vision_job_completion_conflict", await AssertStatusAsync(response, HttpStatusCode.Conflict), StringComparison.Ordinal);
        }

        // A conflicting body that is not even valid is still refused, never adopted.
        using var invalid = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { Tracks = [] , EvidenceAccounting = null });
        Assert.NotEqual(HttpStatusCode.OK, invalid.StatusCode);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal(first.AcceptedAtUtc, job.FinalizationAcceptedAtUtc);
        Assert.Equal(1, await db.VisionFinalizationPayloads.CountAsync());
    }

    // -- concurrency (plan §6: the row lock is the serialization point) ------------------------

    [Fact]
    public async Task IdenticalConcurrentSubmissionsConvergeOnOneHandOff()
    {
        using var factory = Factory(new MutableTimeProvider(Now));
        var (client, lease, request) = await LeasedAsync(factory);
        using var second = factory.CreateClient();

        var responses = await Task.WhenAll(
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request),
            second.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        var acks = new List<VisionJobFinalizationResponse>();
        foreach (var response in responses)
        {
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            acks.Add((await response.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!);
            response.Dispose();
        }
        Assert.All(acks, ack => Assert.Equal("finalizing", ack.State));
        Assert.Equal(acks[0].AcceptedAtUtc, acks[1].AcceptedAtUtc);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal(acks[0].AcceptedAtUtc, job.FinalizationAcceptedAtUtc);
        Assert.Equal(1, await db.VisionFinalizationPayloads.CountAsync());
    }

    [Fact]
    public async Task ConflictingConcurrentSubmissionsLetExactlyOneBecomeAuthoritative()
    {
        using var factory = Factory(new MutableTimeProvider(Now));
        var (client, lease, request) = await LeasedAsync(factory);
        using var second = factory.CreateClient();
        var competing = request with { FramesProcessed = request.FramesProcessed + 1 };

        var responses = await Task.WhenAll(
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request),
            second.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", competing));

        var statuses = responses.Select(x => x.StatusCode).Order().ToArray();
        Assert.Equal([HttpStatusCode.OK, HttpStatusCode.Conflict], statuses);
        foreach (var response in responses) response.Dispose();

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        var payload = await db.VisionFinalizationPayloads.SingleAsync();
        Assert.Equal(job.CompletionDigest, payload.CompletionDigest);
    }

    // -- protocol switch (plan §15.2, §15.4) ---------------------------------------------------

    [Fact]
    public async Task Retired30IsRefusedEvenWithAValidLeaseAndNeverReinterpreted()
    {
        using var factory = Factory(new MutableTimeProvider(Now));
        var (client, lease, request) = await LeasedAsync(factory);

        using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { SchemaVersion = "3.0" });

        Assert.Contains("worker_contract_version_unsupported", await AssertStatusAsync(response, HttpStatusCode.BadRequest), StringComparison.Ordinal);
        await AssertStillLeasedAsync(factory);
    }

    [Fact]
    public async Task V2CompletionIsStillSynchronousAndEchoesItsOwnVersion()
    {
        var clock = new MutableTimeProvider(Now);
        var sealer = new AdvancingAcceptedEvidenceStore(clock);
        using var factory = Factory(clock, sealer);
        var (client, lease, v3) = await LeasedAsync(factory, roles: ["representative"]);
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

        // Unchanged 2.0 semantics: sealed synchronously, published, Completed, its own response.
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        var response = (await completed.Content.ReadFromJsonAsync<VisionJobCompleteResponse>())!;
        Assert.Equal("2.0", response.SchemaVersion);
        Assert.Equal(1, response.TracksAccepted);
        Assert.Equal(2, sealer.SealCount);
        using var verify = factory.Services.CreateScope();
        var db = verify.ServiceProvider.GetRequiredService<MaviDbContext>();
        var thumbnail = await db.Artifacts.SingleAsync(x => x.ArtifactType == ArtifactType.Thumbnail);
        Assert.Contains("/thumbnails/person-000001-", thumbnail.StorageKey, StringComparison.Ordinal);
        var observation = await db.Observations.SingleAsync();
        Assert.Equal(0, observation.EvidenceRank);
        Assert.Equal(observation.QualityScore, observation.SelectionScore);
        Assert.Equal(VisionJobStatus.Completed, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Equal(ProcessingRunStatus.Completed, (await db.ProcessingRuns.SingleAsync()).Status);
        Assert.Equal(VideoProcessingStatus.Processed, (await db.VideoAssets.SingleAsync()).ProcessingStatus);
        Assert.Equal(0, await db.VisionFinalizationPayloads.CountAsync());
        Assert.Equal(1L, await VisibilitySequenceAllocationsAsync(factory));
    }

    [Fact]
    public async Task BodyAboveTheContractBoundIsRefusedBeforeTheHandOff()
    {
        using var factory = Factory(new MutableTimeProvider(Now));
        var (client, lease, _) = await LeasedAsync(factory);
        using var content = new StringContent("{\"schemaVersion\":\"3.1\"}", Encoding.UTF8, "application/json");
        content.Headers.ContentLength = WorkerContractRules.MaximumCompletionRequestBodyBytes + 1;

        using var response = await client.PostAsync($"/api/vision/jobs/{lease.JobId}/complete", content);

        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, response.StatusCode);
        await AssertStillLeasedAsync(factory);
    }

    // -- helpers ------------------------------------------------------------------------------

    private static ApiTestFactory Factory(TimeProvider clock, IAcceptedEvidenceStore? sealer = null, ILoggerProvider? logs = null) => new()
    {
        Clock = clock,
        EnableAsynchronousFinalization = true,
        OverrideServices = services =>
        {
            if (sealer is not null)
            {
                services.RemoveAll<IAcceptedEvidenceStore>();
                services.AddSingleton(sealer);
            }
            if (logs is not null)
                services.AddSingleton(logs);
        },
    };

    private static async Task<(HttpClient Client, VisionJobLeaseContract Lease, VisionJobCompleteRequest Request)> LeasedAsync(
        ApiTestFactory factory, string workerId = "gpu-sdd-01", string[]? roles = null)
    {
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, workerId);
        var request = await BuildRequestAsync(factory, lease, roles ?? Roles);
        return (client, lease, request);
    }

    private static async Task<VisionJobFinalizationResponse> HandOffAsync(HttpClient client, VisionJobLeaseContract lease, VisionJobCompleteRequest request)
    {
        using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var ack = (await response.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!;
        Assert.Equal("finalizing", ack.State);
        return ack;
    }

    private static async Task<string> AssertStatusAsync(HttpResponseMessage response, HttpStatusCode expected)
    {
        var body = await response.Content.ReadAsStringAsync();
        Assert.True(expected == response.StatusCode, $"expected {expected}, got {response.StatusCode}: {body}");
        return body;
    }

    private static async Task AssertStillLeasedAsync(ApiTestFactory factory)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Leased, job.Status);
        Assert.Null(job.CompletionDigest);
        Assert.Null(job.FinalizationAcceptedAtUtc);
        Assert.Equal(0, await db.VisionFinalizationPayloads.CountAsync());
        Assert.Equal(0, await db.Tracks.CountAsync());
    }

    /// <summary>How many visibility sequence values have ever been allocated in this database.</summary>
    internal static async Task<long> VisibilitySequenceAllocationsAsync(ApiTestFactory factory)
    {
        await using var connection = new NpgsqlConnection(factory.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "SELECT CASE WHEN is_called THEN last_value ELSE 0 END FROM processing_visibility_sequence", connection);
        return (long)(await command.ExecuteScalarAsync())!;
    }

    private static string[] EvidenceFiles(ApiTestFactory factory) =>
        Directory.Exists(factory.EvidenceRoot) ? Directory.GetFiles(factory.EvidenceRoot, "*", SearchOption.AllDirectories) : [];

    private static byte[] CropBytes(string role) => Encoding.UTF8.GetBytes($"jpeg-evidence-{role}");

    /// <summary>A completion 3.1 body for one Track with the given roles, its crops and trajectory staged.</summary>
    internal static async Task<VisionJobCompleteRequest> BuildRequestAsync(
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
            WorkerContractRules.CompletionSchemaVersionV31,
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

    /// <summary>The request path must never seal: any call is a test failure, not a no-op.</summary>
    private sealed class SealingTrap : IAcceptedEvidenceStore
    {
        private int _calls;
        public int Calls => _calls;

        public Task<AcceptedEvidenceSealResult> SealAsync(string sourceStorageKey, string acceptedStorageKey, long expectedSizeBytes, string expectedSha256, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _calls);
            throw new InvalidOperationException("Completion 3.1 must not seal evidence in the request.");
        }

        public Task DeleteAcceptedAsync(string acceptedStorageKey, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _calls);
            throw new InvalidOperationException("Completion 3.1 must not touch accepted evidence in the request.");
        }
    }

    internal sealed record LoggedEntry(LogLevel Level, EventId EventId, string Message);

    internal sealed class CapturingLoggerProvider : ILoggerProvider
    {
        private readonly System.Collections.Concurrent.ConcurrentQueue<LoggedEntry> _entries = new();

        public IReadOnlyCollection<LoggedEntry> Entries => _entries.ToArray();

        public ILogger CreateLogger(string categoryName) => new Capturing(_entries);

        public void Dispose()
        {
        }

        private sealed class Capturing(System.Collections.Concurrent.ConcurrentQueue<LoggedEntry> entries) : ILogger
        {
            public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

            public bool IsEnabled(LogLevel logLevel) => true;

            public void Log<TState>(
                LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) =>
                entries.Enqueue(new LoggedEntry(logLevel, eventId, formatter(state, exception)));
        }
    }
}
