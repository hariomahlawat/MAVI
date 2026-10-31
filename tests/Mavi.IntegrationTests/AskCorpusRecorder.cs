using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Ask;
using Mavi.Application.Tests.Ask;
using Mavi.Infrastructure.Language;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

/// <summary>
/// Records the Ask MAVI corpus against a running language role (ADR-026 §6). Skipped unless
/// <c>MAVI_ASK_RECORD</c> names the output file; it never runs in CI. The request is the production request
/// (<see cref="LlamaServerLanguageRuntime"/>), one question at a time in corpus order, and each result is bound to the
/// prompt and grammar hashes, so <c>AskCorpusReplayTests</c> can replay it without the model. The prompt version is the
/// API's (<see cref="AskPrompt.TemplateVersion"/>); a v2 question that names a place the site lacks is refused before
/// the model, as the API refuses it, and its row carries the stage and no output.
/// <code>
/// MAVI_ASK_RECORD=contracts/test-vectors/ask-mavi-recordings-&lt;label&gt;.json
/// MAVI_ASK_LANGUAGE_PORT=62301 (llama-server on 127.0.0.1)   MAVI_ASK_SPLIT=development|all
/// MAVI_ASK_QUESTIONS (default: the current prompt version's corpus; a v2 development pass names the v1 corpus)
/// MAVI_ASK_CACHE_PROMPT=true|false (required; as the installer binds Language:CachePrompt for the pack)
/// MAVI_ASK_LABEL, MAVI_ASK_MODEL_PACK_ID, MAVI_ASK_MODEL_ID, MAVI_ASK_QUANTISATION, MAVI_ASK_MODEL_SHA256,
/// MAVI_ASK_RUNTIME_ID, MAVI_ASK_DEVICE
/// dotnet test tests/Mavi.IntegrationTests --filter FullyQualifiedName~AskCorpusRecorder
/// </code>
/// </summary>
public sealed class AskCorpusRecorder
{
    [Fact]
    public async Task RecordCorpusWhenRequested()
    {
        var output = Environment.GetEnvironmentVariable("MAVI_ASK_RECORD");
        if (string.IsNullOrWhiteSpace(output))
            return;

        string Env(string name) => Environment.GetEnvironmentVariable(name) ?? throw new InvalidOperationException($"{name} is required.");
        var split = Environment.GetEnvironmentVariable("MAVI_ASK_SPLIT") ?? "development";
        Assert.True(split is "development" or "all", "MAVI_ASK_SPLIT is development or all.");

        using var runtime = new LlamaServerLanguageRuntime(Options.Create(new LanguageOptions
        {
            Enabled = true,
            Port = int.Parse(Env("MAVI_ASK_LANGUAGE_PORT"), System.Globalization.CultureInfo.InvariantCulture),
            TimeoutSeconds = 900,
            // MAVI_ASK_CACHE_PROMPT=true|false, required: prefix reuse only for a pack whose set was byte-identical in
            // reverse order (D-S10-7); the recorder never assumes it.
            CachePrompt = Environment.GetEnvironmentVariable("MAVI_ASK_CACHE_PROMPT") switch
            {
                "true" => true,
                "false" => false,
                _ => throw new InvalidOperationException("MAVI_ASK_CACHE_PROMPT must be true or false (D-S10-7)."),
            },
        }));
        var version = AskPrompt.TemplateVersion;
        var v2 = AskPrompt.IsVersion2(version);
        var questionsPath = Environment.GetEnvironmentVariable("MAVI_ASK_QUESTIONS") is { Length: > 0 } chosen ? chosen : AskCorpus.QuestionsPathFor(version);
        var (zoneId, referenceDate, questions) = AskCorpus.LoadQuestions(questionsPath);
        var catalogue = AskCorpus.LoadCatalogue();
        var vocabulary = AskCorpus.LoadVocabulary();
        var siteTime = new AskSiteTime(zoneId, referenceDate);

        var results = new JsonArray();
        var passed = new Dictionary<string, int> { ["development"] = 0, ["held"] = 0 };
        var total = new Dictionary<string, int> { ["development"] = 0, ["held"] = 0 };
        // MAVI_ASK_ORDER=reverse asks in reverse order (results are still written in corpus order): the same outputs in
        // both orders show that reusing the cached prompt prefix does not change what the model writes.
        var selected = questions.Where(item => split == "all" || item.Split == split).ToList();
        if (Environment.GetEnvironmentVariable("MAVI_ASK_ORDER") == "reverse")
            selected.Reverse();
        var rows = new SortedDictionary<int, JsonObject>();
        foreach (var question in selected)
        {
            var prompt = AskPrompt.Build(vocabulary, catalogue, siteTime, question.Text, version);
            var preChecked = v2 && AskPlaceReferences.Unknown(question.Text, catalogue).Count > 0;
            var clock = Stopwatch.StartNew();
            var completion = preChecked
                ? null
                : await runtime.CompleteAsync(new LanguageCompletionRequest(prompt.Prompt, prompt.Grammar, AskService.Decoding), CancellationToken.None);
            var latency = clock.ElapsedMilliseconds;
            var outcome = completion is null
                ? AskCorpus.PreCheckOutcome
                : completion.Truncated
                    ? $"refused:{AskCodes.StageTranslation}:{AskCodes.ModelOutputTruncated}"
                    : AskCorpus.Outcome(AskTranslator.Translate(completion.Text, siteTime, v2 ? question.Text : null));
            var expected = AskCorpus.ExpectedOutcome(AskCorpus.Resolve(question.Expect, catalogue));
            total[question.Split]++;
            if (outcome == expected)
                passed[question.Split]++;
            var row = new JsonObject
            {
                ["id"] = question.Id,
                ["split"] = question.Split,
                ["promptSha256"] = prompt.PromptSha256,
                ["grammarSha256"] = prompt.GrammarSha256,
                ["output"] = completion?.Text,
                ["promptTokens"] = completion?.PromptTokens,
                ["generatedTokens"] = completion?.GeneratedTokens,
                ["latencyMs"] = latency,
                ["outcome"] = outcome,
                ["expected"] = expected,
                ["pass"] = outcome == expected,
            };
            if (preChecked)
                row["stage"] = AskCodes.StageQuestion;
            rows.Add(questions.ToList().IndexOf(question), row);
        }

        foreach (var row in rows.Values)
            results.Add(row);
        var decoding = AskService.Decoding;
        var document = new JsonObject
        {
            ["schemaVersion"] = "mavi-ask-recordings-v1",
            ["$comment"] = "PoC S10 (ADR-026 §6) recorded model outputs, replayed in CI by AskCorpusReplayTests. Development evidence; the held split's exact-match rate is the measured claim. Re-record with AskCorpusRecorder.",
            ["label"] = Env("MAVI_ASK_LABEL"),
            ["recordedAtUtc"] = DateTimeOffset.UtcNow.ToString("O", System.Globalization.CultureInfo.InvariantCulture),
            ["promptTemplateVersion"] = version,
            ["questionsSha256"] = AskCorpus.TextSha256(questionsPath),
            ["catalogueSha256"] = AskCorpus.TextSha256(AskCorpus.CataloguePath),
            ["split"] = split,
            ["order"] = Environment.GetEnvironmentVariable("MAVI_ASK_ORDER") ?? "corpus",
            ["model"] = new JsonObject
            {
                ["modelPackId"] = Env("MAVI_ASK_MODEL_PACK_ID"),
                ["modelId"] = Env("MAVI_ASK_MODEL_ID"),
                ["quantisation"] = Env("MAVI_ASK_QUANTISATION"),
                ["ggufSha256"] = Env("MAVI_ASK_MODEL_SHA256"),
            },
            ["runtime"] = new JsonObject { ["runtimeId"] = Env("MAVI_ASK_RUNTIME_ID"), ["device"] = Env("MAVI_ASK_DEVICE") },
            ["decoding"] = new JsonObject
            {
                ["temperature"] = decoding.Temperature,
                ["topK"] = decoding.TopK,
                ["seed"] = decoding.Seed,
                ["maxTokens"] = decoding.MaxTokens,
                ["requestBody"] = Environment.GetEnvironmentVariable("MAVI_ASK_CACHE_PROMPT") == "false"
                    ? "LlamaServerLanguageRuntime.Body (cache_prompt false, every sampler pinned)"
                    : "LlamaServerLanguageRuntime.Body (cache_prompt true, every sampler pinned)",
            },
            ["summary"] = new JsonObject
            {
                ["development"] = new JsonObject { ["passed"] = passed["development"], ["total"] = total["development"] },
                ["held"] = new JsonObject { ["passed"] = passed["held"], ["total"] = total["held"] },
            },
            ["results"] = results,
        };
        var path = Path.IsPathRooted(output) ? output : Path.Combine(AskCorpus.Root, output);
        await File.WriteAllTextAsync(path, document.ToJsonString(new JsonSerializerOptions { WriteIndented = true }).Replace("\r\n", "\n", StringComparison.Ordinal) + "\n");
    }
}
