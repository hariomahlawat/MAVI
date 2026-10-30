using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Mavi.Application.Modules.Events;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Query;
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

    [Theory]
    [InlineData("derived")]
    [InlineData("underived")]
    public async Task TheGoldenCorpusAnswersExactlyAsFrozen(string setup)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        if (setup == "derived")
        {
            await using var scope = factory.Services.CreateAsyncScope();
            Assert.Equal(1, await scope.ServiceProvider.GetRequiredService<AnalyticEventService>().DeriveDueAsync(50, default));
        }

        using var corpus = JsonDocument.Parse(File.ReadAllText(CorpusPath()));
        var placeholders = corpus.RootElement.GetProperty("placeholders");
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

        foreach (var response in new[] { text, big, parameters })
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
            text = text.Replace(from, to, StringComparison.OrdinalIgnoreCase);
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

    private static ApiTestFactory CreateFactory(SceneAnalyticsWorld world) => new()
    {
        Clock = world.Clock,
        EnableSceneAnalyticsHost = false,
        MediaRootOverride = world.MediaRoot,
        EvidenceRootOverride = world.EvidenceRoot,
    };
}
