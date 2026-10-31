using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Ask;
using Mavi.Contracts.Api.Ask;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Mavi.IntegrationTests;

/// <summary>
/// Ask MAVI end to end over the real API, the real S9 service and a stub language role (ADR-026; register C9.2, C9.3):
/// Ask proposes and the operator confirms (D-S10-10). Ask returns the interpreted query and never runs it; running it
/// through POST /api/query answers that exact query. Every refusal stage is reported with its code, and nothing the
/// model writes is returned.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class AskApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private sealed class StubRuntime(string text) : ILanguageRuntime
    {
        public List<LanguageCompletionRequest> Requests { get; } = [];

        public LanguageRuntimeIdentity Identity { get; } =
            new(true, "mavi-language-v1-test", "qwen2-5-1-5b-instruct", "Q8_0", "llamacpp-b12000-win-x64", "cpu", "policy_cpu");

        public Task<bool> IsAnsweringAsync(CancellationToken cancellationToken) => Task.FromResult(true);

        public Task<LanguageCompletion> CompleteAsync(LanguageCompletionRequest request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            return Task.FromResult(new LanguageCompletion(text, 100, 20, false));
        }
    }

    private static string CountQuery(Guid cameraId, string extraWhere = "") =>
        """{"answer":"query","query":{"contractVersion":"mavi-query-v1","unit":"track","where":{"timeWindow":{"fromUtc":"2026-09-21T00:00:00+00:00","toUtc":"2026-09-22T00:00:00+00:00"},"cameraIds":["CAMERA"]EXTRA},"operation":{"op":"count"}}}"""
            .Replace("CAMERA", cameraId.ToString("D"), StringComparison.Ordinal)
            .Replace("EXTRA", extraWhere, StringComparison.Ordinal);

    private async Task<(SceneAnalyticsWorld World, HttpClient Client, StubRuntime? Runtime, IAsyncDisposable Factory)> HostAsync(Func<SceneAnalyticsWorld, string>? modelText)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var runtime = modelText is null ? null : new StubRuntime(modelText(world));
        var factory = new ApiTestFactory
        {
            Clock = world.Clock,
            EnableSceneAnalyticsHost = false,
            MediaRootOverride = world.MediaRoot,
            EvidenceRootOverride = world.EvidenceRoot,
        };
        var host = runtime is null
            ? factory
            : factory.WithWebHostBuilder(builder => builder.ConfigureTestServices(services =>
            {
                services.RemoveAll<ILanguageRuntime>();
                services.AddSingleton<ILanguageRuntime>(runtime);
            }));
        return (world, host.CreateClient(), runtime, host);
    }

    private static async Task<AskResponse> AskAsync(HttpClient client, string question = "How many tracks today?")
    {
        using var response = await client.PostAsJsonAsync("/api/ask", new { question, referenceDate = "2026-09-21" });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<AskResponse>(body, JsonSerializerOptions.Web)!;
    }

    [Fact]
    public async Task AQuestionIsInterpretedNotRunAndRunningTheInterpretationAnswersThatExactQuery()
    {
        var (world, client, runtime, factory) = await HostAsync(world => CountQuery(world.CameraId));
        await using var _ = factory;

        using var raw = await client.PostAsJsonAsync("/api/ask", new { question = "How many tracks today?", referenceDate = "2026-09-21" });
        var body = JsonNode.Parse(await raw.Content.ReadAsStringAsync())!.AsObject();
        // No answer exists before the operator runs the query: the response has no envelope member at all.
        Assert.False(body.ContainsKey("envelope"));
        var answer = JsonSerializer.Deserialize<AskResponse>(body.ToJsonString(), JsonSerializerOptions.Web)!;

        Assert.Equal(AskCodes.Interpreted, answer.Outcome);
        Assert.Null(answer.Refusal);
        Assert.Equal("UTC", answer.SiteTimeZoneId);
        var resolved = answer.Interpretation!.ResolvedQuery;
        Assert.Equal("2026-09-21T00:00:00.000Z", resolved.GetProperty("where").GetProperty("timeWindow").GetProperty("fromUtc").GetString());
        var camera = Assert.Single(answer.Interpretation.References);
        Assert.Equal(("camera", world.CameraId), (camera.Kind, camera.Id));

        // Run is POST /api/query of the interpretation: it answers that exact query, with the same fingerprint.
        using var run = await client.PostAsync("/api/query", new StringContent(resolved.GetRawText(), System.Text.Encoding.UTF8, "application/json"));
        Assert.Equal(HttpStatusCode.OK, run.StatusCode);
        var envelope = JsonNode.Parse(await run.Content.ReadAsStringAsync())!.AsObject();
        Assert.Equal(answer.Interpretation.QueryFingerprint, (string)envelope["queryFingerprint"]!);
        Assert.Equal(JsonNode.Parse(resolved.GetRawText())!.ToJsonString(), envelope["resolvedQuery"]!.ToJsonString());

        // The model saw the catalogue and the contract; its identity and the greedy decoding are reported.
        var request = Assert.Single(runtime!.Requests);
        Assert.Contains(world.CameraId.ToString("D"), request.Prompt, StringComparison.Ordinal);
        Assert.Contains("mavi-query-v1", request.Prompt, StringComparison.Ordinal);
        Assert.Equal((0d, 1, 42), (request.Decoding.Temperature, request.Decoding.TopK, request.Decoding.Seed));
        Assert.Equal("mavi-language-v1-test", answer.Model.ModelPackId);
        Assert.Equal(AskPrompt.Sha256(request.Prompt), answer.Model.PromptSha256);
    }

    [Fact]
    public async Task AQuestionNamingAPlaceTheSiteLacksIsRefusedBeforeTheModel()
    {
        var (_, client, runtime, factory) = await HostAsync(world => CountQuery(world.CameraId));
        await using var _ = factory;

        var answer = await AskAsync(client, "How many vehicles were in the Loading dock zone today?");

        Assert.Equal("refused", answer.Outcome);
        Assert.Equal((AskCodes.StageQuestion, AskCodes.UnknownReference, "/question"), (answer.Refusal!.Stage, answer.Refusal.Code, answer.Refusal.Path));
        Assert.Equal(AskCodes.ModelRefusalMessage(AskCodes.UnknownReference), answer.Refusal.Message);
        Assert.Null(answer.Interpretation);
        Assert.Empty(runtime!.Requests); // decided by the platform; the model is never asked
        Assert.Null(answer.Model.PromptSha256);
    }

    [Theory]
    [InlineData("model", "outside_contract")]
    [InlineData("translation", "model_output_invalid")]
    [InlineData("translation", "time_offset_mismatch")]
    [InlineData("translation", "plate_text_ungrounded")]
    [InlineData("contract", "unknown_member")]
    public async Task EveryRefusalStageIsReportedWithItsCodeAndNoAnswer(string stage, string code)
    {
        var (_, client, _, factory) = await HostAsync(world => code switch
        {
            "outside_contract" => """{"answer":"refusal","reason":"outside_contract"}""",
            "model_output_invalid" => "There were 12 vehicles at the gate.",
            "time_offset_mismatch" => CountQuery(world.CameraId).Replace("+00:00", "+05:30", StringComparison.Ordinal),
            "unknown_member" => CountQuery(world.CameraId, ",\"speedKmh\":50"),
            // Prompt v2 (m2): the question says no plate, so a plate text the model wrote is refused.
            _ => CountQuery(world.CameraId, ",\"plateText\":{\"text\":\"KA01\"}"),
        });
        await using var _ = factory;

        var answer = await AskAsync(client);

        Assert.Equal("refused", answer.Outcome);
        Assert.Equal((stage, code), (answer.Refusal!.Stage, answer.Refusal.Code));
        Assert.Null(answer.Interpretation);
        // No text the model wrote reaches the response: neither its prose nor a member name it invented.
        var serialised = JsonSerializer.Serialize(answer);
        Assert.DoesNotContain("There were", serialised, StringComparison.Ordinal);
        Assert.DoesNotContain("speedKmh", serialised, StringComparison.Ordinal);
    }

    [Fact]
    public async Task AskNeverEvaluatesAQueryTheServiceWouldRefuse()
    {
        // A camera the platform does not have: the S9 service would refuse it as unknown when run. Ask does not run it,
        // so it proposes it unchanged; the refusal comes only when the operator runs it.
        var unknownCamera = Guid.Parse("01a18a8b-0000-7000-8000-000000000001");
        var (_, client, _, factory) = await HostAsync(_ => CountQuery(unknownCamera));
        await using var _ = factory;

        var answer = await AskAsync(client);
        Assert.Equal(AskCodes.Interpreted, answer.Outcome);
        Assert.Null(answer.Refusal);

        using var run = await client.PostAsync("/api/query", new StringContent(answer.Interpretation!.ResolvedQuery.GetRawText(), System.Text.Encoding.UTF8, "application/json"));
        Assert.NotEqual(HttpStatusCode.OK, run.StatusCode);
        Assert.Contains("unknown_reference", await run.Content.ReadAsStringAsync(), StringComparison.Ordinal);
    }

    [Fact]
    public void TheAskServiceCannotEvaluateAQuery()
    {
        // No execution path without the operator's Run: Ask has no access to the query service at all.
        var parameters = typeof(AskService).GetConstructors().SelectMany(constructor => constructor.GetParameters()).Select(parameter => parameter.ParameterType);
        Assert.DoesNotContain(typeof(Mavi.Application.Modules.Query.StructuredQueryService), parameters);
        Assert.Null(typeof(AskResponse).GetProperty("Envelope"));
    }

    [Fact]
    public async Task WithNoLanguageRoleAskRefusesAndStatusSaysSo()
    {
        var (_, client, _, factory) = await HostAsync(null);
        await using var _ = factory;

        var answer = await AskAsync(client);
        Assert.Equal(("runtime", AskCodes.LanguageUnavailable), (answer.Refusal!.Stage, answer.Refusal.Code));

        var status = await client.GetFromJsonAsync<AskStatusResponse>("/api/ask/status", JsonSerializerOptions.Web);
        Assert.False(status!.Bound);
        Assert.False(status.Answering);
        Assert.Equal(AskCodes.LanguageUnavailable, status.Reason);
    }

    [Fact]
    public async Task AnUnknownSiteTimeZoneIsRefusedEvenWithoutAReferenceDate()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var runtime = new StubRuntime(CountQuery(world.CameraId));
        await using var factory = new ApiTestFactory
        {
            Clock = world.Clock,
            EnableSceneAnalyticsHost = false,
            MediaRootOverride = world.MediaRoot,
            EvidenceRootOverride = world.EvidenceRoot,
        }.WithWebHostBuilder(builder =>
        {
            builder.UseSetting("Ask:SiteTimeZoneId", "Mars/Olympus_Mons");
            builder.ConfigureTestServices(services =>
            {
                services.RemoveAll<ILanguageRuntime>();
                services.AddSingleton<ILanguageRuntime>(runtime);
            });
        });
        using var client = factory.CreateClient();

        // No reference date: the default date must not be derived from a zone that does not exist.
        using var response = await client.PostAsJsonAsync("/api/ask", new { question = "How many tracks today?" });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var answer = JsonSerializer.Deserialize<AskResponse>(await response.Content.ReadAsStringAsync(), JsonSerializerOptions.Web)!;
        Assert.Equal(("runtime", AskCodes.SiteTimeZoneInvalid), (answer.Refusal!.Stage, answer.Refusal.Code));
        Assert.Empty(runtime.Requests);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public async Task AnEmptyQuestionIsRefusedBeforeTheModel(string question)
    {
        var (_, client, runtime, factory) = await HostAsync(world => CountQuery(world.CameraId));
        await using var _ = factory;

        var answer = await AskAsync(client, question);

        Assert.Equal(AskCodes.QuestionInvalid, answer.Refusal!.Code);
        Assert.Empty(runtime!.Requests);
    }
}
