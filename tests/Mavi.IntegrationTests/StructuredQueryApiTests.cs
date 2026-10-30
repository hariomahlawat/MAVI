using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Mavi.Application.Modules.Events;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Application.Modules.Query;
using Mavi.Contracts.Api.Query;
using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The structured query contract end to end (ADR-024; register C8.1): the frozen golden corpus is posted to
/// <c>POST /api/query</c> against the scene-analytics fixture, and every normalised envelope or refusal must equal the
/// corpus. Setting <c>MAVI_QUERY_GOLDEN_BLESS</c> to a file path writes the actual envelopes there instead of failing,
/// for review; the corpus is only ever changed by hand from such a file.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed partial class StructuredQueryApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    /// <summary>
    /// The fixtures the corpus names. <c>derived</c>: one camera, one Person Track, scene facts committed and events
    /// derived. <c>underived</c>: the same, events not derived. <c>pending</c>: the same camera and Track, scene facts
    /// not committed. <c>two-camera</c>: <c>derived</c> plus a second camera with no scene, recorded three
    /// and a half hours earlier, holding two Vehicle Tracks that start at the same instant. <c>entities</c>: <c>two-camera</c>
    /// plus a Person Track on the second camera and one operator-confirmed Person Entity (ADR-023) holding it and the
    /// first camera's Person Track.
    /// </summary>
    [Theory]
    [InlineData("derived")]
    [InlineData("underived")]
    [InlineData("pending")]
    [InlineData("two-camera")]
    [InlineData("entities")]
    public async Task TheGoldenCorpusAnswersExactlyAsFrozen(string setup)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        if (setup != "pending")
            await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        if (setup is "derived" or "two-camera" or "entities")
        {
            await using var scope = factory.Services.CreateAsyncScope();
            Assert.Equal(1, await scope.ServiceProvider.GetRequiredService<AnalyticEventService>().DeriveDueAsync(50, default));
        }

        var second = setup is "two-camera" or "entities" ? await AddSecondCameraAsync(world) : null;

        using var corpus = JsonDocument.Parse(File.ReadAllText(CorpusPath()));
        var placeholders = corpus.RootElement.GetProperty("placeholders");
        Guid? secondPerson = null;
        if (setup == "entities")
            secondPerson = await ConfirmEntityAsync(world, second!, Guid.Parse(placeholders.GetProperty("entity").GetString()!));
        var toWorld = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            [placeholders.GetProperty("camera").GetString()!] = world.CameraId.ToString("D"),
            [placeholders.GetProperty("zone").GetString()!] = world.ZoneId.ToString("D"),
            [placeholders.GetProperty("line").GetString()!] = world.LineId.ToString("D"),
            [placeholders.GetProperty("track").GetString()!] = world.TrackId.ToString("D"),
        };
        var fromWorld = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            [world.CameraId.ToString("D")] = placeholders.GetProperty("camera").GetString()!,
            [world.ZoneId.ToString("D")] = placeholders.GetProperty("zone").GetString()!,
            [world.LineId.ToString("D")] = placeholders.GetProperty("line").GetString()!,
            [world.TrackId.ToString("D")] = placeholders.GetProperty("track").GetString()!,
            [world.RevisionId.ToString("D")] = placeholders.GetProperty("revision").GetString()!,
            [world.VideoId.ToString("D")] = placeholders.GetProperty("video").GetString()!,
            [world.RunId.ToString("D")] = placeholders.GetProperty("run").GetString()!,
            [placeholders.GetProperty("unknown").GetString()!] = placeholders.GetProperty("unknown").GetString()!,
        };
        if (second is not null)
        {
            toWorld[placeholders.GetProperty("camera2").GetString()!] = second.CameraId.ToString("D");
            fromWorld[second.CameraId.ToString("D")] = placeholders.GetProperty("camera2").GetString()!;
            fromWorld[second.VideoId.ToString("D")] = placeholders.GetProperty("video2").GetString()!;
            fromWorld[second.RunId.ToString("D")] = placeholders.GetProperty("run2").GetString()!;
            fromWorld[second.LowTrackId.ToString("D")] = placeholders.GetProperty("track2Low").GetString()!;
            fromWorld[second.HighTrackId.ToString("D")] = placeholders.GetProperty("track2High").GetString()!;
        }

        if (secondPerson is { } person)
        {
            toWorld[placeholders.GetProperty("track2Person").GetString()!] = person.ToString("D");
            fromWorld[person.ToString("D")] = placeholders.GetProperty("track2Person").GetString()!;
            fromWorld[placeholders.GetProperty("entity").GetString()!] = placeholders.GetProperty("entity").GetString()!;
        }

        var blessPath = Environment.GetEnvironmentVariable("MAVI_QUERY_GOLDEN_BLESS");
        var blessed = new JsonObject();
        var failures = new List<string>();
        var ran = 0;
        foreach (var item in corpus.RootElement.GetProperty("cases").EnumerateArray())
        {
            var caseSetup = item.GetProperty("setup").GetString();
            // Cases without a setup read no fixture data; they run against the derived world.
            if (caseSetup != setup && !(caseSetup == "none" && setup == "derived"))
                continue;
            ran++;

            var name = item.GetProperty("name").GetString()!;
            var body = Substitute(item.GetProperty("query").GetRawText(), toWorld);
            using var response = await client.PostAsync("/api/query", new StringContent(body, Encoding.UTF8, "application/json"));
            var text = await response.Content.ReadAsStringAsync();
            var expect = item.GetProperty("expect");
            var status = expect.GetProperty("status").GetInt32();

            JsonNode actual;
            if (response.StatusCode == HttpStatusCode.OK)
            {
                actual = Normalise(JsonNode.Parse(text)!, fromWorld);
            }
            else
            {
                var problem = JsonNode.Parse(text)!;
                Assert.Equal("query_refused", problem["code"]!.GetValue<string>());
                actual = new JsonObject
                {
                    ["code"] = problem["refusal"]!["code"]!.GetValue<string>(),
                    ["path"] = problem["refusal"]!["path"]!.GetValue<string>(),
                };
            }

            blessed[name] = new JsonObject { ["status"] = (int)response.StatusCode, ["actual"] = actual.DeepClone() };
            if ((int)response.StatusCode != status)
            {
                failures.Add($"{name}: status {(int)response.StatusCode}, expected {status}: {text}");
                continue;
            }

            var expected = expect.TryGetProperty(status == 200 ? "envelope" : "refusal", out var frozen)
                ? JsonNode.Parse(frozen.GetRawText())
                : null;
            if (!JsonNode.DeepEquals(expected, actual))
                failures.Add($"{name}: envelope differs:\n{actual.ToJsonString()}");
        }

        if (blessPath is not null)
        {
            File.WriteAllText(blessPath.Replace("{setup}", setup, StringComparison.Ordinal),
                blessed.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            return;
        }

        Assert.True(ran > 0);
        Assert.True(failures.Count == 0, string.Join("\n\n", failures));
    }

    [Fact]
    public async Task AScopeOverTheBoundIsRefusedByTheRealRepositoryNeverTruncated()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await AddSecondCameraAsync(world);
        await using var db = world.Read();
        var where = StructuredQueryParser.Parse(
            "{\"contractVersion\":\"mavi-query-v1\",\"unit\":\"track\"," +
            "\"where\":{\"timeWindow\":{\"fromUtc\":\"2026-09-21T02:00:00Z\",\"toUtc\":\"2026-09-21T07:00:00Z\"}}," +
            "\"operation\":{\"op\":\"count\"}}").Query!.Where;
        QueryReadWindow[] windows = [new("query", where.Window)];
        var identities = new QueryCapabilityIdentities(null, null, null);

        // Three Tracks match and the bound is two: refused at the window, never answered from two of them.
        var refused = await new StructuredQueryRepository(db, world.Clock) { MaximumMatchedRecords = 2 }
            .ReadTracksAsync(where, windows, identities, default);
        Assert.Equal((QueryRefusalCodes.QueryScopeTooLarge, "/where"), (refused.Refusal!.Code, refused.Refusal.Path));
        Assert.Empty(refused.Windows);

        var exact = await new StructuredQueryRepository(db, world.Clock) { MaximumMatchedRecords = 3 }
            .ReadTracksAsync(where, windows, identities, default);
        Assert.Equal(3, Assert.Single(exact.Windows).Records.Count);

        // The Event read holds the same bound across cameras: two events, a bound of one.
        await using (var scope = CreateFactory(world).Services.CreateAsyncScope())
            Assert.Equal(1, await scope.ServiceProvider.GetRequiredService<AnalyticEventService>().DeriveDueAsync(50, default));
        var events = StructuredQueryParser.Parse(
            "{\"contractVersion\":\"mavi-query-v1\",\"unit\":\"event\"," +
            "\"where\":{\"timeWindow\":{\"fromUtc\":\"2026-09-21T05:00:00Z\",\"toUtc\":\"2026-09-21T07:00:00Z\"}}," +
            "\"operation\":{\"op\":\"count\"}}").Query!.Where;
        QueryReadWindow[] eventWindows = [new("query", events.Window)];
        var refusedEvents = await new StructuredQueryRepository(db, world.Clock) { MaximumMatchedRecords = 1 }
            .ReadEventsAsync(events, eventWindows, default);
        Assert.Equal(QueryRefusalCodes.QueryScopeTooLarge, refusedEvents.Refusal!.Code);
        var exactEvents = await new StructuredQueryRepository(db, world.Clock) { MaximumMatchedRecords = 2 }
            .ReadEventsAsync(events, eventWindows, default);
        Assert.Equal(2, Assert.Single(exactEvents.Windows).Records.Count);
    }

    [Fact]
    public async Task TheContractRouteListsTheVocabularyTheBuilderComposesFrom()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var contract = await client.GetFromJsonAsync<QueryContractResponse>("/api/query/contract", new JsonSerializerOptions(JsonSerializerDefaults.Web));

        Assert.Equal("mavi-query-v1", contract!.ContractVersion);
        Assert.Equal(["track", "event", "entity"], contract.Units.Select(unit => unit.Unit));
        var entity = contract.Units.Single(unit => unit.Unit == "entity");
        Assert.Equal((false, "entity_data_unavailable"), (entity.DataAvailable, entity.UnavailableReason));
        Assert.Equal(EventRuleIds.All, contract.EventRuleIds);
        Assert.Contains("query_scope_too_large", contract.RefusalCodes);
    }

    [Fact]
    public async Task ABodyThatIsNotAJsonQueryIsRefusedBeforeAnythingRuns()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var text = await client.PostAsync("/api/query", new StringContent("count people", Encoding.UTF8, "text/plain"));
        using var big = await client.PostAsync("/api/query", new StringContent(new string(' ', 70_000) + "{}", Encoding.UTF8, "application/json"));
        using var parameters = await client.PostAsync("/api/query?unit=track", new StringContent("{}", Encoding.UTF8, "application/json"));
        using var lookalike = await client.PostAsync("/api/query", new StringContent("{}", Encoding.UTF8, "application/jsonx"));

        foreach (var response in new[] { text, big, parameters, lookalike })
        {
            Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
            var problem = JsonNode.Parse(await response.Content.ReadAsStringAsync())!;
            Assert.Equal("query_refused", problem["code"]!.GetValue<string>());
        }
    }

    /// <summary>
    /// The envelope with fixture ids as their placeholders and every other id as <c>&lt;id&gt;</c>; the snapshot and
    /// the fingerprint (which hashes real ids) are left out.
    /// </summary>
    private static JsonNode Normalise(JsonNode envelope, Dictionary<string, string> fromWorld)
    {
        var copy = envelope.AsObject();
        copy.Remove("snapshot");
        copy.Remove("queryFingerprint");
        var text = GuidPattern().Replace(copy.ToJsonString(), match =>
            fromWorld.TryGetValue(match.Value, out var placeholder) ? placeholder : "<id>");
        return JsonNode.Parse(text)!;
    }

    private static string Substitute(string text, Dictionary<string, string> map)
    {
        foreach (var (from, to) in map)
            // Case-sensitive: a corpus case may spell a placeholder in upper case to be refused, and must reach the API so.
            text = text.Replace(from, to, StringComparison.Ordinal);
        return text;
    }

    [GeneratedRegex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")]
    private static partial Regex GuidPattern();

    private static string CorpusPath()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
            directory = directory.Parent;
        return Path.Combine(directory!.FullName, "contracts", "test-vectors", "structured-query-v1-golden.json");
    }

    private static async Task CommitFactsAsync(SceneAnalyticsWorld world)
    {
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion, SceneAnalyticsWorld.ParametersSha256, null, Now.AddDays(-1), 50, default);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var result = await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);
        Assert.True(result.IsSuccess);
    }

    private sealed record SecondCamera(Guid CameraId, Guid VideoId, Guid RunId, Guid LowTrackId, Guid HighTrackId);

    /// <summary>
    /// A second camera with no scene configuration, recorded from 02:30 (three and a half hours before the first
    /// camera's clock), whose one completed, visible run holds two Vehicle Tracks starting at the same instant: the
    /// tie-break and the not-configured coverage path, against real data.
    /// </summary>
    private static async Task<SecondCamera> AddSecondCameraAsync(SceneAnalyticsWorld world)
    {
        await using var db = world.Read();
        var recordingStart = Now.AddHours(-3).AddMinutes(-30);
        var camera = Camera.Create("CAM-LC-02", "Second Test Camera", "UTC");
        var source = Artifact.Create(
            ArtifactType.SourceVideo, $"source/CAM-LC-02/{Guid.CreateVersion7()}.mp4", "video/mp4", 1, new string('b', 64));
        var video = VideoAsset.Create(
            camera.Id, source.Id, "second.mp4", recordingStart, 600_000, 25, 1, 640, 360, "h264", TimestampSource.Manual, 1.0);
        var completedAtUtc = Now.AddMinutes(-5);
        var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", Now.AddMinutes(-9));
        run.MarkRunning("worker-02", Now.AddMinutes(-8));
        run.MarkCompleted(250, 2, 5_000, completedAtUtc);
        // Published as a completion is: its sequence comes from the database sequence, so later snapshots include it.
        var sequence = await db.Database
            .SqlQueryRaw<long>("SELECT nextval('processing_visibility_sequence') AS \"Value\"")
            .SingleAsync();
        run.AssignCompletionVisibilitySequence(sequence);
        var first = Track.Create(run.Id, video.Id, 1, ObjectClass.Vehicle, 60_000, 70_000, recordingStart,
            detectionCount: 8, meanConfidence: 0.7, maxConfidence: 0.9, createdAtUtc: completedAtUtc);
        // Identical in every field an envelope reports, so only the tie-break tells them apart.
        var second = Track.Create(run.Id, video.Id, 2, ObjectClass.Vehicle, 60_000, 70_000, recordingStart,
            detectionCount: 8, meanConfidence: 0.7, maxConfidence: 0.9, createdAtUtc: completedAtUtc);
        var job = VisionJob.Create(run.Id, "phase1-detection-tracking", Now.AddMinutes(-9));
        db.AddRange(camera, source, video, run, job, first, second);
        await db.SaveChangesAsync();

        // Guid order is the "D" form's lexical order, the evaluator's tie-break; the corpus names the two by it.
        var ordered = new[] { first.Id, second.Id }.Order().ToArray();
        return new SecondCamera(camera.Id, video.Id, run.Id, ordered[0], ordered[1]);
    }

    /// <summary>
    /// A Person Track on the second camera (02:35:00–02:35:20 UTC, three hours before the first camera's) and one
    /// operator-confirmed Person Entity holding it and the first camera's Person Track. The Entity is written as a
    /// confirmation leaves it (ADR-023 §6), with the corpus's fixed id so its envelopes are stable; this fixture is the
    /// only place outside the confirmation that sets <c>entity_id</c>, and it is test data.
    /// </summary>
    private static async Task<Guid> ConfirmEntityAsync(SceneAnalyticsWorld world, SecondCamera second, Guid entityId)
    {
        await using var db = world.Read();
        var person = Track.Create(second.RunId, second.VideoId, 3, ObjectClass.Person, 300_000, 320_000, Now.AddHours(-3).AddMinutes(-30),
            detectionCount: 6, meanConfidence: 0.75, maxConfidence: 0.85, createdAtUtc: Now.AddMinutes(-5));
        db.Add(person);
        await db.SaveChangesAsync();
        await db.Database.ExecuteSqlInterpolatedAsync($"""
            INSERT INTO entities (id, entity_type, display_code, identity_status, review_status, created_at_utc, updated_at_utc)
            VALUES ({entityId}, 'Person', {Entity.DisplayCodeFor(EntityType.Person, entityId)}, 'Unknown', 'Confirmed', {Now}, {Now})
            """);
        await db.Database.ExecuteSqlInterpolatedAsync(
            $"UPDATE tracks SET entity_id = {entityId} WHERE id = {world.TrackId} OR id = {person.Id}");
        return person.Id;
    }

    private static ApiTestFactory CreateFactory(SceneAnalyticsWorld world) => new()
    {
        Clock = world.Clock,
        EnableSceneAnalyticsHost = false,
        MediaRootOverride = world.MediaRoot,
        EvidenceRootOverride = world.EvidenceRoot,
    };
}
