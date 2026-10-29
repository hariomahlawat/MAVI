using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Mavi.Api.Embeddings;
using Mavi.Application.Modules.Embeddings;
using Mavi.Contracts.Api.Tracks;
using Mavi.Contracts.Worker.Embeddings;
using Mavi.Domain.Embeddings;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

internal sealed record LeasedEmbeddingUnit(EmbeddingLeaseContract Lease, string Capability, string WorkerId)
{
    public Guid AnalysisId => Lease.AnalysisId;
    public int Attempt => Lease.AttemptCount;
}

/// <summary>
/// The real API host over a <see cref="VisualAttributeWorld"/> with the committed Development embedding release
/// (SigLIP 2 manifest and pipeline profile, 768-d), and a client speaking <c>mavi-embedding-control-v1</c>.
/// </summary>
internal sealed class EmbeddingApiHost : IAsyncDisposable
{
    public static readonly string ManifestPath = Path.Combine(VisualAttributeReleaseFixture.Root, "models", "manifests",
        "embeddings-siglip2-base-p16-224-dev-v1.json");
    public static readonly string ProfilePath = Path.Combine(VisualAttributeReleaseFixture.Root, "src", "vision", "config", "embeddings",
        "development-embeddings-siglip2-v1.json");

    private EmbeddingApiHost(VisualAttributeWorld world) => World = world;

    public VisualAttributeWorld World { get; }
    public ApiTestFactory Factory { get; private set; } = null!;
    public HttpClient Client { get; private set; } = null!;

    public static async Task<EmbeddingApiHost> CreateAsync(PostgresFixture fixture, DateTimeOffset nowUtc, bool configured = true,
        IReadOnlyDictionary<string, string?>? configuration = null)
    {
        var host = new EmbeddingApiHost(await VisualAttributeWorld.CreateAsync(fixture, nowUtc));
        var settings = new Dictionary<string, string?>
        {
            ["Embeddings:Enabled"] = "false",
            ["Embeddings:ModelManifestPath"] = configured ? ManifestPath : string.Empty,
            ["Embeddings:PipelineProfilePath"] = configured ? ProfilePath : string.Empty,
            ["Embeddings:AppearanceQueryWaitMilliseconds"] = "0",
        };
        foreach (var (key, value) in configuration ?? new Dictionary<string, string?>())
            settings[key] = value;
        host.Factory = new ApiTestFactory
        {
            Clock = host.World.Clock,
            MediaRootOverride = host.World.MediaRoot,
            EvidenceRootOverride = host.World.EvidenceRoot,
            AdditionalConfiguration = settings,
        };
        host.Client = host.Factory.CreateClient();
        // Every test drops and recreates the schema and the vector extension, so pgvector's type OID changes while
        // the process-wide Npgsql data source still caches the previous one. Reload it for this database.
        await using (var scope = host.Factory.Services.CreateAsyncScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<Mavi.Infrastructure.Persistence.MaviDbContext>();
            await db.Database.OpenConnectionAsync();
            await ((Npgsql.NpgsqlConnection)db.Database.GetDbConnection()).ReloadTypesAsync();
        }

        return host;
    }

    public string Fingerprint => Factory.Services.GetRequiredService<IEmbeddingRelease>().Resolution.Definition!.Identity.Fingerprint;

    public Task<EmbeddingCycleResult> RunCycleAsync() =>
        Factory.Services.GetRequiredService<EmbeddingHostedService>().RunCycleAsync(CancellationToken.None);

    public async Task<EmbeddingAnalysis> UnitAsync(Guid analysisId)
    {
        await using var db = World.Read();
        return await db.EmbeddingAnalyses.AsNoTracking().SingleAsync(x => x.Id == analysisId);
    }

    public Task<HttpResponseMessage> PostLeaseAsync(string workerId, string? fingerprint = null) =>
        Client.PostAsJsonAsync($"{EmbeddingContractRules.AnalysisRoutePrefix}/lease", new
        {
            schemaVersion = EmbeddingContractRules.SchemaVersion,
            workerId,
            identityFingerprint = fingerprint ?? Fingerprint,
        });

    public async Task<LeasedEmbeddingUnit> LeaseAsync(string workerId = "embeddings-01")
    {
        using var response = await PostLeaseAsync(workerId);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        // The wire format the worker's contract requires (embedding-lease-v1 "utc"): UTC instants end in Z.
        var raw = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
        Assert.EndsWith("Z", raw.GetProperty("leaseExpiresAtUtc").GetString(), StringComparison.Ordinal);
        Assert.EndsWith("Z", raw.GetProperty("deadlineAtUtc").GetString(), StringComparison.Ordinal);
        var lease = raw.Deserialize<EmbeddingLeaseContract>(JsonSerializerOptions.Web);
        return new LeasedEmbeddingUnit(lease!, Assert.Single(response.Headers.GetValues(EmbeddingContractRules.CapabilityHeader)), workerId);
    }

    public Task<HttpResponseMessage> EvidenceAsync(LeasedEmbeddingUnit unit, Guid observationId)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, $"{EmbeddingContractRules.AnalysisRoutePrefix}/{unit.AnalysisId}/evidence/{observationId}");
        request.Headers.Add(EmbeddingContractRules.CapabilityHeader, unit.Capability);
        request.Headers.Add(EmbeddingContractRules.WorkerHeader, unit.WorkerId);
        request.Headers.Add(EmbeddingContractRules.AttemptHeader, unit.Attempt.ToString(System.Globalization.CultureInfo.InvariantCulture));
        return Client.SendAsync(request);
    }

    public Task<HttpResponseMessage> CompleteAsync(LeasedEmbeddingUnit unit, string body, string? capability = null) =>
        SendRawAsync($"{EmbeddingContractRules.AnalysisRoutePrefix}/{unit.AnalysisId}/complete", capability ?? unit.Capability, body);

    public Task<HttpResponseMessage> FailAsync(LeasedEmbeddingUnit unit, string code) =>
        SendRawAsync($"{EmbeddingContractRules.AnalysisRoutePrefix}/{unit.AnalysisId}/fail", unit.Capability, JsonSerializer.Serialize(new
        {
            schemaVersion = EmbeddingContractRules.SchemaVersion,
            analysisId = unit.AnalysisId,
            workerId = unit.WorkerId,
            attemptCount = unit.Attempt,
            failureCode = code,
        }));

    public async Task<HttpResponseMessage> SendRawAsync(string path, string? capability, string body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        if (capability is not null) request.Headers.Add(EmbeddingContractRules.CapabilityHeader, capability);
        return await Client.SendAsync(request);
    }

    /// <summary>A completion body exactly as the worker writes it: every leased Track in lease order.</summary>
    public static string CompletionBody(LeasedEmbeddingUnit unit, Func<EmbeddingLeaseTrackContract, int, object> track) =>
        JsonSerializer.Serialize(new
        {
            schemaVersion = EmbeddingContractRules.SchemaVersion,
            analysisId = unit.AnalysisId,
            workerId = unit.WorkerId,
            attemptCount = unit.Attempt,
            provenance = new
            {
                roleId = "embeddings",
                identityFingerprint = unit.Lease.Identity.Fingerprint,
                runtimeProfileId = "embeddings-onnx-v1",
                runtimeVariant = "windows-x86_64-cpu",
                executionProvider = "CPUExecutionProvider",
                actualDevice = "cpu",
                deviceResolutionReason = "explicit_cpu",
                onnxRuntimeVersion = "1.31.0",
                workerVersion = "1.0.0",
            },
            tracks = unit.Lease.Tracks.Select((item, index) => track(item, index)).ToArray(),
        });

    public static object Embedded(EmbeddingLeaseTrackContract track, float[] vector) => new
    {
        trackId = track.TrackId,
        outcome = "embedded",
        sourceObservationIds = track.Observations.Select(item => item.ObservationId).ToArray(),
        embedding = EmbeddingContractRules.EncodeVector(vector),
    };

    public static object Unavailable(EmbeddingLeaseTrackContract track, string reason) => new
    {
        trackId = track.TrackId,
        outcome = "unavailable",
        reason,
    };

    /// <summary>A unit vector in 768-d mostly along axis <paramref name="axis"/>, tilted towards axis 0 by <paramref name="tilt"/>.</summary>
    public static float[] Axis(int axis, double tilt = 0)
    {
        var vector = new float[768];
        vector[axis] = (float)Math.Cos(tilt);
        vector[0] += (float)Math.Sin(tilt);
        var norm = Math.Sqrt(vector.Sum(value => (double)value * value));
        return vector.Select(value => (float)(value / norm)).ToArray();
    }

    public async Task<JsonElement> SimilarAsync(Guid trackId, string query = "")
    {
        using var response = await Client.GetAsync($"/api/tracks/{trackId}/similar{query}");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    public async ValueTask DisposeAsync()
    {
        Client.Dispose();
        await Factory.DisposeAsync();
        World.Dispose();
    }
}

/// <summary>
/// The embedding lifecycle and similarity search through the real API host and PostgreSQL (PoC S4; register rows
/// C5.2 and C5.3): lease, evidence, completion validation and replay, failure isolation, ranked similarity
/// candidates, snapshot replay and fingerprint, the appearance text query, and no <c>EntityId</c> written.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class EmbeddingApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);

    private static async Task<SeededRun> ActivateAndSeedAsync(EmbeddingApiHost host, int persons = 3, int vehicles = 1, int crops = 2)
    {
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        return await host.World.SeedRunAsync(persons, vehicles, crops, completedAtUtc: host.World.Clock.GetUtcNow());
    }

    private static async Task<string?> CodeAsync(HttpResponseMessage response) => await VisualAttributeApiHost.ProblemCodeAsync(response);

    /// <summary>Persons 0, 1, 2 along axis 1 with tilts 0, 0.3, 0.9 (so 1 is nearer to 0 than 2 is); the vehicle on axis 7.</summary>
    private static async Task<LeasedEmbeddingUnit> LeaseAndPublishAsync(EmbeddingApiHost host, params double[] personTilts)
    {
        var unit = await host.LeaseAsync();
        var persons = 0;
        var body = EmbeddingApiHost.CompletionBody(unit, (track, _) => track.ObjectClass == "Person"
            ? EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(1, personTilts[persons++]))
            : EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(7)));
        using var response = await host.CompleteAsync(unit, body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return unit;
    }

    [Fact]
    public async Task ARunIsLeasedEmbeddedPublishedAndRankedAsSimilarityCandidates()
    {
        await using var host = await EmbeddingApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host);
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);

        var unit = await host.LeaseAsync();
        Assert.Equal(host.Fingerprint, unit.Lease.Identity.Fingerprint);
        Assert.Equal(768, unit.Lease.Identity.Model.Dimension);
        Assert.Equal(run.Tracks.Select(track => track.TrackId), unit.Lease.Tracks.Select(track => track.TrackId));
        Assert.All(unit.Lease.Tracks, track => Assert.Equal([0, 1], track.Observations.Select(item => item.EvidenceRank)));

        // The crop is served lease-scoped, exactly as accepted.
        var crop = run.Track(0).Observations[0];
        using (var evidence = await host.EvidenceAsync(unit, crop.ObservationId))
        {
            Assert.Equal(HttpStatusCode.OK, evidence.StatusCode);
            Assert.Equal(crop.Bytes, await evidence.Content.ReadAsByteArrayAsync());
        }

        var persons = 0;
        var tilts = new[] { 0.0, 0.3, 0.9 };
        var body = EmbeddingApiHost.CompletionBody(unit, (track, _) => track.ObjectClass == "Person"
            ? EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(1, tilts[persons++]))
            : EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(7)));
        using (var completed = await host.CompleteAsync(unit, body))
        {
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
            var json = await completed.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal("completed", json.GetProperty("status").GetString());
            Assert.Equal(4, json.GetProperty("tracksEmbedded").GetInt32());
        }

        // An identical replay is idempotent; a different body for the published unit is a conflict.
        using (var replay = await host.CompleteAsync(unit, body))
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        using (var conflict = await host.CompleteAsync(unit, body.Replace("\"1.0.0\"", "\"1.0.1\"", StringComparison.Ordinal)))
            Assert.Equal("embedding_completion_conflict", await CodeAsync(conflict));

        var similar = await host.SimilarAsync(run.Track(0).TrackId);
        Assert.Equal("ready", similar.GetProperty("state").GetString());
        Assert.Equal(TrackSimilarityContractRules.Label, similar.GetProperty("label").GetString());
        var candidates = similar.GetProperty("candidates").EnumerateArray().ToList();
        // Default class: Persons only, the query Track itself excluded, nearest first, scores descending.
        Assert.Equal([run.Track(1).TrackId, run.Track(2).TrackId], candidates.Select(item => item.GetProperty("track").GetProperty("id").GetGuid()));
        Assert.Equal([1, 2], candidates.Select(item => item.GetProperty("rank").GetInt32()));
        Assert.Equal(Math.Cos(0.3), candidates[0].GetProperty("score").GetDouble(), 3);
        Assert.Equal(run.Track(1).Observations[0].ObservationId, candidates[0].GetProperty("sourceObservationId").GetGuid());
        Assert.False(string.IsNullOrEmpty(similar.GetProperty("snapshot").GetString()));

        var vehicles = await host.SimilarAsync(run.Track(0).TrackId, "?objectClass=Vehicle&k=5");
        Assert.Equal(run.Track(3).TrackId, Assert.Single(vehicles.GetProperty("candidates").EnumerateArray()).GetProperty("track").GetProperty("id").GetGuid());

        // Similarity candidates never become identity: no Entity, no EntityId.
        await using var db = host.World.Read();
        Assert.All(await db.Tracks.AsNoTracking().ToListAsync(), track => Assert.Null(track.EntityId));
        Assert.Empty(await db.Entities.AsNoTracking().ToListAsync());
    }

    [Fact]
    public async Task ASnapshotReplaysTheSameRankingAfterANewerPublicationAndRefusesOtherFilters()
    {
        await using var host = await EmbeddingApiHost.CreateAsync(fixture, T0);
        var first = await ActivateAndSeedAsync(host);
        await host.RunCycleAsync();
        await LeaseAndPublishAsync(host, 0.0, 0.5, 0.9);

        var before = await host.SimilarAsync(first.Track(0).TrackId);
        var snapshot = before.GetProperty("snapshot").GetString()!;
        var beforeIds = before.GetProperty("candidates").EnumerateArray().Select(item => item.GetProperty("track").GetProperty("id").GetGuid()).ToList();

        // A newer run publishes a Person nearer to the query than any existing candidate.
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        var second = await host.World.SeedRunAsync(1, 0, 1, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        await LeaseAndPublishAsync(host, 0.1);

        var fresh = await host.SimilarAsync(first.Track(0).TrackId);
        Assert.Equal(second.Track(0).TrackId, fresh.GetProperty("candidates")[0].GetProperty("track").GetProperty("id").GetGuid());

        var replay = await host.SimilarAsync(first.Track(0).TrackId, $"?snapshot={snapshot}");
        Assert.Equal(beforeIds, replay.GetProperty("candidates").EnumerateArray().Select(item => item.GetProperty("track").GetProperty("id").GetGuid()));
        Assert.Equal(before.GetProperty("snapshotUtc").GetString(), replay.GetProperty("snapshotUtc").GetString());

        // The snapshot's fingerprint covers k and the scope: replayed with other filters it is refused.
        using (var other = await host.Client.GetAsync($"/api/tracks/{first.Track(0).TrackId}/similar?k=3&snapshot={snapshot}"))
            Assert.Equal("similarity_query_invalid", await CodeAsync(other));
        using (var tampered = await host.Client.GetAsync($"/api/tracks/{first.Track(0).TrackId}/similar?snapshot={snapshot[..^2]}AA"))
            Assert.Equal(HttpStatusCode.BadRequest, tampered.StatusCode);
        using (var foreign = await host.Client.GetAsync($"/api/tracks/{first.Track(1).TrackId}/similar?snapshot={snapshot}"))
            Assert.Equal("similarity_query_invalid", await CodeAsync(foreign));
        // An hour later the token has expired.
        host.World.Clock.Advance(TimeSpan.FromMinutes(61));
        using (var expired = await host.Client.GetAsync($"/api/tracks/{first.Track(0).TrackId}/similar?snapshot={snapshot}"))
            Assert.Equal("similarity_query_invalid", await CodeAsync(expired));
    }

    [Fact]
    public async Task SimilarityStatesArePendingUnavailableAndNotConfiguredWithoutCandidates()
    {
        await using var host = await EmbeddingApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 2, vehicles: 0, crops: 1);
        await host.RunCycleAsync();
        Assert.Equal("pending", (await host.SimilarAsync(run.Track(0).TrackId)).GetProperty("state").GetString());

        var unit = await host.LeaseAsync();
        var body = EmbeddingApiHost.CompletionBody(unit, (track, index) => index == 0
            ? EmbeddingApiHost.Unavailable(track, "evidence_too_small")
            : EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(3)));
        using (var completed = await host.CompleteAsync(unit, body))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);

        var unavailable = await host.SimilarAsync(run.Track(0).TrackId);
        Assert.Equal("unavailable", unavailable.GetProperty("state").GetString());
        Assert.Equal("evidence_too_small", unavailable.GetProperty("reason").GetString());
        Assert.Empty(unavailable.GetProperty("candidates").EnumerateArray());
        // The Track whose evidence was too small is never anyone's candidate either.
        Assert.Empty((await host.SimilarAsync(run.Track(1).TrackId)).GetProperty("candidates").EnumerateArray());

        using (var missing = await host.Client.GetAsync($"/api/tracks/{Guid.CreateVersion7()}/similar"))
            Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
        using (var unknownKey = await host.Client.GetAsync($"/api/tracks/{run.Track(0).TrackId}/similar?threshold=0.9"))
            Assert.Equal("similarity_query_invalid", await CodeAsync(unknownKey));
        using (var tooMany = await host.Client.GetAsync($"/api/tracks/{run.Track(0).TrackId}/similar?k=51"))
            Assert.Equal("similarity_query_invalid", await CodeAsync(tooMany));

        await using var bare = await EmbeddingApiHost.CreateAsync(fixture, T0, configured: false);
        var other = await bare.World.SeedRunAsync(1, 0, 1, completedAtUtc: T0);
        Assert.Equal("notConfigured", (await bare.SimilarAsync(other.Track(0).TrackId)).GetProperty("state").GetString());
        using var appearance = await bare.Client.GetAsync("/api/tracks?appearanceQuery=red%20jacket");
        Assert.Equal("embeddings_not_configured", await CodeAsync(appearance));
    }

    [Fact]
    public async Task ACompletionThatDoesNotDescribeTheLeaseIsRefusedAndPublishesNothing()
    {
        await using var host = await EmbeddingApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host, persons: 2, vehicles: 0, crops: 2);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        var foreign = Guid.CreateVersion7();

        string Body(Func<EmbeddingLeaseTrackContract, int, object> track) => EmbeddingApiHost.CompletionBody(unit, track);
        var cases = new[]
        {
            // Reordered Tracks.
            EmbeddingApiHost.CompletionBody(unit with { Lease = unit.Lease with { Tracks = [.. unit.Lease.Tracks.Reverse()] } },
                (track, _) => EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(2))),
            // A source Observation that was never leased.
            Body((track, _) => new { trackId = track.TrackId, outcome = "embedded", sourceObservationIds = new[] { foreign },
                embedding = EmbeddingContractRules.EncodeVector(EmbeddingApiHost.Axis(2)) }),
            // A vector that is not unit length.
            Body((track, _) => new { trackId = track.TrackId, outcome = "embedded",
                sourceObservationIds = track.Observations.Select(item => item.ObservationId).ToArray(),
                embedding = EmbeddingContractRules.EncodeVector(new float[768]) }),
            // A vector of the wrong dimension.
            Body((track, _) => new { trackId = track.TrackId, outcome = "embedded",
                sourceObservationIds = track.Observations.Select(item => item.ObservationId).ToArray(),
                embedding = EmbeddingContractRules.EncodeVector(new float[] { 1f }) }),
            // no_evidence for a Track that has crops.
            Body((track, _) => EmbeddingApiHost.Unavailable(track, "no_evidence")),
        };
        foreach (var body in cases)
        {
            using var refused = await host.CompleteAsync(unit, body);
            Assert.Equal(HttpStatusCode.UnprocessableEntity, refused.StatusCode);
        }

        // Another identity's provenance and a foreign capability are refused too.
        using (var identity = await host.CompleteAsync(unit, Body((track, _) => EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(2)))
                   .Replace(unit.Lease.Identity.Fingerprint, new string('e', 64), StringComparison.Ordinal)))
            Assert.Equal("embedding_identity_mismatch", await CodeAsync(identity));
        using (var stolen = await host.CompleteAsync(unit, Body((track, _) => EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(2))),
                   capability: new string('A', 43)))
            Assert.Equal(HttpStatusCode.Conflict, stolen.StatusCode);

        Assert.Equal(EmbeddingAnalysisStatus.Running, (await host.UnitAsync(unit.AnalysisId)).Status);
        await using var db = host.World.Read();
        Assert.Empty(await db.TrackEmbeddings.AsNoTracking().ToListAsync());
        Assert.Equal("pending", (await host.SimilarAsync(run.Track(0).TrackId)).GetProperty("state").GetString());
    }

    [Fact]
    public async Task AnEmbeddingCrashFailureOrExhaustionLeavesTheRunTracksAndOtherUnitsUntouched()
    {
        await using var host = await EmbeddingApiHost.CreateAsync(fixture, T0,
            configuration: new Dictionary<string, string?> { ["Embeddings:MaximumAttempts"] = "2" });
        var run = await ActivateAndSeedAsync(host, persons: 1, vehicles: 1, crops: 1);
        await host.RunCycleAsync();
        await using (var db = host.World.Read())
        {
            db.VisualAttributeAnalyses.Add(VisualAttributeAnalysis.Queue(run.RunId, VisualAttributeTestIdentity.Fields(), host.World.Clock.GetUtcNow()));
            await db.SaveChangesAsync();
        }

        (ProcessingRunStatus Status, long? Visibility, DateTimeOffset? Completed, int Tracks, int Observations) Snapshot(
            Mavi.Infrastructure.Persistence.MaviDbContext db)
        {
            var processing = db.ProcessingRuns.AsNoTracking().Single(x => x.Id == run.RunId);
            return (processing.Status, processing.VisibilitySequence, processing.CompletedAtUtc,
                db.Tracks.AsNoTracking().Count(x => x.ProcessingRunId == run.RunId), db.Observations.AsNoTracking().Count());
        }

        (ProcessingRunStatus, long?, DateTimeOffset?, int, int) before;
        await using (var db = host.World.Read()) before = Snapshot(db);

        // Attempt 1 fails retryably (requeued); attempt 2 takes the lease and dies: the unit is exhausted.
        var first = await host.LeaseAsync();
        using (var failed = await host.FailAsync(first, "embedding_runtime_failed"))
            Assert.Equal("requeued", (await failed.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("outcome").GetString());
        var second = await host.LeaseAsync();
        Assert.Equal(2, second.Attempt);
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        Assert.Equal(1, (await host.RunCycleAsync()).ExhaustedFailed);
        var unit = await host.UnitAsync(second.AnalysisId);
        Assert.Equal(EmbeddingAnalysisStatus.Failed, unit.Status);
        Assert.Equal(EmbeddingAnalysis.AttemptsExhaustedCode, unit.FailureCode);

        // A late completion of the dead attempt cannot publish.
        using (var late = await host.CompleteAsync(second,
                   EmbeddingApiHost.CompletionBody(second, (track, _) => EmbeddingApiHost.Embedded(track, EmbeddingApiHost.Axis(4)))))
            Assert.Equal(HttpStatusCode.Conflict, late.StatusCode);

        await using (var db = host.World.Read())
        {
            Assert.Equal(before, Snapshot(db));
            Assert.Equal(VisualAttributeAnalysisStatus.Queued, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);
            Assert.Empty(await db.TrackEmbeddings.AsNoTracking().ToListAsync());
        }

        // Track search over the run is unaffected.
        using var search = await host.Client.GetAsync($"/api/tracks?processingRunId={run.RunId}");
        Assert.Equal(2, (await search.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("items").GetArrayLength());
    }

    [Fact]
    public async Task AnAppearanceQueryIsQueuedEmbeddedByTheWorkerThenRankedWithASnapshot()
    {
        await using var host = await EmbeddingApiHost.CreateAsync(fixture, T0);
        var run = await ActivateAndSeedAsync(host);
        await host.RunCycleAsync();
        await LeaseAndPublishAsync(host, 0.0, 0.5, 1.2);

        // Not yet embedded: 503 with Retry-After, and the normalised text is queued for the worker.
        using (var pending = await host.Client.GetAsync("/api/tracks?appearanceQuery=%20%20Red%20%20Jacket%20"))
        {
            Assert.Equal(HttpStatusCode.ServiceUnavailable, pending.StatusCode);
            Assert.Equal("appearance_query_pending", await CodeAsync(pending));
            Assert.True(pending.Headers.Contains("Retry-After"));
        }

        using var lease = await host.Client.PostAsJsonAsync($"{EmbeddingContractRules.TextQueryRoutePrefix}/lease", new
        {
            schemaVersion = EmbeddingContractRules.SchemaVersion,
            workerId = "embeddings-01",
            identityFingerprint = host.Fingerprint,
        });
        Assert.Equal(HttpStatusCode.OK, lease.StatusCode);
        var textJson = JsonDocument.Parse(await lease.Content.ReadAsStringAsync()).RootElement;
        Assert.EndsWith("Z", textJson.GetProperty("leaseExpiresAtUtc").GetString(), StringComparison.Ordinal);
        var text = textJson.Deserialize<EmbeddingTextQueryLeaseContract>(JsonSerializerOptions.Web);
        Assert.Equal("red jacket", text!.Text);
        var capability = Assert.Single(lease.Headers.GetValues(EmbeddingContractRules.CapabilityHeader));
        using (var completed = await host.SendRawAsync($"{EmbeddingContractRules.TextQueryRoutePrefix}/{text.QueryId}/complete", capability,
                   JsonSerializer.Serialize(new
                   {
                       schemaVersion = EmbeddingContractRules.SchemaVersion,
                       queryId = text.QueryId,
                       workerId = "embeddings-01",
                       attemptCount = text.AttemptCount,
                       embedding = EmbeddingContractRules.EncodeVector(EmbeddingApiHost.Axis(1, 0.05)),
                   })))
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);

        // The same text, spelled differently, is the same query.
        using var ready = await host.Client.GetAsync("/api/tracks?appearanceQuery=RED%20jacket&objectClass=Person&limit=2");
        Assert.Equal(HttpStatusCode.OK, ready.StatusCode);
        var page = await ready.Content.ReadFromJsonAsync<JsonElement>();
        var items = page.GetProperty("items").EnumerateArray().ToList();
        Assert.Equal([run.Track(0).TrackId, run.Track(1).TrackId], items.Select(item => item.GetProperty("id").GetGuid()));
        Assert.True(items[0].GetProperty("appearanceScore").GetDouble() > items[1].GetProperty("appearanceScore").GetDouble());
        Assert.Equal(JsonValueKind.Null, page.GetProperty("nextCursor").ValueKind);
        var appearance = page.GetProperty("appearance");
        Assert.Equal(TrackSimilarityContractRules.Label, appearance.GetProperty("label").GetString());
        var snapshot = appearance.GetProperty("snapshot").GetString();

        using (var replay = await host.Client.GetAsync($"/api/tracks?appearanceQuery=red%20jacket&objectClass=Person&limit=2&appearanceSnapshot={snapshot}"))
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        using (var mismatch = await host.Client.GetAsync($"/api/tracks?appearanceQuery=blue%20jacket&objectClass=Person&limit=2&appearanceSnapshot={snapshot}"))
            Assert.Equal("appearance_query_invalid", await CodeAsync(mismatch));
        using (var combined = await host.Client.GetAsync("/api/tracks?appearanceQuery=red%20jacket&plateText=AB12"))
            Assert.Equal("appearance_query_combination_unsupported", await CodeAsync(combined));
        using (var empty = await host.Client.GetAsync("/api/tracks?appearanceQuery=%20%20"))
            Assert.Equal("appearance_query_invalid", await CodeAsync(empty));
        using (var tooLong = await host.Client.GetAsync($"/api/tracks?appearanceQuery={new string('a', 201)}"))
            Assert.Equal("appearance_query_invalid", await CodeAsync(tooLong));

        await using var db = host.World.Read();
        Assert.All(await db.Tracks.AsNoTracking().ToListAsync(), track => Assert.Null(track.EntityId));
    }

    [Fact]
    public async Task AWorkerOfAnotherIdentityLeasesNothing()
    {
        await using var host = await EmbeddingApiHost.CreateAsync(fixture, T0);
        await ActivateAndSeedAsync(host);
        await host.RunCycleAsync();
        using var other = await host.PostLeaseAsync("embeddings-01", new string('d', 64));
        Assert.Equal(HttpStatusCode.NoContent, other.StatusCode);
        using var capabilityInRequest = new HttpRequestMessage(HttpMethod.Post, $"{EmbeddingContractRules.AnalysisRoutePrefix}/lease")
        {
            Content = JsonContent.Create(new { schemaVersion = EmbeddingContractRules.SchemaVersion, workerId = "embeddings-01", identityFingerprint = host.Fingerprint }),
        };
        capabilityInRequest.Headers.Add(EmbeddingContractRules.CapabilityHeader, new string('A', 43));
        using var refused = await host.Client.SendAsync(capabilityInRequest);
        Assert.Equal("embedding_capability_unexpected", await CodeAsync(refused));
    }
}
