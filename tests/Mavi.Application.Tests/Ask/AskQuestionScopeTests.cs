using System.Text.Json.Nodes;
using Mavi.Application.Modules.Ask;

namespace Mavi.Application.Tests.Ask;

/// <summary>Lexical gating (ADR-026 §4, proposed amendment D-S10-6): only what the question names can be written.</summary>
public sealed class AskQuestionScopeTests
{
    private static readonly AskSiteCatalogue Catalogue = AskCorpus.LoadCatalogue();
    private static readonly Mavi.Contracts.Api.Query.QueryContractResponse Vocabulary = AskCorpus.LoadVocabulary();

    private static AskQuestionScope Scope(string question) => AskQuestionScope.From(question, Catalogue, Vocabulary);

    private static AskCatalogueCamera Camera(string code) => Catalogue.Cameras.Single(camera => camera.Code == code);

    [Fact]
    public void ACameraIsNamedByEveryWordOfItsShortNameOrThroughItsOwnZoneOrLine()
    {
        Assert.Equal([Camera("POC-S2-07").CameraId], Scope("How many people at the Scramble crossing camera today?").Cameras);
        Assert.Equal([Camera("POC-S2-09").CameraId], Scope("Cars at the School parking lot").Cameras);
        var viaLine = Scope("People crossing the Crosswalk line at Macedonia Square");
        Assert.Contains(Camera("POC-S2-02").CameraId, viaLine.Cameras);
        Assert.Equal([Camera("POC-S2-02").Lines[0].LineId], viaLine.Lines);
        Assert.Empty(Scope("Count events by camera today").Cameras);
        Assert.Empty(Scope("How many vehicles at the junction?").Cameras);
    }

    [Fact]
    public void AGenericWordDoesNotNameAZoneOrLine()
    {
        // "Count line" (camera 03) is not named by every question that says "count".
        var scope = Scope("Count stopped-vehicle events today");
        Assert.Empty(scope.Lines);
        Assert.Empty(scope.Cameras);
    }

    [Theory]
    [InlineData("Vehicles that entered through the Arch gate", "bToA")]
    [InlineData("Vehicles that left through the Arch gate", "aToB")]
    [InlineData("Vehicles at the Arch gate exit", "aToB")]
    public void ALineDirectionIsOfferedOnlyOnTheSideTheQuestionNames(string question, string side)
    {
        var arch = Camera("POC-S2-05").Lines.Single(line => line.Name == "Arch gate").LineId;
        Assert.Equal([side], Scope(question).LineSides[arch]);
    }

    [Fact]
    public void WithoutADirectionWordNoDirectionIsOffered()
    {
        var arch = Camera("POC-S2-05").Lines.Single(line => line.Name == "Arch gate").LineId;
        Assert.Empty(Scope("Person tracks that crossed the Arch gate line by hour").LineSides[arch]);
    }

    [Fact]
    public void OnlyTheAttributeValuesTheQuestionSaysAreOffered()
    {
        var scope = Scope("Find people with a red top");
        Assert.Equal(["red"], scope.AttributeValues["person-upper-colour"]);
        Assert.DoesNotContain("person-carried-bag", scope.AttributeValues.Keys);
        Assert.Equal(["present"], Scope("people with a backpack").AttributeValues["person-carried-bag"]);
        Assert.Empty(Scope("How many vehicles were seen today?").AttributeValues);
    }

    [Fact]
    public void RulesNeedAnEventNounAndClassesAClassWord()
    {
        Assert.Equal(["zone-dwell"], Scope("How many zone dwell events were there?").Rules);
        Assert.Empty(Scope("Show people who dwelled in the Waiting area for more than 2 minutes").Rules);
        Assert.Equal(["line-crossing"], Scope("Line crossings at the Junction exit line by direction").Rules);
        Assert.Empty(Scope("Show the last event at the Archway gate camera").ObjectClasses);
        Assert.Equal(["Person", "Vehicle"], Scope("How many person and vehicle tracks were there?").ObjectClasses);
    }

    [Fact]
    public void TheGrammarOffersNothingTheQuestionDoesNotName()
    {
        var site = new AskSiteTime("Asia/Kolkata", new DateOnly(2026, 10, 1));
        var grammar = JsonNode.Parse(AskGrammar.Build(Vocabulary, Catalogue, site, Scope("Count events by camera today")))!.ToJsonString();
        foreach (var absent in new[] { "\"cameraIds\":", "\"zone\":", "\"line\":", "\"attributes\":", "\"plateText\":", "\"ruleIds\":", "\"objectClass\":", "\"entity\"" })
            Assert.DoesNotContain(absent, grammar, StringComparison.Ordinal);
        Assert.Contains("05:30$", grammar, StringComparison.Ordinal); // the site offset ends every instant pattern
    }
}
