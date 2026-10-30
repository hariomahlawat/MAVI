using System.Text.Json.Nodes;
using Mavi.Application.Modules.Ask;

namespace Mavi.Application.Tests.Ask;

/// <summary>
/// Prompt v2 (ADR-026 amendment D-S10-9, owner decision D-S10-8): unknown places are refused before the model; the
/// tighter gating (m3); plate text grounded in the question (m2); every offset of a daylight-saving zone (m8); and
/// one query shape per unit. v1 is unchanged (its recordings replay in <see cref="AskCorpusReplayTests"/>).
/// </summary>
public sealed class AskPromptV2Tests
{
    private static readonly AskSiteCatalogue Catalogue = AskCorpus.LoadCatalogue();
    private static readonly Mavi.Contracts.Api.Query.QueryContractResponse Vocabulary = AskCorpus.LoadVocabulary();
    private static readonly AskSiteTime Kolkata = new("Asia/Kolkata", new DateOnly(2026, 10, 1));

    private static AskQuestionScope Scope(string question, string version = AskPrompt.TemplateVersion2) =>
        AskQuestionScope.From(question, Catalogue, Vocabulary, version);

    private static AskCatalogueCamera Camera(string code) => Catalogue.Cameras.Single(camera => camera.Code == code);

    [Fact]
    public void TheApiUsesPromptV2AndAnUnknownVersionIsAnError()
    {
        Assert.Equal("mavi-ask-prompt-v2", AskPrompt.TemplateVersion);
        Assert.Throws<ArgumentOutOfRangeException>(() => AskPrompt.IsVersion2("mavi-ask-prompt-v3"));
    }

    [Theory]
    [InlineData("Count people at the Central Station camera today")]
    [InlineData("Count vehicles in the Loading dock zone")]
    [InlineData("How many vehicles crossed the Bridge line?")]
    [InlineData("Show vehicles at camera 14 today")]
    [InlineData("People in zone C this morning")]
    [InlineData("How many cars passed Victoria Gardens today?")]
    [InlineData("Loading dock zone vehicles today")]
    [InlineData("Persons near the front camera")]
    public void APlaceTheSiteDoesNotHaveIsUnknown(string question)
    {
        Assert.NotEmpty(AskPlaceReferences.Unknown(question, Catalogue));
    }

    [Theory]
    [InlineData("Which camera had the most vehicle tracks yesterday?")]
    [InlineData("How many people walked Toward the camera over the Crosswalk line at Macedonia Square?")]
    [InlineData("Count events by camera today")]
    [InlineData("Line crossings at the Junction exit line by direction today")]
    [InlineData("How many zone dwell events were there at the Bus stop waiting room?")]
    [InlineData("Group events at the School cafe lobby by line direction today")]
    [InlineData("Count line crossings today")]
    [InlineData("Show the 20 most recent vehicle tracks on Caton Farm Road")]
    [InlineData("Number of events at the busiest camera")]
    [InlineData("Vehicles at camera 7 today")]
    [InlineData("Delete all tracks from the Highway camera")]
    [InlineData("Top 3 zones by events at the Worringer Platz junction today")]
    [InlineData("Find people with a red top at the School hallway on Monday")]
    public void NamedOrGenericPlacesAreNotUnknown(string question)
    {
        Assert.Empty(AskPlaceReferences.Unknown(question, Catalogue));
    }

    [Fact]
    public void AReferenceNamesTheItemsWhoseNamesContainItsWords()
    {
        Assert.Equal([Camera("POC-S2-04").CameraId], Scope("Vehicles at the Highway camera today").Cameras);
        Assert.Equal([Camera("POC-S2-07").CameraId], Scope("Vehicles at camera 7 today").Cameras);
        Assert.Equal([Camera("POC-S2-02").CameraId], Scope("How many people at Macedonia Square today?").Cameras);
        // v1 names neither: its gating needs every word of the short name.
        Assert.Empty(Scope("Vehicles at the Highway camera today", AskPrompt.TemplateVersion1).Cameras);
        Assert.Empty(Scope("How many people at Macedonia Square today?", AskPrompt.TemplateVersion1).Cameras);
    }

    [Fact]
    public void ASingleWordNameNeedsItsKindAfterIt()
    {
        var crossing = Camera("POC-S2-07").Zones.Single(zone => zone.Name == "Crossing").ZoneId;
        Assert.DoesNotContain(crossing, Scope("Compare person tracks at the Scramble crossing today with yesterday").Zones);
        Assert.Contains(crossing, Scope("People in the crossing zone at the Scramble crossing").Zones);
        // v1 offered it for any "crossing" (the h21 miss): kept for v1's recordings.
        Assert.Contains(crossing, Scope("Compare person tracks at the Scramble crossing today with yesterday", AskPrompt.TemplateVersion1).Zones);
    }

    [Fact]
    public void ANameEndingInItsKindIsSaidAsAPhrase()
    {
        var countLine = Camera("POC-S2-03").Lines.Single(line => line.Name == "Count line").LineId;
        Assert.DoesNotContain(countLine, Scope("Count Person tracks that crossed the Arch gate line by hour").Lines);
        Assert.Contains(countLine, Scope("Vehicles over the count line at Caton Farm Road").Lines);
    }

    [Theory]
    [InlineData("People who went in through the Doorway line", new[] { "bToA" })]
    [InlineData("People who walked out through the Doorway line", new[] { "aToB" })]
    [InlineData("People crossing the Doorway line in the morning", new string[0])]
    public void InAndOutSidesNeedAVerbPhraseOrASynonym(string question, string[] sides)
    {
        var doorway = Camera("POC-S2-10").Lines.Single(line => line.Name == "Doorway line").LineId;
        Assert.Equal(sides, Scope(question).LineSides[doorway]);
    }

    [Theory]
    [InlineData("People crossing the Landing line to the door", new[] { "aToB" })]
    [InlineData("People crossing the Landing line away from the door", new[] { "bToA" })]
    [InlineData("People crossing the Landing line by the door", new string[0])]
    public void ToAndFromSidesNeedTheirPhrase(string question, string[] sides)
    {
        var landing = Camera("POC-S2-12").Lines.Single(line => line.Name == "Landing line").LineId;
        Assert.Equal(sides, Scope(question).LineSides[landing]);
    }

    private const string PlateQuery =
        """{"answer":"query","query":{"contractVersion":"mavi-query-v1","unit":"track","where":{"timeWindow":{"fromUtc":"2026-10-01T00:00:00+05:30","toUtc":"2026-10-02T00:00:00+05:30"},"plateText":{"text":"ka-01","match":"contains"}},"operation":{"op":"count"}}}""";

    [Theory]
    [InlineData("How many cars with a plate containing KA 01 today?", null)]
    [InlineData("How many cars with plate ka-01 today?", null)]
    [InlineData("How many cars with a plate containing KA02 today?", AskCodes.PlateTextUngrounded)]
    [InlineData("How many cars with a Karnataka plate today?", AskCodes.PlateTextUngrounded)]
    public void APlateTextMustOccurInTheQuestion(string question, string? refusal)
    {
        var translation = AskTranslator.Translate(PlateQuery, Kolkata, question);
        Assert.Equal(refusal, translation.Refusal?.Code);
        if (refusal is not null)
            Assert.Equal((AskCodes.StageTranslation, "/query/where/plateText/text"), (translation.Refusal!.Stage, translation.Refusal.Path));
        // v1 (no question) checks nothing.
        Assert.Null(AskTranslator.Translate(PlateQuery, Kolkata).Refusal);
    }

    [Fact]
    public void ADaylightSavingZoneOffersBothOffsets()
    {
        var berlin = new AskSiteTime("Europe/Berlin", new DateOnly(2026, 10, 25));
        Assert.Equal([TimeSpan.FromHours(1), TimeSpan.FromHours(2)], berlin.Offsets);
        Assert.Equal([TimeSpan.FromMinutes(330)], Kolkata.Offsets);

        var v2 = AskPrompt.Build(Vocabulary, Catalogue, berlin, "How many vehicles today?", AskPrompt.TemplateVersion2);
        Assert.EndsWith(@"(\+01:00|\+02:00)$", InstantPattern(v2.Grammar), StringComparison.Ordinal);
        Assert.Contains("the zone's offset at that instant (+01:00 or +02:00)", v2.Prompt, StringComparison.Ordinal);
        // The day of the change: "today" runs from +02:00 midnight to +01:00 midnight.
        Assert.Contains("\"fromUtc\":\"2026-10-25T00:00:00+02:00\",\"toUtc\":\"2026-10-26T00:00:00+01:00\"", v2.Prompt, StringComparison.Ordinal);
        var window = """{"answer":"query","query":{"contractVersion":"mavi-query-v1","unit":"track","where":{"timeWindow":{"fromUtc":"2026-10-25T00:00:00+02:00","toUtc":"2026-10-26T00:00:00+01:00"}},"operation":{"op":"count"}}}""";
        Assert.Null(AskTranslator.Translate(window, berlin, "How many vehicles today?").Refusal);

        var v1 = AskPrompt.Build(Vocabulary, Catalogue, berlin, "How many vehicles today?", AskPrompt.TemplateVersion1);
        Assert.EndsWith(@"T[0-9]{2}:[0-9]{2}:[0-9]{2}\+02:00$", InstantPattern(v1.Grammar, v2: false), StringComparison.Ordinal);
        Assert.Contains("with the offset +02:00", v1.Prompt, StringComparison.Ordinal);
    }

    /// <summary>The pattern of the time window's fromUtc in the (first unit's) query shape.</summary>
    private static string InstantPattern(string grammar, bool v2 = true)
    {
        var query = JsonNode.Parse(grammar)!["anyOf"]![0]!["properties"]!["query"]!;
        var shape = v2 ? query["anyOf"]![0]! : query;
        return (string)shape["properties"]!["where"]!["properties"]!["timeWindow"]!["properties"]!["fromUtc"]!["pattern"]!;
    }

    [Fact]
    public void ASingleOffsetZoneKeepsTheV1TimeSentence()
    {
        var v2 = AskPrompt.Build(Vocabulary, Catalogue, Kolkata, "How many vehicles today?", AskPrompt.TemplateVersion2);
        Assert.Contains("every instant is site local time with the offset +05:30.", v2.Prompt, StringComparison.Ordinal);
        Assert.Contains("\"by hour\", \"per hour\", \"hourly\": always timeBucket 3600", v2.Prompt, StringComparison.Ordinal);
        Assert.Contains("by hour between 10:00 and 12:00<|im_end|>", v2.Prompt, StringComparison.Ordinal);
    }

    [Fact]
    public void EachUnitIsOfferedOnlyItsOwnPredicatesDimensionsAndFields()
    {
        var question = "How many different tracks triggered line crossing events or people with a plate KA01 in the Gate approach zone today, by camera?";
        var grammar = JsonNode.Parse(AskPrompt.Build(Vocabulary, Catalogue, Kolkata, question, AskPrompt.TemplateVersion2).Grammar)!;
        var units = grammar["anyOf"]![0]!["properties"]!["query"]!["anyOf"]!.AsArray()
            .ToDictionary(item => (string)item!["properties"]!["unit"]!["const"]!, item => item!["properties"]!.AsObject());

        Assert.Equal(["track", "event"], units.Keys);
        var trackWhere = units["track"]["where"]!["properties"]!.AsObject();
        var eventWhere = units["event"]["where"]!["properties"]!.AsObject();
        Assert.Contains("plateText", trackWhere.Select(pair => pair.Key));
        Assert.DoesNotContain("ruleIds", trackWhere.Select(pair => pair.Key));
        Assert.Contains("ruleIds", eventWhere.Select(pair => pair.Key));
        Assert.DoesNotContain("plateText", eventWhere.Select(pair => pair.Key));
        Assert.Equal(["zoneId"], eventWhere["zone"]!["properties"]!.AsObject().Select(pair => pair.Key));
        Assert.Equal(["zoneId", "relation", "minDwellMs", "loitering"], trackWhere["zone"]!["properties"]!.AsObject().Select(pair => pair.Key));

        string[] Fields(string unit) => [.. units[unit]["operation"]!["anyOf"]!.AsArray()
            .Single(item => (string?)item!["properties"]!["op"]!["const"] == "countDistinct")!["properties"]!["field"]!["enum"]!.AsArray().Select(value => (string)value!)];
        Assert.Equal(["camera", "objectClass", "video"], Fields("track"));
        Assert.Equal(["camera", "track", "rule"], Fields("event"));
    }

    [Fact]
    public void TheV1PromptAndGrammarAreUnchanged()
    {
        // The h01 v1 recording's hashes (7B pack): v1 bytes must not move, or the v1 recordings stop replaying.
        var (zoneId, referenceDate, questions) = AskCorpus.LoadQuestions();
        var h01 = questions.Single(question => question.Id == "h01");
        var recording = JsonNode.Parse(AskCorpus.Read("contracts/test-vectors/ask-mavi-recordings-qwen2.5-7b-q4-k-m-laptop-sm75-fit.json"))!;
        var row = recording["results"]!.AsArray().Single(item => (string)item!["id"]! == "h01")!;
        var prompt = AskPrompt.Build(Vocabulary, Catalogue, new AskSiteTime(zoneId, referenceDate), h01.Text, AskPrompt.TemplateVersion1);
        Assert.Equal((string)row["promptSha256"]!, prompt.PromptSha256);
        Assert.Equal((string)row["grammarSha256"]!, prompt.GrammarSha256);
    }
}
