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
/// the answer is exactly the structured query's envelope, every refusal stage is reported with its code and no
/// envelope, and nothing the model writes is returned.
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
    public async Task AnAnsweredQuestionReturnsExactlyTheStructuredQueryEnvelope()
    {
        var (world, client, runtime, factory) = await HostAsync(world => CountQuery(world.CameraId));
        await using var _ = factory;

        var answer = await AskAsync(client);

        Assert.Equal("answered", answer.Outcome);
        Assert.Null(answer.Refusal);
        Assert.Equal("UTC", answer.SiteTimeZoneId);
        var resolved = answer.Interpretation!.ResolvedQuery;
        Assert.Equal("2026-09-21T00:00:00.000Z", resolved.GetProperty("where").GetProperty("timeWindow").GetProperty("fromUtc").GetString());
        var camera = Assert.Single(answer.Interpretation.References);
        Assert.Equal(("camera", world.CameraId), (camera.Kind, camera.Id));

        // The same query posted directly answers the same envelope (the snapshot block aside).
        using var direct = await client.PostAsync("/api/query", new StringContent(resolved.GetRawText(), System.Text.Encoding.UTF8, "application/json"));
        var directEnvelope = JsonNode.Parse(await direct.Content.ReadAsStringAsync())!.AsObject();
        var askEnvelope = JsonNode.Parse(JsonSerializer.Serialize(answer.Envelope, JsonSerializerOptions.Web))!.AsObject();
        directEnvelope.Remove("snapshot");
        askEnvelope.Remove("snapshot");
        Assert.Equal(directEnvelope.ToJsonString(), askEnvelope.ToJsonString());

        // The model saw the catalogue and the contract; its identity and the greedy decoding are reported.
        var request = Assert.Single(runtime!.Requests);
        Assert.Contains(world.CameraId.ToString("D"), request.Prompt, StringComparison.Ordinal);
        Assert.Contains("mavi-query-v1", request.Prompt, StringComparison.Ordinal);
        Assert.Equal((0d, 1, 42), (request.Decoding.Temperature, request.Decoding.TopK, request.Decoding.Seed));
        Assert.Equal("mavi-language-v1-test", answer.Model.ModelPackId);
        Assert.Equal(AskPrompt.Sha256(request.Prompt), answer.Model.PromptSha256);
    }

    [Theory]
    [InlineData("model", "outside_contract")]
    [InlineData("translation", "model_output_invalid")]
    [InlineData("translation", "time_offset_mismatch")]
    [InlineData("contract", "unknown_member")]
    [InlineData("service", "unknown_reference")]
    public async Task EveryRefusalStageIsReportedWithItsCodeAndNoAnswer(string stage, string code)
    {
        var (_, client, _, factory) = await HostAsync(world => code switch
        {
            "outside_contract" => """{"answer":"refusal","reason":"outside_contract"}""",
            "model_output_invalid" => "There were 12 vehicles at the gate.",
            "time_offset_mismatch" => CountQuery(world.CameraId).Replace("+00:00", "+05:30", StringComparison.Ordinal),
            "unknown_member" => CountQuery(world.CameraId, ",\"speedKmh\":50"),
            _ => CountQuery(Guid.Parse("01a18a8b-0000-7000-8000-000000000001")),
        });
        await using var _ = factory;

        var answer = await AskAsync(client);

        Assert.Equal("refused", answer.Outcome);
        Assert.Equal((stage, code), (answer.Refusal!.Stage, answer.Refusal.Code));
        Assert.Null(answer.Envelope);
        Assert.Null(answer.Interpretation);
        // No text the model wrote reaches the response: neither its prose nor a member name it invented.
        var serialised = JsonSerializer.Serialize(answer);
        Assert.DoesNotContain("There were", serialised, StringComparison.Ordinal);
        Assert.DoesNotContain("speedKmh", serialised, StringComparison.Ordinal);
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
