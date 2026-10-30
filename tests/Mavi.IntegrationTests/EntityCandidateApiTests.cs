using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Api.Embeddings;
using Mavi.Api.Endpoints;
using Mavi.Api.Entities;
using Mavi.Api.Faces;
using Mavi.Application.Deployment;
using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Embeddings;
using Mavi.Application.Modules.Entities;
using Mavi.Contracts.Worker.Embeddings;
using Mavi.Contracts.Worker.Faces;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>A Track to seed: its class, camera and its interval in seconds from the world's origin.</summary>
internal sealed record EntitySeedTrack(ObjectClass ObjectClass, double StartSeconds, double EndSeconds, float[] Vector);

/// <summary>
/// The real API host over a <see cref="VisualAttributeWorld"/> with the committed Development embedding and face releases, the
/// PoC profile and the labelled Development operator. Embedding and face units are completed through their real worker
/// contracts; Entity-candidate derivation is driven one cycle at a time.
/// </summary>
internal sealed class EntityApiHost : IAsyncDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "mavi-entity-tests", Guid.NewGuid().ToString("N"));
    private readonly Dictionary<Guid, float[]> _vectors = [];
    private readonly Dictionary<Guid, float[]> _faces = [];

    private EntityApiHost(VisualAttributeWorld world) => World = world;

    public VisualAttributeWorld World { get; }
    public ApiTestFactory Factory { get; private set; } = null!;
    public HttpClient Client { get; private set; } = null!;

    /// <summary>The instant every seeded interval is measured from.</summary>
    public DateTimeOffset Origin { get; private set; }

    public static async Task<EntityApiHost> CreateAsync(PostgresFixture fixture, DateTimeOffset nowUtc, string identityMode = "development-unattributed")
    {
        var host = new EntityApiHost(await VisualAttributeWorld.CreateAsync(fixture, nowUtc)) { Origin = nowUtc.AddHours(-2) };
        Directory.CreateDirectory(host._root);
        var metadata = Path.Combine(host._root, "release.json");
        File.WriteAllText(metadata, $$"""
            {
              "schemaVersion": "mavi-poc-release-metadata-v1",
              "profile": "poc-single-host",
              "productionQualified": false,
              "evidenceClass": "Development",
              "identityMode": "windows-negotiate",
              "application": { "revision": "{{new string('c', 40)}}" },
              "packs": []
            }
            """);
        host.Factory = new ApiTestFactory
        {
            Clock = host.World.Clock,
            MediaRootOverride = host.World.MediaRoot,
            EvidenceRootOverride = host.World.EvidenceRoot,
            AdditionalConfiguration = new Dictionary<string, string?>
            {
                ["Embeddings:Enabled"] = "false",
                ["Embeddings:ModelManifestPath"] = EmbeddingApiHost.ManifestPath,
                ["Embeddings:PipelineProfilePath"] = EmbeddingApiHost.ProfilePath,
                ["Embeddings:AppearanceQueryWaitMilliseconds"] = "0",
                ["Faces:Enabled"] = "true",
                ["Faces:ModelManifestPath"] = FaceApiHost.ManifestPath,
                ["Faces:PipelineProfilePath"] = FaceApiHost.ProfilePath,
                ["EntityCandidates:Enabled"] = "false",
                ["AnalyticEvents:Enabled"] = "false",
                ["Identity:Mode"] = identityMode,
                ["Deployment:Profile"] = DeploymentProfiles.PocSingleHost,
                ["Deployment:ReleaseMetadataPath"] = metadata,
            },
        };
        host.Client = host.Factory.CreateClient();
        await using (var scope = host.Factory.Services.CreateAsyncScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            await db.Database.OpenConnectionAsync();
            await ((NpgsqlConnection)db.Database.GetDbConnection()).ReloadTypesAsync();
        }

        // Every camera of these tests is in one declared site unless a test says otherwise (catalogue v2, D-S7-3).
        await using (var db = host.World.Read())
            await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE cameras SET site_code = {Site} WHERE id = {host.World.CameraId}");

        // Activate the embedding identity, so runs completed after this are queued.
        await host.Factory.Services.GetRequiredService<EmbeddingHostedService>().RunCycleAsync(CancellationToken.None);
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        return host;
    }

    public const string Site = "site-a";

    /// <summary>Another camera, in <paramref name="site"/> (null: no declared site).</summary>
    public async Task<Guid> CameraAsync(string code, string? site = Site)
    {
        var camera = Mavi.Domain.Cameras.Camera.Create(code, "Entity test camera " + code, "UTC", World.Clock.GetUtcNow(), site);
        await using var db = World.Read();
        db.Cameras.Add(camera);
        await db.SaveChangesAsync();
        return camera.Id;
    }

    public string Fingerprint => Factory.Services.GetRequiredService<IEmbeddingRelease>().Resolution.Definition!.Identity.Fingerprint;

    /// <summary>A completed, visible run on <paramref name="cameraId"/> (a new video unless <paramref name="videoAssetId"/> is given).</summary>
    public async Task<(Guid RunId, Guid VideoAssetId, IReadOnlyList<Guid> TrackIds)> SeedAsync(Guid cameraId, IReadOnlyList<EntitySeedTrack> tracks,
        Guid? videoAssetId = null, IReadOnlyList<float[]?>? faces = null)
    {
        var now = World.Clock.GetUtcNow();
        var entities = new List<object>();
        Guid videoId;
        if (videoAssetId is { } existing)
        {
            videoId = existing;
        }
        else
        {
            var source = Artifact.Create(ArtifactType.SourceVideo, $"source/entities/{Guid.CreateVersion7()}.mp4", "video/mp4", 1,
                Convert.ToHexStringLower(SHA256.HashData(Guid.NewGuid().ToByteArray())));
            var video = VideoAsset.Create(cameraId, source.Id, "entities.mp4", Origin, 3_600_000, 25, 1, 640, 360, "h264", TimestampSource.Manual, 1.0);
            entities.Add(source);
            entities.Add(video);
            videoId = video.Id;
        }

        var run = ProcessingRun.Create(videoId, "phase1-detection-tracking-v1", "{}", now.AddMinutes(-5));
        run.MarkRunning("vision-01", now.AddMinutes(-4));
        run.MarkCompleted(100, tracks.Count, 1_000, now);
        entities.Add(run);
        var ids = new List<Guid>();
        for (var index = 0; index < tracks.Count; index++)
        {
            var seed = tracks[index];
            var track = Track.Create(run.Id, videoId, index + 1, seed.ObjectClass, (long)(seed.StartSeconds * 1000), (long)(seed.EndSeconds * 1000),
                Origin, 4, 0.8, 0.9, now);
            var bytes = VisualAttributeWorld.FakeJpeg(track.Id, 0);
            var sha256 = Convert.ToHexStringLower(SHA256.HashData(bytes));
            var storageKey = $"evidence/{run.Id:D}/attempt-0001/crops/{track.Id:N}-0-{sha256}.jpg";
            var artifact = Artifact.Create(ArtifactType.EvidenceCrop, storageKey, "image/jpeg", bytes.Length, sha256);
            var observation = Observation.Create(track.Id, ObservationType.Representative, 0, (long)(seed.StartSeconds * 1000), Origin,
                0.1f, 0.1f, 0.2f, 0.2f, 0.8, 0.7, 0, 0.7);
            observation.AttachEvidenceArtifact(artifact.Id);
            await World.WriteEvidenceAsync(storageKey, bytes);
            entities.Add(track);
            entities.Add(artifact);
            entities.Add(observation);
            ids.Add(track.Id);
            _vectors[track.Id] = seed.Vector;
            if (faces?[index] is { } face) _faces[track.Id] = face;
        }

        await using var db = World.Read();
        db.AddRange(entities);
        await db.SaveChangesAsync();
        var sequence = await NextSequenceAsync(db);
        await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE processing_runs SET visibility_sequence = {sequence} WHERE id = {run.Id}");
        World.Clock.Advance(TimeSpan.FromSeconds(1));
        return (run.Id, videoId, ids);
    }

    /// <summary>Queues and completes every pending embedding unit with the seeded vectors.</summary>
    public async Task EmbedAllAsync()
    {
        await Factory.Services.GetRequiredService<EmbeddingHostedService>().RunCycleAsync(CancellationToken.None);
        while (true)
        {
            using var response = await Client.PostAsJsonAsync($"{EmbeddingContractRules.AnalysisRoutePrefix}/lease", new
            {
                schemaVersion = EmbeddingContractRules.SchemaVersion,
                workerId = "embeddings-01",
                identityFingerprint = Fingerprint,
            });
            if (response.StatusCode == HttpStatusCode.NoContent) return;
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            var lease = (await response.Content.ReadFromJsonAsync<EmbeddingLeaseContract>(JsonSerializerOptions.Web))!;
            var unit = new LeasedEmbeddingUnit(lease, Assert.Single(response.Headers.GetValues(EmbeddingContractRules.CapabilityHeader)), "embeddings-01");
            var body = EmbeddingApiHost.CompletionBody(unit, (track, _) => _vectors.TryGetValue(track.TrackId, out var vector)
                ? EmbeddingApiHost.Embedded(track, vector)
                : EmbeddingApiHost.Unavailable(track, "evidence_too_small"));
            using var completed = await SendRawAsync($"{EmbeddingContractRules.AnalysisRoutePrefix}/{unit.AnalysisId}/complete",
                EmbeddingContractRules.CapabilityHeader, unit.Capability, body);
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        }
    }

    /// <summary>Opts the cameras in, then queues and completes every face unit: seeded faces observed, the rest no face.</summary>
    public async Task FacesAllAsync(params Guid[] cameraIds)
    {
        foreach (var camera in cameraIds)
        {
            using var optIn = await Client.PutAsJsonAsync($"/api/cameras/{camera}/face-analysis", new { enabled = true });
            Assert.Equal(HttpStatusCode.OK, optIn.StatusCode);
        }

        await Factory.Services.GetRequiredService<FaceHostedService>().RunCycleAsync(CancellationToken.None);
        var fingerprint = Factory.Services.GetRequiredService<Mavi.Application.Modules.Faces.IFaceRelease>().Resolution.Definition!.Identity.Fingerprint;
        while (true)
        {
            using var response = await Client.PostAsJsonAsync($"{FaceContractRules.AnalysisRoutePrefix}/lease", new
            {
                schemaVersion = FaceContractRules.SchemaVersion,
                workerId = "faces-01",
                identityFingerprint = fingerprint,
            });
            if (response.StatusCode == HttpStatusCode.NoContent) return;
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            var lease = (await response.Content.ReadFromJsonAsync<FaceLeaseContract>(JsonSerializerOptions.Web))!;
            var unit = new LeasedFaceUnit(lease, Assert.Single(response.Headers.GetValues(FaceContractRules.CapabilityHeader)), "faces-01");
            var body = FaceApiHost.CompletionBody(unit, (track, _) => _faces.TryGetValue(track.TrackId, out var face)
                ? FaceApiHost.Observed(track, face)
                : FaceApiHost.Unknown(track, "no_face_detected"));
            using var completed = await SendRawAsync($"{FaceContractRules.AnalysisRoutePrefix}/{unit.AnalysisId}/complete",
                FaceContractRules.CapabilityHeader, unit.Capability, body);
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        }
    }

    public Task<int> DeriveAsync() =>
        Factory.Services.GetRequiredService<EntityCandidatesHostedService>().RunCycleAsync(new EntityCandidatesOptions { BatchSize = 50 }, CancellationToken.None);

    public async Task<JsonElement> GetJsonAsync(string path)
    {
        using var response = await Client.GetAsync(path);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    public async Task<List<JsonElement>> CandidatesAsync(string query = "") =>
        (await GetJsonAsync("/api/entity-candidates" + query)).GetProperty("candidates").EnumerateArray().ToList();

    public Task<HttpResponseMessage> DecideAsync(Guid candidateId, string decision, string? note = null) =>
        Client.PostAsJsonAsync($"/api/entity-candidates/{candidateId}/{decision}", new { note });

    public async Task<int> AuditCountAsync(string? action = null)
    {
        await using var db = World.Read();
        return await db.AuditEntries.CountAsync(x => action == null || x.Action == action);
    }

    public async Task<Dictionary<Guid, Guid?>> EntityIdsAsync(params Guid[] trackIds)
    {
        await using var db = World.Read();
        return await db.Tracks.AsNoTracking().Where(x => trackIds.Contains(x.Id)).ToDictionaryAsync(x => x.Id, x => x.EntityId);
    }

    /// <summary>Unit vector in 768-d: mostly along <paramref name="axis"/>, tilted towards axis 0 by <paramref name="tilt"/> radians.</summary>
    public static float[] Vector(int axis, double tilt = 0) => EmbeddingApiHost.Axis(axis, tilt);

    private async Task<HttpResponseMessage> SendRawAsync(string path, string header, string capability, string body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        request.Headers.Add(header, capability);
        return await Client.SendAsync(request);
    }

    private static async Task<long> NextSequenceAsync(MaviDbContext db)
    {
        var connection = (NpgsqlConnection)db.Database.GetDbConnection();
        if (connection.State != System.Data.ConnectionState.Open) await connection.OpenAsync();
        await using var command = new NpgsqlCommand($"SELECT nextval('{ProcessingVisibilityBarrier.SequenceName}')", connection);
        return (long)(await command.ExecuteScalarAsync())!;
    }

    public async ValueTask DisposeAsync()
    {
        Client.Dispose();
        await Factory.DisposeAsync();
        World.Dispose();
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
        }
    }
}

/// <summary>
/// Entity candidates and operator confirmation through the real API host and PostgreSQL (PoC S7; ADR-023; register
/// rows C6.1 and C6.2): pair-local derivation with the plausibility model, confirmation and audit in one
/// transaction, dismissal suppresses, extension and merge rules, reprocessing carries nothing over, the face factor
/// separate and audited, and the operator requirement.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class EntityCandidateApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 30, 12, 0, 0, TimeSpan.Zero);

    // Two vectors on one axis score the cosine of their tilt difference: 0.2 rad → 0.980, 0.5 → 0.878 (above the 0.85 floor), 0.6 → 0.825 (below it).
    private static EntitySeedTrack Person(double start, double end, double tilt = 0, int axis = 1) =>
        new(ObjectClass.Person, start, end, EntityApiHost.Vector(axis, tilt));

    private static EntitySeedTrack Vehicle(double start, double end, double tilt = 0, int axis = 7) =>
        new(ObjectClass.Vehicle, start, end, EntityApiHost.Vector(axis, tilt));

    private static Guid Id(JsonElement candidate) => candidate.GetProperty("candidateId").GetGuid();

    private static (Guid Lower, Guid Higher) Pair(Guid a, Guid b) => a.CompareTo(b) < 0 ? (a, b) : (b, a);

    private static (Guid, Guid) PairOf(JsonElement candidate) =>
        (candidate.GetProperty("lower").GetProperty("trackId").GetGuid(), candidate.GetProperty("higher").GetProperty("trackId").GetGuid());

    [Fact]
    public async Task ACameraPairIsProposedListedAndConfirmedIntoAnEntityWithItsAuditInTheSameTransaction()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 4)]);
        var b = await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.2), Vehicle(10, 14)]);
        await host.EmbedAllAsync();
        Assert.Equal(2, await host.DeriveAsync());
        Assert.Equal(0, await host.DeriveAsync());

        var list = await host.GetJsonAsync("/api/entity-candidates");
        Assert.Equal(EntityCandidateLabels.Candidates, list.GetProperty("label").GetString());
        Assert.Equal(EntityCandidateCatalogue.Current.CatalogueVersion, list.GetProperty("catalogue").GetProperty("version").GetString());
        Assert.Equal(EntityCandidateCatalogue.Current.Sha256, list.GetProperty("catalogue").GetProperty("sha256").GetString());
        var candidate = Assert.Single(list.GetProperty("candidates").EnumerateArray());
        Assert.Equal(Pair(a.TrackIds[0], b.TrackIds[0]), PairOf(candidate));
        var factors = candidate.GetProperty("factors");
        Assert.Equal(Math.Cos(0.2), factors.GetProperty("appearance").GetProperty("score").GetDouble(), 3);
        Assert.Equal(0.85, factors.GetProperty("appearance").GetProperty("floor").GetDouble());
        Assert.False(factors.GetProperty("plausibility").GetProperty("sameCamera").GetBoolean());
        Assert.Equal(6_000, factors.GetProperty("plausibility").GetProperty("gapMs").GetInt64());
        Assert.False(factors.GetProperty("face").GetProperty("available").GetBoolean());
        Assert.Equal("open", candidate.GetProperty("status").GetString());

        var summary = await host.GetJsonAsync("/api/entity-candidates/summary");
        var pair = Assert.Single(summary.GetProperty("pairs").EnumerateArray());
        Assert.Equal(1, pair.GetProperty("open").GetInt32());
        Assert.Equal(0, summary.GetProperty("pendingDerivations").GetInt32());

        // Nothing merges by itself: candidates exist, no Entity and no EntityId.
        await using (var db = host.World.Read())
        {
            Assert.Equal(0, await db.Entities.CountAsync());
            Assert.Equal(0, await db.Tracks.CountAsync(x => x.EntityId != null));
        }

        var audits = await host.AuditCountAsync();
        using (var confirmed = await host.DecideAsync(Id(candidate), "confirm", "  same jacket and bag  "))
        {
            Assert.Equal(HttpStatusCode.OK, confirmed.StatusCode);
            var json = await confirmed.Content.ReadFromJsonAsync<JsonElement>();
            Assert.True(json.GetProperty("entityCreated").GetBoolean());
            Assert.Equal(EntityCandidateLabels.Entity, json.GetProperty("label").GetString());
            Assert.Equal("confirmed", json.GetProperty("candidate").GetProperty("status").GetString());
            Assert.Equal("development-unattributed", json.GetProperty("candidate").GetProperty("decision").GetProperty("identitySource").GetString());
        }

        Assert.Equal(audits + 1, await host.AuditCountAsync());
        await using (var db = host.World.Read())
        {
            var entity = await db.Entities.SingleAsync();
            Assert.Equal(EntityType.Person, entity.EntityType);
            Assert.Equal(IdentityStatus.Unknown, entity.IdentityStatus);
            Assert.Equal(ReviewStatus.Confirmed, entity.ReviewStatus);
            var ids = await host.EntityIdsAsync(a.TrackIds[0], b.TrackIds[0], b.TrackIds[1]);
            Assert.Equal(entity.Id, ids[a.TrackIds[0]]);
            Assert.Equal(entity.Id, ids[b.TrackIds[0]]);
            Assert.Null(ids[b.TrackIds[1]]);

            var stored = await db.EntityCandidates.SingleAsync();
            var audit = await db.AuditEntries.SingleAsync(x => x.Action == "entities.candidate-confirmed");
            Assert.Equal(audit.Id, stored.DecisionAuditEntryId);
            Assert.Equal(stored.Id.ToString("D"), audit.SubjectId);
            Assert.Equal("entity-candidate", audit.SubjectType);
            Assert.Equal("same jacket and bag", stored.DecisionNote);
            Assert.Equal(host.World.Clock.GetUtcNow(), stored.DecidedAtUtc);
            Assert.Equal(entity.Id, stored.EntityId);
        }

        // The S9 Entity unit now has data: the contract says so, and a count reads the confirmed membership (ADR-023 §9).
        var contract = await host.GetJsonAsync("/api/query/contract");
        var entityUnit = contract.GetProperty("units").EnumerateArray().Single(unit => unit.GetProperty("unit").GetString() == "entity");
        Assert.True(entityUnit.GetProperty("dataAvailable").GetBoolean());
        using (var counted = await host.Client.PostAsync("/api/query", new StringContent(
                   "{\"contractVersion\":\"mavi-query-v1\",\"unit\":\"entity\",\"where\":{\"timeWindow\":{\"fromUtc\":\"2026-10-30T09:00:00Z\"," +
                   "\"toUtc\":\"2026-10-30T11:00:00Z\"}},\"operation\":{\"op\":\"countDistinct\",\"field\":\"camera\"}}", Encoding.UTF8, "application/json")))
        {
            Assert.Equal(HttpStatusCode.OK, counted.StatusCode);
            var envelope = await counted.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal(2, envelope.GetProperty("result").GetProperty("value").GetInt64());
        }

        var view = await host.GetJsonAsync($"/api/entities/{(await host.EntityIdsAsync(a.TrackIds[0]))[a.TrackIds[0]]}");
        Assert.Equal("Unknown", view.GetProperty("identityStatus").GetString());
        Assert.Equal(EntityCandidateLabels.Entity, view.GetProperty("label").GetString());
        Assert.Equal(2, view.GetProperty("members").GetArrayLength());
        Assert.Single(view.GetProperty("confirmations").EnumerateArray());

        // A decision is final: a second one is refused with the current state and writes nothing.
        using (var again = await host.DecideAsync(Id(candidate), "dismiss"))
        {
            Assert.Equal(HttpStatusCode.Conflict, again.StatusCode);
            var problem = await again.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal(EntityConfirmationRules.AlreadyDecided, problem.GetProperty("code").GetString());
            Assert.Equal("confirmed", problem.GetProperty("candidate").GetProperty("status").GetString());
        }

        Assert.Equal(audits + 1, await host.AuditCountAsync());
        Assert.Empty(await host.CandidatesAsync());
        Assert.Single(await host.CandidatesAsync("?status=confirmed"));
    }

    [Fact]
    public async Task ThePlausibilityModelAndTheFloorDecideWhichPairsAreProposed()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        // Camera A: p0 and p1 overlap on one camera; p2 is later on the same camera. Neither same-camera pair is proposed (v2).
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 10), Person(5, 15, tilt: 0.2), Person(100, 110, tilt: 0.3)]);
        // Camera B: p3 overlaps p0 by 1.5 s (inside the 2 s tolerance), p4 overlaps p2 by 5 s (elsewhere at once),
        // p5 is far later but below the floor, and a vehicle that is never paired with a person.
        var b = await host.SeedAsync(cameraB,
            [Person(8.5, 20, tilt: 0.25), Person(105, 120, tilt: 0.1), Person(500, 510, tilt: -0.6), Vehicle(0, 600, axis: 1)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();

        var pairs = (await host.CandidatesAsync("?limit=200")).Select(PairOf).ToHashSet();
        Assert.DoesNotContain(Pair(a.TrackIds[0], a.TrackIds[1]), pairs);   // same camera, concurrent
        Assert.DoesNotContain(Pair(a.TrackIds[0], a.TrackIds[2]), pairs);   // same camera, later: out of v2's scope
        Assert.Contains(Pair(a.TrackIds[0], b.TrackIds[0]), pairs);         // elsewhere, within the tolerance
        Assert.DoesNotContain(Pair(a.TrackIds[2], b.TrackIds[1]), pairs);   // elsewhere at the same time
        Assert.DoesNotContain(pairs, pair => pair.Item1 == b.TrackIds[2] || pair.Item2 == b.TrackIds[2]);   // below the floor
        Assert.DoesNotContain(pairs, pair => pair.Item1 == b.TrackIds[3] || pair.Item2 == b.TrackIds[3]);   // other class

        Assert.Empty(await host.CandidatesAsync($"?cameraId={host.World.CameraId}&otherCameraId={host.World.CameraId}"));
        Assert.All(await host.CandidatesAsync("?limit=200"),
            item => Assert.False(item.GetProperty("factors").GetProperty("plausibility").GetProperty("sameCamera").GetBoolean()));
        var tolerated = (await host.CandidatesAsync()).Single(item => PairOf(item) == Pair(a.TrackIds[0], b.TrackIds[0]));
        Assert.Equal(-1_500, tolerated.GetProperty("factors").GetProperty("plausibility").GetProperty("gapMs").GetInt64());

        // Ordered by appearance score, highest first.
        var scores = (await host.CandidatesAsync("?limit=200")).Select(item => item.GetProperty("factors").GetProperty("appearance").GetProperty("score").GetDouble()).ToList();
        Assert.Equal(scores.OrderByDescending(score => score), scores);
    }

    [Fact]
    public async Task OnlyCamerasThatDeclareTheSameSiteArePaired()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var sameSite = await host.CameraAsync("CAM-ENT-B");
        var otherSite = await host.CameraAsync("CAM-ENT-X", "site-x");
        var noSite = await host.CameraAsync("CAM-ENT-N", null);
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 4)]);
        var b = await host.SeedAsync(sameSite, [Person(10, 14, tilt: 0.05)]);
        var x = await host.SeedAsync(otherSite, [Person(20, 24, tilt: 0.05)]);
        var n = await host.SeedAsync(noSite, [Person(30, 34, tilt: 0.05), Person(40, 44, tilt: 0.05)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();

        // Every vector is within the floor of every other, yet only the same-site cross-camera pair is proposed.
        Assert.Equal(Pair(a.TrackIds[0], b.TrackIds[0]), PairOf(Assert.Single(await host.CandidatesAsync("?limit=200"))));
        var list = await host.GetJsonAsync("/api/entity-candidates");
        Assert.Equal("mavi-entity-candidates-v2", list.GetProperty("catalogue").GetProperty("version").GetString());
        Assert.Contains(list.GetProperty("catalogue").GetProperty("parameters").EnumerateArray(),
            item => item.GetProperty("name").GetString() == "site" && item.GetProperty("source").GetString() == "owner-decision");
        var camera = await host.GetJsonAsync($"/api/cameras/{otherSite}");
        Assert.Equal("site-x", camera.GetProperty("siteCode").GetString());
        _ = x;
        _ = n;
    }

    [Fact]
    public async Task ADismissalIsAttributableSuppressesTheCandidateAndIsNeverReProposed()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        await host.SeedAsync(host.World.CameraId, [Person(0, 4)]);
        var b = await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.2)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();
        var candidate = Assert.Single(await host.CandidatesAsync());

        using (var tooLong = await host.DecideAsync(Id(candidate), "dismiss", new string('x', 501)))
            Assert.Equal(EntityEndpoints.DecisionInvalidCode, await VisualAttributeApiHost.ProblemCodeAsync(tooLong));
        using (var dismissed = await host.DecideAsync(Id(candidate), "dismiss", "different shoes"))
            Assert.Equal(HttpStatusCode.OK, dismissed.StatusCode);
        Assert.Equal(1, await host.AuditCountAsync("entities.candidate-dismissed"));
        Assert.Empty(await host.CandidatesAsync());
        var listed = Assert.Single(await host.CandidatesAsync("?status=dismissed"));
        Assert.Equal("different shoes", listed.GetProperty("decision").GetProperty("note").GetString());

        // A later analysis pairs with the same Tracks again; the dismissed pair is not re-proposed.
        await host.SeedAsync(cameraB, [Person(30, 34, tilt: 0.1)]);
        await host.EmbedAllAsync();
        Assert.Equal(1, await host.DeriveAsync());
        Assert.DoesNotContain(await host.CandidatesAsync("?limit=200"), item => Id(item) == Id(candidate));
        await using var db = host.World.Read();
        Assert.Equal(EntityCandidateStatus.Dismissed, (await db.EntityCandidates.SingleAsync(x => x.Id == Id(candidate))).Status);
        Assert.Equal(0, await db.Entities.CountAsync());
        Assert.Equal(0, await db.Tracks.CountAsync(x => x.EntityId != null));
        Assert.Null((await host.EntityIdsAsync(b.TrackIds[0]))[b.TrackIds[0]]);
    }

    [Fact]
    public async Task ConfirmationExtendsAnEntityOnlyWhenPlausibleAgainstEveryMemberAndRefusesAMerge()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        var cameraC = await host.CameraAsync("CAM-ENT-C");
        // p0 (A, 0–10) ~ p1 (B, 40–50) ~ p2 (C, 3–12): p2 is plausible with p1, but overlaps p0 on another camera by 7 s.
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 10), Person(200, 210, tilt: 0.1, axis: 2)]);
        var b = await host.SeedAsync(cameraB, [Person(40, 50, tilt: 0.1), Person(300, 310, tilt: 0.15, axis: 2)]);
        var c = await host.SeedAsync(cameraC, [Person(3, 12, tilt: 0.05)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();
        var candidates = await host.CandidatesAsync("?limit=200");
        JsonElement Find(Guid x, Guid y) => candidates.Single(item => PairOf(item) == Pair(x, y));

        // p0–p1 creates Entity E1.
        using (var first = await host.DecideAsync(Id(Find(a.TrackIds[0], b.TrackIds[0])), "confirm"))
            Assert.Equal(HttpStatusCode.OK, first.StatusCode);
        // p1–p2 would add p2, which overlaps p0 elsewhere by 7 s: refused, nothing written.
        var audits = await host.AuditCountAsync();
        using (var implausible = await host.DecideAsync(Id(Find(b.TrackIds[0], c.TrackIds[0])), "confirm"))
        {
            Assert.Equal(HttpStatusCode.Conflict, implausible.StatusCode);
            var problem = await implausible.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal(EntityConfirmationRules.ExtensionImplausible, problem.GetProperty("code").GetString());
            Assert.Equal(a.TrackIds[0], problem.GetProperty("conflictingTrackId").GetGuid());
        }

        Assert.Equal(audits, await host.AuditCountAsync());
        Assert.Null((await host.EntityIdsAsync(c.TrackIds[0]))[c.TrackIds[0]]);
        Assert.Equal("open", (await host.GetJsonAsync($"/api/entity-candidates/{Id(Find(b.TrackIds[0], c.TrackIds[0]))}")).GetProperty("status").GetString());

        // A second Entity E2 (axis 2), then a candidate between the two Entities is a merge: refused.
        using (var second = await host.DecideAsync(Id(Find(a.TrackIds[1], b.TrackIds[1])), "confirm"))
            Assert.Equal(HttpStatusCode.OK, second.StatusCode);
        var ids = await host.EntityIdsAsync(a.TrackIds[0], a.TrackIds[1]);
        Assert.NotEqual(ids[a.TrackIds[0]], ids[a.TrackIds[1]]);
        await using (var db = host.World.Read())
        {
            // Forge a cross-Entity candidate (the floor kept axes 1 and 2 apart) to exercise the merge refusal.
            var derivation = await db.EntityCandidateDerivations.FirstAsync();
            db.EntityCandidates.Add(EntityCandidate.Create(derivation.Id, EntityCandidateCatalogue.Current.CatalogueVersion, host.Fingerprint, a.TrackIds[0], b.TrackIds[1],
                ObjectClass.Person, 0.9, false, 290_000, T0));
            await db.SaveChangesAsync();
        }

        var merge = (await host.CandidatesAsync("?limit=200")).Single(item => PairOf(item) == Pair(a.TrackIds[0], b.TrackIds[1]));
        using (var refused = await host.DecideAsync(Id(merge), "confirm"))
            Assert.Equal(EntityConfirmationRules.MergeUnsupported, await VisualAttributeApiHost.ProblemCodeAsync(refused));
        await using (var db = host.World.Read())
            Assert.Equal(2, await db.Entities.CountAsync());
    }

    [Fact]
    public async Task ReprocessingCreatesNewTracksWithNoEntityAndNoCarriedOverDecision()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 4)]);
        var b = await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.2)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();
        using (var confirmed = await host.DecideAsync(Id(Assert.Single(await host.CandidatesAsync())), "confirm"))
            Assert.Equal(HttpStatusCode.OK, confirmed.StatusCode);
        var entityId = (await host.EntityIdsAsync(a.TrackIds[0]))[a.TrackIds[0]]!.Value;

        // Reprocess camera B's video: a new run, new Tracks.
        var again = await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.2)], videoAssetId: b.VideoAssetId);
        await host.EmbedAllAsync();
        await host.DeriveAsync();

        Assert.Null((await host.EntityIdsAsync(again.TrackIds[0]))[again.TrackIds[0]]);
        var fresh = Assert.Single(await host.CandidatesAsync());
        Assert.Equal(Pair(a.TrackIds[0], again.TrackIds[0]), PairOf(fresh));
        Assert.Equal("open", fresh.GetProperty("status").GetString());
        // The confirmed pair left the default views with its old Track, and stays readable through its Entity.
        Assert.Empty(await host.CandidatesAsync("?status=confirmed"));
        var entity = await host.GetJsonAsync($"/api/entities/{entityId}");
        var members = entity.GetProperty("members").EnumerateArray().ToDictionary(item => item.GetProperty("trackId").GetGuid(),
            item => item.GetProperty("visible").GetBoolean());
        Assert.True(members[a.TrackIds[0]]);
        Assert.False(members[b.TrackIds[0]]);

        // The reprocessed copy of B's Track can join the Entity: it is checked against visible members only, not against
        // its own earlier-run copy (same camera, same interval).
        using (var extended = await host.DecideAsync(Id(fresh), "confirm"))
        {
            Assert.Equal(HttpStatusCode.OK, extended.StatusCode);
            Assert.False((await extended.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("entityCreated").GetBoolean());
        }

        Assert.Equal(entityId, (await host.EntityIdsAsync(again.TrackIds[0]))[again.TrackIds[0]]);

        // A candidate whose Track is no longer visible cannot be confirmed.
        await using (var db = host.World.Read())
        {
            var derivation = await db.EntityCandidateDerivations.FirstAsync();
            db.EntityCandidates.Add(EntityCandidate.Create(derivation.Id, EntityCandidateCatalogue.Current.CatalogueVersion, host.Fingerprint, b.TrackIds[0], again.TrackIds[0],
                ObjectClass.Person, 0.9, true, 0, T0));
            await db.SaveChangesAsync();
        }

        await using (var db = host.World.Read())
        {
            var stale = await db.EntityCandidates.SingleAsync(x => x.LowerTrackId == Pair(b.TrackIds[0], again.TrackIds[0]).Lower &&
                                                                   x.HigherTrackId == Pair(b.TrackIds[0], again.TrackIds[0]).Higher);
            using var refused = await host.DecideAsync(stale.Id, "confirm");
            Assert.Equal(EntityConfirmationRules.NotVisible, await VisualAttributeApiHost.ProblemCodeAsync(refused));
        }
    }

    [Fact]
    public async Task TheFaceFactorIsSeparateComputedOnRequestAuditedAndUnknownWithAReason()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        var faceA = FaceApiHost.Axis(3);
        var faceB = FaceApiHost.Axis(3, 0.4);
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 4), Person(50, 54, tilt: 0.1)], faces: [faceA, null]);
        var b = await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.2)], faces: [faceB]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();
        var before = (await host.CandidatesAsync("?limit=200")).Select(item => (PairOf(item),
            item.GetProperty("factors").GetProperty("appearance").GetProperty("score").GetDouble())).ToList();

        await host.FacesAllAsync(host.World.CameraId, cameraB);
        var after = await host.CandidatesAsync("?limit=200");
        // The face takes no part in generating or ordering candidates.
        Assert.Equal(before, after.Select(item => (PairOf(item), item.GetProperty("factors").GetProperty("appearance").GetProperty("score").GetDouble())));
        var withFaces = after.Single(item => PairOf(item) == Pair(a.TrackIds[0], b.TrackIds[0]));
        var withoutFace = after.Single(item => PairOf(item) == Pair(a.TrackIds[1], b.TrackIds[0]));
        Assert.True(withFaces.GetProperty("factors").GetProperty("face").GetProperty("available").GetBoolean());
        Assert.False(withoutFace.GetProperty("factors").GetProperty("face").GetProperty("available").GetBoolean());

        var audits = await host.AuditCountAsync("entities.candidate-face-compared");
        using (var response = await host.Client.PostAsJsonAsync($"/api/entity-candidates/{Id(withFaces)}/face-factor", new { }))
        {
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            var json = await response.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal("observed", json.GetProperty("state").GetString());
            var pair = json.GetProperty("pair");
            Assert.Equal(Math.Cos(0.4), pair.GetProperty("score").GetDouble(), 3);
            Assert.Equal(Math.Cos(0.4) >= json.GetProperty("referenceThreshold").GetProperty("cosine").GetDouble(),
                pair.GetProperty("aboveThreshold").GetBoolean());
            Assert.False(json.GetProperty("referenceThreshold").GetProperty("calibratedOnCctv").GetBoolean());
        }

        using (var response = await host.Client.PostAsJsonAsync($"/api/entity-candidates/{Id(withoutFace)}/face-factor", new { }))
        {
            var json = await response.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal("unknown", json.GetProperty("state").GetString());
            Assert.Equal(JsonValueKind.Null, json.GetProperty("pair").ValueKind);
            var lower = json.GetProperty("lower").GetProperty("trackId").GetGuid() == a.TrackIds[1] ? json.GetProperty("lower") : json.GetProperty("higher");
            Assert.Equal("unknown", lower.GetProperty("state").GetString());
            Assert.Equal("no_face_detected", lower.GetProperty("reason").GetString());
        }

        Assert.Equal(audits + 2, await host.AuditCountAsync("entities.candidate-face-compared"));
        // Ids only in the audit row: no score.
        await using var db = host.World.Read();
        Assert.All(await db.AuditEntries.Where(x => x.Action == "entities.candidate-face-compared").ToListAsync(),
            entry => Assert.Equal("entity-candidate", entry.SubjectType));
        // An unknown candidate is refused and leaves no audit row.
        using var missing = await host.Client.PostAsJsonAsync($"/api/entity-candidates/{Guid.CreateVersion7()}/face-factor", new { });
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
        Assert.Equal(audits + 2, await host.AuditCountAsync("entities.candidate-face-compared"));
    }

    [Fact]
    public async Task EveryEntitySurfaceRequiresTheOperatorAndRefusesFormsAndUnknownKeys()
    {
        await using (var disabled = await EntityApiHost.CreateAsync(fixture, T0, identityMode: "disabled"))
        {
            using var list = await disabled.Client.GetAsync("/api/entity-candidates");
            Assert.Equal(HttpStatusCode.Unauthorized, list.StatusCode);
            using var confirm = await disabled.DecideAsync(Guid.CreateVersion7(), "confirm");
            Assert.Equal(HttpStatusCode.Unauthorized, confirm.StatusCode);
            using var entity = await disabled.Client.GetAsync($"/api/entities/{Guid.CreateVersion7()}");
            Assert.Equal(HttpStatusCode.Unauthorized, entity.StatusCode);
        }

        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        using (var form = await host.Client.PostAsync($"/api/entity-candidates/{Guid.CreateVersion7()}/confirm",
                   new FormUrlEncodedContent([new KeyValuePair<string, string>("note", "x")])))
            Assert.Contains(form.StatusCode, new[] { HttpStatusCode.UnsupportedMediaType, HttpStatusCode.BadRequest });
        using (var unknown = await host.Client.GetAsync("/api/entity-candidates?score=0.5"))
            Assert.Equal(EntityEndpoints.InvalidCode, await VisualAttributeApiHost.ProblemCodeAsync(unknown));
        using (var bad = await host.Client.GetAsync("/api/entity-candidates?limit=0"))
            Assert.Equal(HttpStatusCode.BadRequest, bad.StatusCode);
        using (var missing = await host.DecideAsync(Guid.CreateVersion7(), "confirm"))
            Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
        Assert.Equal(0, await host.AuditCountAsync());
    }

    [Fact]
    public async Task ADecisionWhoseAuditCannotBeWrittenChangesNothing()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 4)]);
        var b = await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.2)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();
        var candidateId = Id(Assert.Single(await host.CandidatesAsync()));

        await using (var scope = host.Factory.Services.CreateAsyncScope())
        {
            var repository = scope.ServiceProvider.GetRequiredService<IEntityCandidateRepository>();
            var decider = new EntityCandidateDecider("op", "Operator", "development-unattributed");
            await Assert.ThrowsAsync<InvalidOperationException>(() => repository.ConfirmAsync(candidateId, null, decider,
                _ => throw new InvalidOperationException("audit unavailable"),
                EntityCandidateCatalogue.Current, host.Fingerprint, T0, CancellationToken.None));
            await Assert.ThrowsAsync<InvalidOperationException>(() => repository.DismissAsync(candidateId, null, decider,
                _ => throw new InvalidOperationException("audit unavailable"),
                EntityCandidateCatalogue.Current, host.Fingerprint, T0, CancellationToken.None));
        }

        await using var db = host.World.Read();
        Assert.Equal(EntityCandidateStatus.Open, (await db.EntityCandidates.SingleAsync()).Status);
        Assert.Equal(0, await db.Entities.CountAsync());
        Assert.Equal(0, await db.Tracks.CountAsync(x => x.EntityId != null));
        Assert.Equal(0, await db.AuditEntries.CountAsync());
        Assert.Null((await host.EntityIdsAsync(b.TrackIds[0]))[b.TrackIds[0]]);
        _ = a;
    }

    [Fact]
    public async Task DerivationGivesTheSameCandidatesInAnyOrder()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        var cameraC = await host.CameraAsync("CAM-ENT-C");
        await host.SeedAsync(host.World.CameraId, [Person(0, 4), Person(60, 64, tilt: 0.3)]);
        await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.1), Person(70, 74, tilt: 0.4)]);
        await host.SeedAsync(cameraC, [Person(20, 24, tilt: 0.2), Vehicle(30, 34)]);
        await host.EmbedAllAsync();
        Assert.Equal(3, await host.DeriveAsync());

        async Task<List<string>> SetAsync()
        {
            await using var db = host.World.Read();
            return (await db.EntityCandidates.AsNoTracking().ToListAsync())
                .Select(x => $"{x.LowerTrackId}|{x.HigherTrackId}|{x.AppearanceScore:R}|{x.GapMs}|{x.SameCamera}")
                .Order(StringComparer.Ordinal).ToList();
        }

        var forward = await SetAsync();
        Assert.NotEmpty(forward);
        List<Guid> analyses;
        await using (var db = host.World.Read())
        {
            analyses = await db.EmbeddingAnalyses.AsNoTracking().OrderByDescending(x => x.VisibilitySequence).Select(x => x.Id).ToListAsync();
            await db.EntityCandidateDerivations.ExecuteDeleteAsync();
        }

        // The same analyses derived in the reverse order give the identical set (pair-local rule, ADR-023 §2).
        await using (var scope = host.Factory.Services.CreateAsyncScope())
        {
            var repository = scope.ServiceProvider.GetRequiredService<IEntityCandidateRepository>();
            foreach (var analysis in analyses)
                await repository.DeriveAsync(analysis, host.Fingerprint, EntityCandidateCatalogue.Current, T0, CancellationToken.None);
        }

        Assert.Equal(forward, await SetAsync());
    }

    [Fact]
    public async Task ACandidateOfAnEarlierCatalogueIsNeverDecided()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 4), Person(30, 34, tilt: 0.1)]);
        await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.2)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();
        Guid legacy;
        await using (var db = host.World.Read())
        {
            // A v1 pair v2 excludes (same camera), left in the database from before the amendment.
            var derivation = await db.EntityCandidateDerivations.FirstAsync();
            var candidate = EntityCandidate.Create(derivation.Id, EntityCandidateCatalogue.V1.CatalogueVersion, host.Fingerprint, a.TrackIds[0],
                a.TrackIds[1], ObjectClass.Person, 0.99, true, 26_000, T0);
            db.EntityCandidates.Add(candidate);
            await db.SaveChangesAsync();
            legacy = candidate.Id;
        }

        foreach (var decision in new[] { "confirm", "dismiss" })
        {
            using var refused = await host.DecideAsync(legacy, decision);
            Assert.Equal(EntityConfirmationRules.Superseded, await VisualAttributeApiHost.ProblemCodeAsync(refused));
        }

        Assert.Equal(0, await host.AuditCountAsync());
        Assert.Null((await host.EntityIdsAsync(a.TrackIds[0]))[a.TrackIds[0]]);
    }

    [Fact]
    public async Task TheStructuredQueryEntityUnitIsForOperatorsOnly()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0, identityMode: "disabled");
        const string Query = "{\"contractVersion\":\"mavi-query-v1\",\"unit\":\"entity\",\"where\":{\"timeWindow\":" +
                             "{\"fromUtc\":\"2026-10-30T09:00:00Z\",\"toUtc\":\"2026-10-30T11:00:00Z\"}},\"operation\":{\"op\":\"find\"}}";
        using (var refused = await host.Client.PostAsync("/api/query", new StringContent(Query, Encoding.UTF8, "application/json")))
            Assert.Equal(HttpStatusCode.Unauthorized, refused.StatusCode);
        // A Track query stays open, as before S7.
        using (var tracks = await host.Client.PostAsync("/api/query",
                   new StringContent(Query.Replace("\"entity\"", "\"track\"", StringComparison.Ordinal), Encoding.UTF8, "application/json")))
            Assert.Equal(HttpStatusCode.OK, tracks.StatusCode);
        // Whether any Entity exists is not disclosed either.
        var contract = await host.GetJsonAsync("/api/query/contract");
        var entity = contract.GetProperty("units").EnumerateArray().Single(unit => unit.GetProperty("unit").GetString() == "entity");
        Assert.False(entity.GetProperty("dataAvailable").GetBoolean());
        Assert.Equal("operator_required", entity.GetProperty("unavailableReason").GetString());
    }

    [Fact]
    public async Task ConcurrentConfirmationsSharingATrackSerialiseIntoOneEntity()
    {
        await using var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-ENT-B");
        var cameraC = await host.CameraAsync("CAM-ENT-C");
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 4)]);
        var b = await host.SeedAsync(cameraB, [Person(10, 14, tilt: 0.1)]);
        var c = await host.SeedAsync(cameraC, [Person(20, 24, tilt: 0.15)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();
        var candidates = await host.CandidatesAsync();
        var ab = candidates.Single(item => PairOf(item) == Pair(a.TrackIds[0], b.TrackIds[0]));
        var bc = candidates.Single(item => PairOf(item) == Pair(b.TrackIds[0], c.TrackIds[0]));

        var results = await Task.WhenAll(host.DecideAsync(Id(ab), "confirm"), host.DecideAsync(Id(bc), "confirm"));
        Assert.All(results, response => Assert.Equal(HttpStatusCode.OK, response.StatusCode));
        foreach (var response in results) response.Dispose();
        var ids = await host.EntityIdsAsync(a.TrackIds[0], b.TrackIds[0], c.TrackIds[0]);
        Assert.Single(ids.Values.Distinct());
        Assert.NotNull(ids[a.TrackIds[0]]);
        await using var db = host.World.Read();
        Assert.Equal(1, await db.Entities.CountAsync());
        Assert.Equal(2, await db.AuditEntries.CountAsync(x => x.Action == "entities.candidate-confirmed"));
    }
}
