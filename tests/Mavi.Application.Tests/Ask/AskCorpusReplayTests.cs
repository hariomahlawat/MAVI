using System.Text.Json.Nodes;
using Mavi.Application.Modules.Ask;

namespace Mavi.Application.Tests.Ask;

/// <summary>
/// The Ask MAVI translation tests in CI (ADR-026 §6). CI cannot run the model, so each recording set — model outputs
/// recorded locally against a pinned pack, runtime and device — is replayed through the real prompt builder, translator
/// and strict parser:
/// <list type="bullet">
/// <item>every prompt and grammar rebuilt from the current code and fixtures must hash to what the model was given
/// (otherwise the recordings are stale and must be re-recorded);</item>
/// <item>every recorded output must translate to the recorded outcome, and pass exactly when that outcome equals the
/// corpus expectation;</item>
/// <item>the recorded pass counts per split must be what the replay computes.</item>
/// </list>
/// This proves the pipeline and the recorded run, not a fresh inference.
/// </summary>
public sealed class AskCorpusReplayTests
{
    public static TheoryData<string> RecordingSets()
    {
        var data = new TheoryData<string>();
        foreach (var path in Directory.GetFiles(Path.Combine(AskCorpus.Root, AskCorpus.RecordingsDirectory), AskCorpus.RecordingsPattern).Order(StringComparer.Ordinal))
            data.Add(Path.GetFileName(path));
        return data;
    }

    [Fact]
    public void AtLeastOneRecordingSetExists()
    {
        Assert.NotEmpty(RecordingSets());
    }

    [Fact]
    public void EveryExpectedQueryIsAValidContractQuery()
    {
        // Prompt v1's corpus: 20 development and 40 held questions (the held split is spent; v2 develops on all 60).
        var (_, _, questions) = AskCorpus.LoadQuestions();
        var catalogue = AskCorpus.LoadCatalogue();
        Assert.Equal(60, questions.Count);
        Assert.Equal(20, questions.Count(question => question.Split == "development"));
        Assert.Equal(40, questions.Count(question => question.Split == "held"));
        foreach (var question in questions)
            Assert.NotEmpty(AskCorpus.ExpectedOutcome(AskCorpus.Resolve(question.Expect, catalogue)));
    }

    [Theory]
    [MemberData(nameof(RecordingSets))]
    public void RecordingSetReplaysExactly(string fileName)
    {
        var recording = JsonNode.Parse(AskCorpus.Read(Path.Combine(AskCorpus.RecordingsDirectory, fileName)))!.AsObject();
        Assert.Equal("mavi-ask-recordings-v1", (string)recording["schemaVersion"]!);
        // Each set replays through the prompt version it was recorded with (v1 is kept byte for byte), on that version's corpus.
        var version = (string)recording["promptTemplateVersion"]!;
        var v2 = AskPrompt.IsVersion2(version);
        var questionsPath = AskCorpus.QuestionsPathFor(version);
        Assert.Equal(AskCorpus.TextSha256(questionsPath), (string)recording["questionsSha256"]!);
        Assert.Equal(AskCorpus.TextSha256(AskCorpus.CataloguePath), (string)recording["catalogueSha256"]!);

        var (zoneId, referenceDate, questions) = AskCorpus.LoadQuestions(questionsPath);
        var catalogue = AskCorpus.LoadCatalogue();
        var vocabulary = AskCorpus.LoadVocabulary();
        var siteTime = new AskSiteTime(zoneId, referenceDate);
        var byId = questions.ToDictionary(question => question.Id);
        // A measured set holds every corpus question exactly once, in corpus order: nothing can be dropped or repeated
        // with the summary edited to match.
        Assert.Equal("all", (string)recording["split"]!);
        Assert.Equal(questions.Select(question => question.Id), recording["results"]!.AsArray().Select(item => (string)item!["id"]!));

        var passed = new Dictionary<string, int> { ["development"] = 0, ["held"] = 0 };
        var total = new Dictionary<string, int> { ["development"] = 0, ["held"] = 0 };
        foreach (var result in recording["results"]!.AsArray().Select(item => item!.AsObject()))
        {
            var id = (string)result["id"]!;
            var question = byId[id];
            Assert.Equal(question.Split, (string)result["split"]!);

            var prompt = AskPrompt.Build(vocabulary, catalogue, siteTime, question.Text, version);
            Assert.True(prompt.PromptSha256 == (string)result["promptSha256"]!, $"{id}: the prompt changed since recording; re-record.");
            Assert.True(prompt.GrammarSha256 == (string)result["grammarSha256"]!, $"{id}: the grammar changed since recording; re-record.");

            // v2: a question naming a place the site lacks is refused before the model, so its row has no output; the
            // current code must still refuse it, and must still let every other question through.
            var preChecked = v2 && AskPlaceReferences.Unknown(question.Text, catalogue).Count > 0;
            Assert.Equal(preChecked ? AskCodes.StageQuestion : null, (string?)result["stage"]);
            string outcome;
            if (preChecked)
            {
                Assert.Null(result["output"]);
                outcome = AskCorpus.PreCheckOutcome;
            }
            else
            {
                outcome = AskCorpus.Outcome(AskTranslator.Translate((string)result["output"]!, siteTime, v2 ? question.Text : null));
            }

            var expected = AskCorpus.ExpectedOutcome(AskCorpus.Resolve(question.Expect, catalogue));
            Assert.Equal((string)result["outcome"]!, outcome);
            Assert.Equal((string)result["expected"]!, expected);
            Assert.Equal((bool)result["pass"]!, outcome == expected);

            total[question.Split]++;
            if (outcome == expected)
                passed[question.Split]++;
        }

        var summary = recording["summary"]!.AsObject();
        foreach (var split in new[] { "development", "held" })
        {
            Assert.Equal((int)summary[split]!["total"]!, total[split]);
            Assert.Equal((int)summary[split]!["passed"]!, passed[split]);
        }
    }
}
