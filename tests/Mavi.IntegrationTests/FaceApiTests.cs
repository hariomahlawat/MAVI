using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Mavi.Api.Faces;
using Mavi.Application.Deployment;
using Mavi.Application.Modules.Faces;
using Mavi.Contracts.Worker.Faces;
using Mavi.Domain.Faces;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

namespace Mavi.IntegrationTests;

internal sealed record LeasedFaceUnit(FaceLeaseContract Lease, string Capability, string WorkerId)
{
    public Guid AnalysisId => Lease.AnalysisId;
    public int Attempt => Lease.AttemptCount;
}

/// <summary>
/// The real API host over a <see cref="VisualAttributeWorld"/> with the committed Development face release (YuNet +
/// AdaFace IR-50 manifest and pipeline profile, 512-d), the PoC profile and the labelled Development operator, and a
/// client speaking <c>mavi-face-control-v1</c>.
/// </summary>
internal sealed class FaceApiHost : IAsyncDisposable
{
    public static readonly string ManifestPath = Path.Combine(VisualAttributeReleaseFixture.Root, "models", "manifests",
        "faces-yunet-adaface-ir50-dev-v1.json");
    public static readonly string ProfilePath = Path.Combine(VisualAttributeReleaseFixture.Root, "src", "vision", "config", "faces",
        "development-faces-adaface-v1.json");

    private readonly string _root = Path.Combine(Path.GetTempPath(), "mavi-face-tests", Guid.NewGuid().ToString("N"));

    private FaceApiHost(VisualAttributeWorld world) => World = world;

    public VisualAttributeWorld World { get; }
    public ApiTestFactory Factory { get; private set; } = null!;
    public HttpClient Client { get; private set; } = null!;

    public static async Task<FaceApiHost> CreateAsync(PostgresFixture fixture, DateTimeOffset nowUtc, string identityMode = "development-unattributed",
        bool facesEnabled = true)
    {
        var host = new FaceApiHost(await VisualAttributeWorld.CreateAsync(fixture, nowUtc));
        Directory.CreateDirectory(host._root);
        var metadata = Path.Combine(host._root, "release.json");
        File.WriteAllText(metadata, $$"""
            {
              "schemaVersion": "mavi-poc-release-metadata-v1",
              "profile": "poc-single-host",
              "productionQualified": false,
              "evidenceClass": "Development",
              "identityMode": "windows-negotiate",
              "application": { "revision": "{{new string('b', 40)}}" },
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
                ["Faces:Enabled"] = facesEnabled ? "true" : "false",
                ["Faces:ModelManifestPath"] = ManifestPath,
                ["Faces:PipelineProfilePath"] = ProfilePath,
                ["Identity:Mode"] = identityMode,
                ["Deployment:Profile"] = DeploymentProfiles.PocSingleHost,
                ["Deployment:ReleaseMetadataPath"] = metadata,
            },
        };
        host.Client = host.Factory.CreateClient();
        // Every test recreates the vector extension, so pgvector's type OID changes under the cached data source.
        await using (var scope = host.Factory.Services.CreateAsyncScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<Mavi.Infrastructure.Persistence.MaviDbContext>();
            await db.Database.OpenConnectionAsync();
            await ((NpgsqlConnection)db.Database.GetDbConnection()).ReloadTypesAsync();
        }

        return host;
    }

    public FaceReleaseDefinition Definition => Factory.Services.GetRequiredService<IFaceRelease>().Resolution.Definition!;

    public Task<FaceCycleResult> RunCycleAsync() => Factory.Services.GetRequiredService<FaceHostedService>().RunCycleAsync(CancellationToken.None);

    public Task<HttpResponseMessage> OptInAsync(bool enabled = true) =>
        Client.PutAsJsonAsync($"/api/cameras/{World.CameraId}/face-analysis", new { enabled });

    public async Task<LeasedFaceUnit> LeaseAsync(string workerId = "faces-01")
    {
        using var response = await Client.PostAsJsonAsync($"{FaceContractRules.AnalysisRoutePrefix}/lease", new
        {
            schemaVersion = FaceContractRules.SchemaVersion,
            workerId,
            identityFingerprint = Definition.Identity.Fingerprint,
        });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var raw = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
        Assert.EndsWith("Z", raw.GetProperty("leaseExpiresAtUtc").GetString(), StringComparison.Ordinal);
        var lease = raw.Deserialize<FaceLeaseContract>(JsonSerializerOptions.Web)!;
        return new LeasedFaceUnit(lease, Assert.Single(response.Headers.GetValues(FaceContractRules.CapabilityHeader)), workerId);
    }

    public Task<HttpResponseMessage> EvidenceAsync(LeasedFaceUnit unit, Guid observationId)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, $"{FaceContractRules.AnalysisRoutePrefix}/{unit.AnalysisId}/evidence/{observationId}");
        request.Headers.Add(FaceContractRules.CapabilityHeader, unit.Capability);
        request.Headers.Add(FaceContractRules.WorkerHeader, unit.WorkerId);
        request.Headers.Add(FaceContractRules.AttemptHeader, unit.Attempt.ToString(System.Globalization.CultureInfo.InvariantCulture));
        return Client.SendAsync(request);
    }

    public Task<HttpResponseMessage> CompleteAsync(LeasedFaceUnit unit, string body) =>
        SendRawAsync($"{FaceContractRules.AnalysisRoutePrefix}/{unit.AnalysisId}/complete", unit.Capability, body);

    public async Task<HttpResponseMessage> SendRawAsync(string path, string? capability, string body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        if (capability is not null) request.Headers.Add(FaceContractRules.CapabilityHeader, capability);
        return await Client.SendAsync(request);
    }

    /// <summary>A completion body as the worker writes it: every leased Track in lease order.</summary>
    public static string CompletionBody(LeasedFaceUnit unit, Func<FaceLeaseTrackContract, int, object> track) =>
        JsonSerializer.Serialize(new
        {
            schemaVersion = FaceContractRules.SchemaVersion,
            analysisId = unit.AnalysisId,
            workerId = unit.WorkerId,
            attemptCount = unit.Attempt,
            provenance = new
            {
                roleId = "faces",
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

    public static object Face(Guid? observationId, double side, float[]? vector, double score = 0.95, string? thumbnail = null)
    {
        var landmarks = new[] { new[] { 10.0, 12.0 }, new[] { 20.0, 12.0 }, new[] { 15.0, 17.0 }, new[] { 11.0, 22.0 }, new[] { 19.0, 22.0 } };
        var box = new { x = 4.0, y = 6.0, width = side, height = side + 4 };
        var usable = side >= 32;
        return (observationId, vector, thumbnail) switch
        {
            ({ } id, { } v, _) => new { observationId = id, box, landmarks, score, usable, embedding = FaceContractRules.EncodeVector(v) },
            ({ } id, null, _) => new { observationId = id, box, landmarks, score, usable },
            (null, { } v, { } t) => new { box, landmarks, score, usable, embedding = FaceContractRules.EncodeVector(v), thumbnail = t },
            _ => (object)new { box, landmarks, score, usable },
        };
    }

    public static object Observed(FaceLeaseTrackContract track, float[] vector, double side = 40) => new
    {
        trackId = track.TrackId,
        outcome = "observed",
        faces = new[] { Face(track.Observations[0].ObservationId, side, vector) },
    };

    public static object Unknown(FaceLeaseTrackContract track, string reason, params object[] faces) => new
    {
        trackId = track.TrackId,
        outcome = "unknown",
        reason,
        faces,
    };

    /// <summary>A unit vector in 512-d along <paramref name="axis"/>, tilted towards axis 0 by <paramref name="tilt"/>.</summary>
    public static float[] Axis(int axis, double tilt = 0)
    {
        var vector = new float[512];
        vector[axis] = (float)Math.Cos(tilt);
        vector[0] += (float)Math.Sin(tilt);
        var norm = Math.Sqrt(vector.Sum(value => (double)value * value));
        return vector.Select(value => (float)(value / norm)).ToArray();
    }

    public async Task<JsonElement> TrackFacesAsync(Guid trackId)
    {
        using var response = await Client.GetAsync($"/api/tracks/{trackId}/faces");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    public async Task<JsonElement> PostOkAsync(string path, object body, HttpStatusCode expected = HttpStatusCode.OK)
    {
        using var response = await Client.PostAsJsonAsync(path, body);
        Assert.Equal(expected, response.StatusCode);
        return response.StatusCode == HttpStatusCode.NoContent ? default : await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    public async Task<int> AuditCountAsync()
    {
        await using var db = World.Read();
        return await db.AuditEntries.CountAsync();
    }

    public async Task<string> AuditTextAsync()
    {
        await using var connection = new NpgsqlConnection(World.Fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT coalesce(string_agg(row_to_json(a)::text, '\n'), '') FROM audit_entries a", connection);
        return (string)(await command.ExecuteScalarAsync())!;
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
/// Face intelligence through the real API host and PostgreSQL (PoC S6; register rows C5A.3–C5A.5): opt-in gating,
/// lease, lease-scoped evidence and its IDOR fence, completion validation and replay, failure isolation, Unknown,
/// "Find this face" with score and threshold context and a replayable snapshot, the gallery and its audit trail
/// without biometric or personal content, transient query images erased and purged, opt-out purge, and the operator
/// requirement.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class FaceApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
    private static readonly HttpStatusCode[] Refusals = [HttpStatusCode.Forbidden, HttpStatusCode.UnsupportedMediaType];
    private static readonly double[][] Marks = [[1.0, 1.0], [2.0, 1.0], [1.5, 2.0], [1.0, 3.0], [2.0, 3.0]];

    private static Task<string?> CodeAsync(HttpResponseMessage response) => VisualAttributeApiHost.ProblemCodeAsync(response);

    /// <summary>Opt in, seed 3 Persons and 1 Vehicle, queue, lease; Persons 0 and 1 observed (tilts 0 and 0.3), Person 2 too small.</summary>
    private static async Task<(SeededRun Run, LeasedFaceUnit Unit)> PublishAsync(FaceApiHost host)
    {
        using (var optIn = await host.OptInAsync())
            Assert.Equal(HttpStatusCode.OK, optIn.StatusCode);
        var run = await host.World.SeedRunAsync(3, 1, 2, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        var unit = await host.LeaseAsync();
        var body = FaceApiHost.CompletionBody(unit, (track, index) => index switch
        {
            0 => FaceApiHost.Observed(track, FaceApiHost.Axis(1)),
            1 => FaceApiHost.Observed(track, FaceApiHost.Axis(1, 0.3)),
            _ => FaceApiHost.Unknown(track, "face_too_small", FaceApiHost.Face(track.Observations[0].ObservationId, 20, null)),
        });
        using var completed = await host.CompleteAsync(unit, body);
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        return (run, unit);
    }

    [Fact]
    public async Task AnOptedInRunIsLeasedPublishedAndSearchedAsFaceCandidates()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0);
        var early = await host.World.SeedRunAsync(1, 0, 1, completedAtUtc: T0);
        // Off by default: nothing is queued and the Track says so.
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);
        Assert.Equal("notEnabled", (await host.TrackFacesAsync(early.Track(0).TrackId)).GetProperty("state").GetString());

        var audits = await host.AuditCountAsync();
        using (var optIn = await host.OptInAsync())
            Assert.Equal(HttpStatusCode.OK, optIn.StatusCode);
        Assert.Equal(audits + 1, await host.AuditCountAsync());
        var run = await host.World.SeedRunAsync(3, 1, 2, completedAtUtc: host.World.Clock.GetUtcNow());
        // Opt-in covers the camera's existing runs too.
        Assert.Equal(2, (await host.RunCycleAsync()).Queued);
        Assert.Equal("pending", (await host.TrackFacesAsync(early.Track(0).TrackId)).GetProperty("state").GetString());

        var first = await host.LeaseAsync();
        if (first.Lease.ProcessingRunId != run.RunId)
        {
            using var done = await host.CompleteAsync(first, FaceApiHost.CompletionBody(first, (track, _) => FaceApiHost.Unknown(track, "no_face_detected")));
            Assert.Equal(HttpStatusCode.OK, done.StatusCode);
            first = await host.LeaseAsync();
        }

        var unit = first;
        Assert.Equal(512, unit.Lease.Identity.Model.Dimension);
        // Only the Person Tracks are leased.
        Assert.Equal(run.Tracks.Where(track => track.ObjectClass == Mavi.Domain.Intelligence.ObjectClass.Person).Select(track => track.TrackId),
            unit.Lease.Tracks.Select(track => track.TrackId));
        var crop = run.Track(0).Observations[0];
        using (var evidence = await host.EvidenceAsync(unit, crop.ObservationId))
        {
            Assert.Equal(HttpStatusCode.OK, evidence.StatusCode);
            Assert.Equal(crop.Bytes, await evidence.Content.ReadAsByteArrayAsync());
        }

        // The IDOR fence: the Vehicle's crop and another run's crop are refused.
        using (var vehicle = await host.EvidenceAsync(unit, run.Track(3).Observations[0].ObservationId))
            Assert.Equal("face_evidence_forbidden", await CodeAsync(vehicle));
        using (var foreign = await host.EvidenceAsync(unit, early.Track(0).Observations[0].ObservationId))
            Assert.Equal("face_evidence_forbidden", await CodeAsync(foreign));

        var body = FaceApiHost.CompletionBody(unit, (track, index) => index switch
        {
            0 => FaceApiHost.Observed(track, FaceApiHost.Axis(1)),
            1 => FaceApiHost.Observed(track, FaceApiHost.Axis(1, 0.3)),
            _ => FaceApiHost.Unknown(track, "face_too_small", FaceApiHost.Face(track.Observations[0].ObservationId, 20, null)),
        });
        using (var completed = await host.CompleteAsync(unit, body))
        {
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
            var json = await completed.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal(2, json.GetProperty("tracksObserved").GetInt32());
            Assert.Equal(1, json.GetProperty("tracksUnknown").GetInt32());
        }

        using (var replay = await host.CompleteAsync(unit, body))
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        using (var conflict = await host.CompleteAsync(unit, body.Replace("\"1.0.0\"", "\"1.0.1\"", StringComparison.Ordinal)))
            Assert.Equal("face_completion_conflict", await CodeAsync(conflict));

        var observed = await host.TrackFacesAsync(run.Track(0).TrackId);
        Assert.Equal("observed", observed.GetProperty("state").GetString());
        Assert.Equal(FaceOperatorEndpointsLabel, observed.GetProperty("label").GetString());
        Assert.False(observed.GetProperty("referenceThreshold").GetProperty("calibratedOnCctv").GetBoolean());
        var face = Assert.Single(observed.GetProperty("faces").EnumerateArray());
        Assert.True(face.GetProperty("usable").GetBoolean());
        Assert.StartsWith("/api/artifacts/", face.GetProperty("evidenceCropUrl").GetString(), StringComparison.Ordinal);
        var unknown = await host.TrackFacesAsync(run.Track(2).TrackId);
        Assert.Equal("unknown", unknown.GetProperty("state").GetString());
        Assert.Equal("face_too_small", unknown.GetProperty("reason").GetString());
        Assert.Equal("notPerson", (await host.TrackFacesAsync(run.Track(3).TrackId)).GetProperty("state").GetString());

        // "Find this face": the other observed Track, with its score against the reference threshold; the source
        // face itself is not its own candidate; the search is audited.
        audits = await host.AuditCountAsync();
        var search = await host.PostOkAsync("/api/faces/search", new { source = new { faceId = face.GetProperty("faceId").GetGuid() } });
        Assert.Equal(audits + 1, await host.AuditCountAsync());
        var candidate = Assert.Single(search.GetProperty("candidates").EnumerateArray());
        Assert.Equal(run.Track(1).TrackId, candidate.GetProperty("trackId").GetGuid());
        Assert.Equal(Math.Cos(0.3), candidate.GetProperty("score").GetDouble(), 3);
        Assert.Equal(Math.Cos(0.3) >= host.Definition.ReferenceThreshold.Cosine, candidate.GetProperty("aboveThreshold").GetBoolean());
        Assert.Equal(host.Definition.ReferenceThreshold.Cosine, search.GetProperty("referenceThreshold").GetProperty("cosine").GetDouble());

        // The snapshot replays the same list after a newer publication.
        var snapshot = search.GetProperty("snapshot").GetString()!;
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        await host.World.SeedRunAsync(1, 0, 1, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        var newer = await host.LeaseAsync();
        using (var published = await host.CompleteAsync(newer, FaceApiHost.CompletionBody(newer, (track, _) => FaceApiHost.Observed(track, FaceApiHost.Axis(1, 0.1)))))
            Assert.Equal(HttpStatusCode.OK, published.StatusCode);
        var fresh = await host.PostOkAsync("/api/faces/search", new { source = new { faceId = face.GetProperty("faceId").GetGuid() } });
        Assert.Equal(2, fresh.GetProperty("candidates").GetArrayLength());
        var replayed = await host.PostOkAsync("/api/faces/search", new { source = new { faceId = face.GetProperty("faceId").GetGuid() }, snapshot });
        Assert.Equal(run.Track(1).TrackId, Assert.Single(replayed.GetProperty("candidates").EnumerateArray()).GetProperty("trackId").GetGuid());
        using (var other = await host.Client.PostAsJsonAsync("/api/faces/search",
                   new { source = new { faceId = face.GetProperty("faceId").GetGuid() }, k = 3, snapshot }))
            Assert.Equal(FaceSearchService.InvalidCode, await CodeAsync(other));

        // A face that is too small cannot be a search source.
        var small = Assert.Single(unknown.GetProperty("faces").EnumerateArray()).GetProperty("faceId").GetGuid();
        using (var refused = await host.Client.PostAsJsonAsync("/api/faces/search", new { source = new { faceId = small } }))
            Assert.Equal(FaceSourceCodes.NotUsable, await CodeAsync(refused));

        // Candidates never become identity: no Entity, no EntityId.
        await using var db = host.World.Read();
        Assert.All(await db.Tracks.AsNoTracking().ToListAsync(), track => Assert.Null(track.EntityId));
        Assert.Empty(await db.Entities.AsNoTracking().ToListAsync());
    }

    private const string FaceOperatorEndpointsLabel = Mavi.Api.Endpoints.FaceOperatorEndpoints.Label;

    [Fact]
    public async Task ACompletionThatDoesNotDescribeTheLeaseOrBreaksTheProfileIsRefusedAndPublishesNothing()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0);
        using (var optIn = await host.OptInAsync())
            Assert.Equal(HttpStatusCode.OK, optIn.StatusCode);
        await host.World.SeedRunAsync(2, 0, 2, completedAtUtc: T0);
        await host.RunCycleAsync();
        var unit = await host.LeaseAsync();
        string Body(Func<FaceLeaseTrackContract, int, object> track) => FaceApiHost.CompletionBody(unit, track);
        var cases = new[]
        {
            // observed without a usable face.
            Body((track, _) => new { trackId = track.TrackId, outcome = "observed", faces = new[] { FaceApiHost.Face(track.Observations[0].ObservationId, 20, null) } }),
            // usable flag disagreeing with the 32 px floor (a 40 px face reported unusable).
            Body((track, _) => new { trackId = track.TrackId, outcome = "unknown", reason = "face_too_small", faces = new[] { new
            {
                observationId = track.Observations[0].ObservationId, box = new { x = 0.0, y = 0.0, width = 40.0, height = 44.0 },
                landmarks = Marks,
                score = 0.95, usable = false,
            } } }),
            // a score below the detector threshold.
            Body((track, _) => new { trackId = track.TrackId, outcome = "observed", faces = new[] { FaceApiHost.Face(track.Observations[0].ObservationId, 40, FaceApiHost.Axis(2), 0.5) } }),
            // an Observation that was never leased.
            Body((track, _) => new { trackId = track.TrackId, outcome = "observed", faces = new[] { FaceApiHost.Face(Guid.CreateVersion7(), 40, FaceApiHost.Axis(2)) } }),
            // a vector of the wrong dimension.
            Body((track, _) => new { trackId = track.TrackId, outcome = "observed", faces = new[] { new
            {
                observationId = track.Observations[0].ObservationId, box = new { x = 0.0, y = 0.0, width = 40.0, height = 44.0 },
                landmarks = Marks,
                score = 0.95, usable = true, embedding = FaceContractRules.EncodeVector(new float[] { 1f }),
            } } }),
            // no_evidence for a Track that has crops.
            Body((track, _) => FaceApiHost.Unknown(track, "no_evidence")),
            // reordered Tracks.
            FaceApiHost.CompletionBody(unit with { Lease = unit.Lease with { Tracks = [.. unit.Lease.Tracks.Reverse()] } },
                (track, _) => FaceApiHost.Unknown(track, "no_face_detected")),
        };
        foreach (var body in cases)
        {
            using var refused = await host.CompleteAsync(unit, body);
            Assert.Equal(HttpStatusCode.UnprocessableEntity, refused.StatusCode);
            Assert.Equal("face_completion_invalid", await CodeAsync(refused));
        }

        await using var db = host.World.Read();
        Assert.Equal(FaceAnalysisStatus.Running, (await db.FaceAnalyses.AsNoTracking().SingleAsync()).Status);
        Assert.Empty(await db.FaceObservations.AsNoTracking().ToListAsync());
        Assert.Empty(await db.FaceEmbeddings.AsNoTracking().ToListAsync());
    }

    [Fact]
    public async Task AFaceFailureLeavesTheRunTracksAndObservationsUntouched()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0);
        using (var optIn = await host.OptInAsync())
            Assert.Equal(HttpStatusCode.OK, optIn.StatusCode);
        var run = await host.World.SeedRunAsync(2, 1, 2, completedAtUtc: T0);
        await using (var before = host.World.Read())
        {
            var runBefore = await before.ProcessingRuns.AsNoTracking().SingleAsync(x => x.Id == run.RunId);
            await host.RunCycleAsync();
            var unit = await host.LeaseAsync();
            using var failed = await host.SendRawAsync($"{FaceContractRules.AnalysisRoutePrefix}/{unit.AnalysisId}/fail", unit.Capability,
                JsonSerializer.Serialize(new
                {
                    schemaVersion = FaceContractRules.SchemaVersion, analysisId = unit.AnalysisId, workerId = unit.WorkerId,
                    attemptCount = unit.Attempt, failureCode = "face_output_invalid",
                }));
            Assert.Equal(HttpStatusCode.OK, failed.StatusCode);
            Assert.Equal("failed", (await failed.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("outcome").GetString());

            await using var after = host.World.Read();
            var runAfter = await after.ProcessingRuns.AsNoTracking().SingleAsync(x => x.Id == run.RunId);
            Assert.Equal(ProcessingRunStatus.Completed, runAfter.Status);
            Assert.Equal(runBefore.VisibilitySequence, runAfter.VisibilitySequence);
            Assert.Equal(runBefore.CompletedAtUtc, runAfter.CompletedAtUtc);
            Assert.Equal(3, await after.Tracks.AsNoTracking().CountAsync(x => x.ProcessingRunId == run.RunId));
            Assert.Equal(6, await after.Observations.AsNoTracking().CountAsync(x => run.Tracks.Select(t => t.TrackId).Contains(x.TrackId)));
        }

        var state = await host.TrackFacesAsync(run.Track(0).TrackId);
        Assert.Equal("failed", state.GetProperty("state").GetString());
        Assert.Equal("face_output_invalid", state.GetProperty("reason").GetString());
        // Automatic queueing never retries a failure.
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);
    }

    [Fact]
    public async Task OptingOutDeletesTheCamerasFaceRows()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0);
        var (run, _) = await PublishAsync(host);
        await using (var db = host.World.Read())
        {
            Assert.Equal(3, await db.FaceObservations.CountAsync());
            Assert.Equal(2, await db.FaceEmbeddings.CountAsync());
        }

        using (var optOut = await host.OptInAsync(enabled: false))
        {
            Assert.Equal(HttpStatusCode.OK, optOut.StatusCode);
            Assert.Equal(1, (await optOut.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("faceAnalysesDeleted").GetInt32());
        }

        await using (var db = host.World.Read())
        {
            Assert.Empty(await db.FaceAnalyses.ToListAsync());
            Assert.Equal(0, await db.FaceObservations.CountAsync());
            Assert.Equal(0, await db.FaceEmbeddings.CountAsync());
            Assert.Equal(0, await db.FaceTrackOutcomes.CountAsync());
            Assert.Equal(4, await db.Tracks.CountAsync(x => x.ProcessingRunId == run.RunId));
        }

        Assert.Equal("notEnabled", (await host.TrackFacesAsync(run.Track(0).TrackId)).GetProperty("state").GetString());
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);
        var cameras = await host.Client.GetFromJsonAsync<JsonElement>("/api/cameras");
        Assert.False(cameras.EnumerateArray().Single(c => c.GetProperty("id").GetGuid() == host.World.CameraId).GetProperty("faceAnalysisEnabled").GetBoolean());
        using (var optIn = await host.OptInAsync()) Assert.Equal(HttpStatusCode.OK, optIn.StatusCode);
        cameras = await host.Client.GetFromJsonAsync<JsonElement>("/api/cameras");
        Assert.True(cameras.EnumerateArray().Single(c => c.GetProperty("id").GetGuid() == host.World.CameraId).GetProperty("faceAnalysisEnabled").GetBoolean());
    }

    [Fact]
    public async Task GalleryChangesAreAuditedWithoutTheLabelAndAComparisonStoresNoMatch()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0);
        var (run, _) = await PublishAsync(host);
        var faceId = Assert.Single((await host.TrackFacesAsync(run.Track(0).TrackId)).GetProperty("faces").EnumerateArray()).GetProperty("faceId").GetGuid();
        var otherFace = Assert.Single((await host.TrackFacesAsync(run.Track(1).TrackId)).GetProperty("faces").EnumerateArray()).GetProperty("faceId").GetGuid();
        const string Label = "Visitor-Zeta-71";

        var compareEmpty = await host.PostOkAsync("/api/faces/gallery/compare", new { source = new { faceId } });
        Assert.Empty(compareEmpty.GetProperty("candidates").EnumerateArray());
        Assert.Equal("No gallery candidate above the threshold", compareEmpty.GetProperty("message").GetString());

        var audits = await host.AuditCountAsync();
        var enrolled = await host.PostOkAsync("/api/faces/gallery", new { label = Label, note = "front desk", source = new { faceId } }, HttpStatusCode.Created);
        var personId = enrolled.GetProperty("enrolledPersonId").GetGuid();
        Assert.Equal(audits + 1, await host.AuditCountAsync());
        Assert.Contains($"\"action\":\"faces.gallery-enrolled\",\"subject_type\":\"face-gallery-entry\",\"subject_id\":\"{personId:D}\"", await host.AuditTextAsync(), StringComparison.Ordinal);

        using (var patch = await host.Client.PatchAsJsonAsync($"/api/faces/gallery/{personId}", new { note = (string?)null }))
            Assert.Equal(HttpStatusCode.OK, patch.StatusCode);
        Assert.Equal(audits + 2, await host.AuditCountAsync());
        var added = await host.PostOkAsync($"/api/faces/gallery/{personId}/templates", new { source = new { faceId = otherFace } }, HttpStatusCode.Created);
        Assert.Equal(audits + 3, await host.AuditCountAsync());

        // The comparison returns the entry above the threshold with its score; it is audited and stores nothing.
        var compared = await host.PostOkAsync("/api/faces/gallery/compare", new { source = new { faceId } });
        var match = Assert.Single(compared.GetProperty("candidates").EnumerateArray());
        Assert.Equal(personId, match.GetProperty("enrolledPersonId").GetGuid());
        Assert.Equal(1.0, match.GetProperty("score").GetDouble(), 3);
        Assert.Equal(audits + 4, await host.AuditCountAsync());

        var gallery = await host.Client.GetFromJsonAsync<JsonElement>("/api/faces/gallery");
        var entry = Assert.Single(gallery.GetProperty("entries").EnumerateArray());
        Assert.Equal(2, entry.GetProperty("templates").GetArrayLength());
        Assert.All(entry.GetProperty("templates").EnumerateArray(), template => Assert.Equal("evidence", template.GetProperty("sourceKind").GetString()));

        using (var removeTemplate = await host.Client.PostAsJsonAsync(
                   $"/api/faces/gallery/{personId}/templates/{added.GetProperty("templateId").GetGuid()}/delete", new { }))
            Assert.Equal(HttpStatusCode.NoContent, removeTemplate.StatusCode);
        using (var delete = await host.Client.PostAsJsonAsync($"/api/faces/gallery/{personId}/delete", new { }))
            Assert.Equal(HttpStatusCode.NoContent, delete.StatusCode);
        Assert.Equal(audits + 6, await host.AuditCountAsync());
        using (var gone = await host.Client.PostAsJsonAsync($"/api/faces/gallery/{personId}/delete", new { }))
            Assert.Equal(HttpStatusCode.NotFound, gone.StatusCode);
        // A refused mutation leaves no audit row.
        Assert.Equal(audits + 6, await host.AuditCountAsync());

        // No audit row carries the label; the gallery is gone (hard delete).
        Assert.DoesNotContain(Label, await host.AuditTextAsync(), StringComparison.Ordinal);
        await using var db = host.World.Read();
        Assert.Empty(await db.EnrolledPersons.ToListAsync());
        Assert.Empty(await db.EnrolledPersonFaces.ToListAsync());

        // No table links a Track or a face to an enrolled person: only the gallery's own template table refers to it.
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("""
            SELECT string_agg(conrelid::regclass::text, ',') FROM pg_constraint
            WHERE contype = 'f' AND confrelid = 'enrolled_persons'::regclass
            """, connection);
        Assert.Equal("enrolled_person_faces", await command.ExecuteScalarAsync());
        await using var columns = new NpgsqlCommand("""
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name LIKE '%enrolled_person%' AND table_name <> 'enrolled_person_faces'
            """, connection);
        Assert.Equal(0L, await columns.ExecuteScalarAsync());
    }

    [Fact]
    public async Task AQueryImageIsAnalysedErasedSearchableAndPurgedAfterAnHour()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0);
        var (run, _) = await PublishAsync(host);
        var image = new byte[] { 0xFF, 0xD8, 0xFF, 0xE0, 1, 2, 3, 4 };
        using (var wrong = await host.Client.PostAsJsonAsync("/api/faces/queries", new { imageBase64 = Convert.ToBase64String(image), mimeType = "image/png" }))
            Assert.Equal(Mavi.Api.Endpoints.FaceOperatorEndpoints.QueryInvalidCode, await CodeAsync(wrong));
        var audits = await host.AuditCountAsync();
        var uploaded = await host.PostOkAsync("/api/faces/queries", new { imageBase64 = Convert.ToBase64String(image), mimeType = "image/jpeg" },
            HttpStatusCode.Accepted);
        var queryId = uploaded.GetProperty("queryId").GetGuid();
        Assert.Equal(audits + 1, await host.AuditCountAsync());
        Assert.Contains($"\"action\":\"faces.query-uploaded\",\"subject_type\":\"face-query\",\"subject_id\":\"{queryId:D}\"", await host.AuditTextAsync(), StringComparison.Ordinal);

        // The worker leases the query, reads the image lease-scoped, and completes it.
        using var lease = await host.Client.PostAsJsonAsync($"{FaceContractRules.QueryWorkerRoutePrefix}/lease", new
        {
            schemaVersion = FaceContractRules.SchemaVersion, workerId = "faces-01", identityFingerprint = host.Definition.Identity.Fingerprint,
        });
        Assert.Equal(HttpStatusCode.OK, lease.StatusCode);
        var capability = Assert.Single(lease.Headers.GetValues(FaceContractRules.CapabilityHeader));
        var leased = await lease.Content.ReadFromJsonAsync<FaceQueryLeaseContract>(JsonSerializerOptions.Web);
        Assert.Equal(image.Length, leased!.Image.SizeBytes);
        var read = new HttpRequestMessage(HttpMethod.Get, $"{FaceContractRules.QueryWorkerRoutePrefix}/{queryId}/image");
        read.Headers.Add(FaceContractRules.CapabilityHeader, capability);
        read.Headers.Add(FaceContractRules.WorkerHeader, "faces-01");
        read.Headers.Add(FaceContractRules.AttemptHeader, "1");
        using (var bytes = await host.Client.SendAsync(read))
            Assert.Equal(image, await bytes.Content.ReadAsByteArrayAsync());

        var thumbnail = Convert.ToBase64String(new byte[] { 0xFF, 0xD8, 0xFF, 0xDB, 9, 9 });
        using (var completed = await host.SendRawAsync($"{FaceContractRules.QueryWorkerRoutePrefix}/{queryId}/complete", capability,
                   JsonSerializer.Serialize(new
                   {
                       schemaVersion = FaceContractRules.SchemaVersion, queryId, workerId = "faces-01", attemptCount = 1,
                       faces = new[] { FaceApiHost.Face(null, 60, FaceApiHost.Axis(1, 0.2), thumbnail: thumbnail), FaceApiHost.Face(null, 20, null) },
                   })))
        {
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
            var json = await completed.Content.ReadFromJsonAsync<JsonElement>();
            Assert.Equal("completed", json.GetProperty("status").GetString());
        }

        await using (var db = host.World.Read())
            Assert.Null((await db.FaceQueries.AsNoTracking().SingleAsync(x => x.Id == queryId)).Image);
        var query = await host.Client.GetFromJsonAsync<JsonElement>($"/api/faces/queries/{queryId}");
        Assert.Equal("completed", query.GetProperty("status").GetString());
        var faces = query.GetProperty("faces").EnumerateArray().ToList();
        Assert.StartsWith("data:image/jpeg;base64,", faces[0].GetProperty("thumbnailDataUrl").GetString(), StringComparison.Ordinal);
        Assert.Equal(JsonValueKind.Null, faces[1].GetProperty("thumbnailDataUrl").ValueKind);

        var search = await host.PostOkAsync("/api/faces/search", new { source = new { queryId, faceIndex = 0 } });
        // The query face (tilt 0.2) is nearer to Track 1 (tilt 0.3) than to Track 0 (tilt 0).
        Assert.Equal([run.Track(1).TrackId, run.Track(0).TrackId],
            search.GetProperty("candidates").EnumerateArray().Select(item => item.GetProperty("trackId").GetGuid()));
        using (var unusable = await host.Client.PostAsJsonAsync("/api/faces/search", new { source = new { queryId, faceIndex = 1 } }))
            Assert.Equal(FaceSourceCodes.NotUsable, await CodeAsync(unusable));

        // Enrolled from the upload: the template keeps the worker's thumbnail.
        await host.PostOkAsync("/api/faces/gallery", new { label = "Upload", source = new { queryId, faceIndex = 0 } }, HttpStatusCode.Created);
        var gallery = await host.Client.GetFromJsonAsync<JsonElement>("/api/faces/gallery");
        var template = Assert.Single(Assert.Single(gallery.GetProperty("entries").EnumerateArray()).GetProperty("templates").EnumerateArray());
        Assert.Equal("query", template.GetProperty("sourceKind").GetString());
        Assert.NotEqual(JsonValueKind.Null, template.GetProperty("thumbnailDataUrl").ValueKind);

        // An hour later the query, its faces and vectors are purged; the gallery template stays. Before the sweep
        // deletes them, the expired query is already gone for reads and as a search source.
        host.World.Clock.Advance(TimeSpan.FromMinutes(61));
        using (var expired = await host.Client.GetAsync($"/api/faces/queries/{queryId}"))
            Assert.Equal(HttpStatusCode.NotFound, expired.StatusCode);
        using (var expiredSearch = await host.Client.PostAsJsonAsync("/api/faces/search", new { source = new { queryId, faceIndex = 0 } }))
            Assert.Equal(FaceSourceCodes.NotFound, await CodeAsync(expiredSearch));
        Assert.Equal(1, (await host.RunCycleAsync()).QueriesPurged);
        using (var gone = await host.Client.GetAsync($"/api/faces/queries/{queryId}"))
            Assert.Equal(HttpStatusCode.NotFound, gone.StatusCode);
        await using (var db = host.World.Read())
        {
            Assert.Empty(await db.FaceQueryEmbeddings.ToListAsync());
            Assert.Single(await db.EnrolledPersonFaces.ToListAsync());
        }
    }

    [Fact]
    public async Task AUnitQueuedBeforeAnOptOutCommittedIsNeverLeased()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0);
        using (var optIn = await host.OptInAsync())
            Assert.Equal(HttpStatusCode.OK, optIn.StatusCode);
        await host.World.SeedRunAsync(3, 1, 2, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        // The race: the queueing read saw the camera on, the opt-out committed (deleting nothing yet queued), then the
        // unit was inserted. Modelled by turning the flag off underneath the queued unit.
        await using (var connection = new NpgsqlConnection(fixture.ConnectionString))
        {
            await connection.OpenAsync();
            await using var command = new NpgsqlCommand("UPDATE cameras SET face_analysis_enabled = false WHERE id = @id", connection);
            command.Parameters.AddWithValue("id", host.World.CameraId);
            Assert.Equal(1, await command.ExecuteNonQueryAsync());
        }

        using var lease = await host.Client.PostAsJsonAsync($"{FaceContractRules.AnalysisRoutePrefix}/lease", new
        {
            schemaVersion = FaceContractRules.SchemaVersion,
            workerId = "faces-01",
            identityFingerprint = host.Definition.Identity.Fingerprint,
        });
        Assert.Equal(HttpStatusCode.NoContent, lease.StatusCode);
        await using var db = host.World.Read();
        Assert.Equal(0, await db.FaceObservations.CountAsync());
    }

    [Fact]
    public async Task WithQueueingDisabledTheRetentionSweepStillRunsAndAnExpiredImageIsNotLeased()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0, facesEnabled: false);
        using (var optIn = await host.OptInAsync())
            Assert.Equal(HttpStatusCode.OK, optIn.StatusCode);
        await host.World.SeedRunAsync(3, 1, 2, completedAtUtc: host.World.Clock.GetUtcNow());
        var uploaded = await host.PostOkAsync("/api/faces/queries",
            new { imageBase64 = Convert.ToBase64String(new byte[] { 0xFF, 0xD8, 0xFF, 1 }), mimeType = "image/jpeg" }, HttpStatusCode.Accepted);
        var queryId = uploaded.GetProperty("queryId").GetGuid();
        host.World.Clock.Advance(TimeSpan.FromMinutes(15));
        using (var lease = await host.Client.PostAsJsonAsync($"{FaceContractRules.QueryWorkerRoutePrefix}/lease", new
               {
                   schemaVersion = FaceContractRules.SchemaVersion,
                   workerId = "faces-01",
                   identityFingerprint = host.Definition.Identity.Fingerprint,
               }))
            Assert.Equal(HttpStatusCode.NoContent, lease.StatusCode);
        var cycle = await host.RunCycleAsync();
        Assert.Equal(0, cycle.Queued);
        Assert.Equal(1, cycle.QueryImagesErased);
        host.World.Clock.Advance(TimeSpan.FromMinutes(46));
        Assert.Equal(1, (await host.RunCycleAsync()).QueriesPurged);
        await using var db = host.World.Read();
        Assert.False(await db.FaceQueries.AnyAsync(x => x.Id == queryId));
        Assert.Empty(await db.FaceAnalyses.ToListAsync());
    }

    [Fact]
    public async Task AnUnanalysedQueryImageIsErasedAfterFifteenMinutes()
    {
        await using var host = await FaceApiHost.CreateAsync(fixture, T0);
        var uploaded = await host.PostOkAsync("/api/faces/queries",
            new { imageBase64 = Convert.ToBase64String(new byte[] { 0x89, 0x50, 0x4E, 0x47, 1 }), mimeType = "image/png" }, HttpStatusCode.Accepted);
        var queryId = uploaded.GetProperty("queryId").GetGuid();
        host.World.Clock.Advance(TimeSpan.FromMinutes(15));
        Assert.Equal(1, (await host.RunCycleAsync()).QueryImagesErased);
        await using var db = host.World.Read();
        var query = await db.FaceQueries.AsNoTracking().SingleAsync(x => x.Id == queryId);
        Assert.Null(query.Image);
        Assert.Equal(FaceQueryStatus.Failed, query.Status);
        Assert.Equal(FaceQuery.ImageExpiredCode, query.FailureCode);
    }

    [Fact]
    public async Task FaceRoutesRequireAnOperatorAndJson()
    {
        await using (var host = await FaceApiHost.CreateAsync(fixture, T0))
        {
            var run = await host.World.SeedRunAsync(1, 0, 1, completedAtUtc: T0);
            // A form-shaped or multipart mutation is refused even for an operator (ADR-010 §3, §8): 403 by the policy or
            // 415 by JSON binding, and nothing changes.
            using var form = await host.Client.PutAsync($"/api/cameras/{host.World.CameraId}/face-analysis",
                new FormUrlEncodedContent(new Dictionary<string, string> { ["enabled"] = "true" }));
            Assert.Contains(form.StatusCode, Refusals);
            using var multipart = await host.Client.PostAsync("/api/faces/queries", new MultipartFormDataContent { { new ByteArrayContent([0xFF, 0xD8]), "image", "a.jpg" } });
            Assert.Contains(multipart.StatusCode, Refusals);
            Assert.Equal(0, await host.AuditCountAsync());
            await using var db = host.World.Read();
            Assert.False((await db.Cameras.SingleAsync()).FaceAnalysisEnabled);
            _ = run;
        }

        // With identity disabled, every face surface is refused.
        await using var disabled = await FaceApiHost.CreateAsync(fixture, T0, identityMode: "disabled");
        var seeded = await disabled.World.SeedRunAsync(1, 0, 1, completedAtUtc: T0);
        using (var read = await disabled.Client.GetAsync($"/api/tracks/{seeded.Track(0).TrackId}/faces"))
            Assert.Equal(HttpStatusCode.Unauthorized, read.StatusCode);
        using (var gallery = await disabled.Client.GetAsync("/api/faces/gallery"))
            Assert.Equal(HttpStatusCode.Unauthorized, gallery.StatusCode);
        using (var optIn = await disabled.OptInAsync())
            Assert.Equal(HttpStatusCode.Unauthorized, optIn.StatusCode);
        using (var search = await disabled.Client.PostAsJsonAsync("/api/faces/search", new { source = new { faceId = Guid.NewGuid() } }))
            Assert.Equal(HttpStatusCode.Unauthorized, search.StatusCode);
    }

    [Fact]
    public async Task TheMigrationIsAdditiveAndRoundTrips()
    {
        const string Preceding = "20261029114149_AddTrackEmbeddings";
        const string Migration = "20261029174307_AddFaceIntelligence";
        string[] tables =
        [
            "face_analyses", "face_track_outcomes", "face_observations", "face_embeddings", "face_queries", "face_query_embeddings",
            "enrolled_persons", "enrolled_person_faces",
        ];
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync(Preceding);
        var before = await ColumnsAsync();
        await migrator.MigrateAsync(Migration);
        var after = await ColumnsAsync();
        Assert.All(tables, table => Assert.Contains(after, item => item.StartsWith(table + ".", StringComparison.Ordinal)));
        // The only change to an existing table is the camera opt-in switch, off by default.
        Assert.Equal(before.Append("cameras.face_analysis_enabled:boolean:NO:false").Order(StringComparer.Ordinal).ToList(),
            after.Where(item => !tables.Contains(item.Split('.')[0])).Order(StringComparer.Ordinal).ToList());

        await migrator.MigrateAsync(Preceding);
        Assert.Equal(before, await ColumnsAsync());
        await migrator.MigrateAsync(Migration);
        Assert.Equal(after, await ColumnsAsync());
    }

    private async Task<List<string>> ColumnsAsync()
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("""
            SELECT table_name || '.' || column_name || ':' || data_type || ':' || is_nullable || ':' || coalesce(column_default, '')
            FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, column_name
            """, connection);
        await using var reader = await command.ExecuteReaderAsync();
        var columns = new List<string>();
        while (await reader.ReadAsync()) columns.Add(reader.GetString(0));
        return columns;
    }
}
