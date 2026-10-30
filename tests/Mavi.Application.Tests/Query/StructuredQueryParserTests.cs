using System.Text.Json;
using Mavi.Application.Modules.Query;

namespace Mavi.Application.Tests.Query;

/// <summary>
/// The parser against the frozen golden corpus (ADR-024 §1, §7): the same file <c>tools/verify_repo.py</c> holds the
/// JSON Schema to. A case the parser refuses must be a case the corpus expects refused, with its exact code and path;
/// every other case must parse, and its canonical form must be a fixed point.
/// </summary>
public sealed class StructuredQueryParserTests
{
    internal const string CorpusPath = "contracts/test-vectors/structured-query-v1-golden.json";

    public static TheoryData<string> CaseNames()
    {
        var data = new TheoryData<string>();
        foreach (var item in Corpus().RootElement.GetProperty("cases").EnumerateArray())
            data.Add(item.GetProperty("name").GetString()!);
        return data;
    }

    [Theory]
    [MemberData(nameof(CaseNames))]
    public void EveryCorpusCaseParsesOrIsRefusedExactlyAsTheCorpusSays(string name)
    {
        using var corpus = Corpus();
        var item = corpus.RootElement.GetProperty("cases").EnumerateArray()
            .Single(candidate => candidate.GetProperty("name").GetString() == name);
        var expect = item.GetProperty("expect");
        var parsed = StructuredQueryParser.Parse(item.GetProperty("query").GetRawText());

        // A case with no setup and a refusal is the parser's to refuse; every other case is valid at the parser and is
        // answered, or refused by the service against data.
        var parserRefuses = item.GetProperty("setup").GetString() == "none" && expect.TryGetProperty("refusal", out _);
        if (parserRefuses)
        {
            var refusal = expect.GetProperty("refusal");
            Assert.False(parsed.IsValid, $"{name} should be refused.");
            Assert.Equal(
                (refusal.GetProperty("code").GetString(), refusal.GetProperty("path").GetString()),
                (parsed.Refusal!.Code, parsed.Refusal.Path));
            Assert.Contains(parsed.Refusal.Code, QueryRefusalCodes.All);
            return;
        }

        Assert.True(parsed.IsValid, $"{name} was refused: {parsed.Refusal?.Code} at {parsed.Refusal?.Path}.");
        var canonical = StructuredQueryCanonical.Write(parsed.Query!);
        var again = StructuredQueryParser.Parse(canonical);
        Assert.True(again.IsValid);
        Assert.Equal(canonical, StructuredQueryCanonical.Write(again.Query!));
    }

    [Fact]
    public void TheCorpusCoversEveryUnitOperationAndEveryParserRefusalCode()
    {
        using var corpus = Corpus();
        var cases = corpus.RootElement.GetProperty("cases").EnumerateArray().ToList();
        var answered = cases.Where(item => item.GetProperty("expect").GetProperty("status").GetInt32() == 200).ToList();

        Assert.Equal(
            ["entity", "event", "track"],
            answered.Select(item => item.GetProperty("query").GetProperty("unit").GetString()).Distinct().Order());
        Assert.Equal(
            QueryContract.Operations.Order(),
            answered.Select(item => item.GetProperty("query").GetProperty("operation").GetProperty("op").GetString()).Distinct().Order());

        var refused = cases
            .Where(item => item.GetProperty("expect").TryGetProperty("refusal", out _))
            .Select(item => item.GetProperty("expect").GetProperty("refusal").GetProperty("code").GetString())
            .ToHashSet();
        // Not reachable from a JSON corpus: malformed text, a repeated member (a parsed JSON object cannot hold one),
        // the attribute vocabulary and capability wiring (host-dependent) and the scope bound; each has its own test.
        var elsewhere = new[]
        {
            QueryRefusalCodes.MalformedJson, QueryRefusalCodes.DuplicateMember, QueryRefusalCodes.AttributeCombinationInvalid,
            QueryRefusalCodes.CapabilityNotConfigured, QueryRefusalCodes.QueryScopeTooLarge,
        };
        Assert.Empty(QueryRefusalCodes.All.Except(refused).Except(elsewhere));
    }

    [Fact]
    public void AMemberRepeatedInTheRawTextIsRefusedNotLastOneWins()
    {
        const string text = """
            {"contractVersion":"mavi-query-v1","unit":"track","unit":"event",
             "where":{"timeWindow":{"fromUtc":"2026-09-21T05:00:00Z","toUtc":"2026-09-21T07:00:00Z"}},
             "operation":{"op":"count"}}
            """;
        var parsed = StructuredQueryParser.Parse(text);
        Assert.Equal((QueryRefusalCodes.DuplicateMember, "/unit"), (parsed.Refusal!.Code, parsed.Refusal.Path));
    }

    [Theory]
    [InlineData("")]
    [InlineData("{")]
    [InlineData("[1,2]")]
    [InlineData("null")]
    public void TextThatIsNotAQueryObjectIsRefused(string text)
    {
        var parsed = StructuredQueryParser.Parse(text);
        Assert.False(parsed.IsValid);
        Assert.Contains(parsed.Refusal!.Code, new[] { QueryRefusalCodes.MalformedJson, QueryRefusalCodes.InvalidValue });
    }

    [Fact]
    public void EquivalentSpellingsShareOneCanonicalFormAndFingerprint()
    {
        const string terse = """
            {"unit":"event","contractVersion":"mavi-query-v1","operation":{"op":"find"},
             "where":{"ruleIds":["zone-dwell","line-crossing"],"timeWindow":{"toUtc":"2026-09-21T07:00:00+00:00","fromUtc":"2026-09-21T05:00:00Z"}}}
            """;
        const string explicitForm = """
            {"contractVersion":"mavi-query-v1","unit":"event",
             "where":{"timeWindow":{"fromUtc":"2026-09-21T05:00:00.000Z","toUtc":"2026-09-21T07:00:00Z"},
                      "ruleIds":["line-crossing","zone-dwell"],"catalogueVersion":"mavi-events-v1"},
             "operation":{"op":"find","limit":50,"order":"newest"},"requireCompleteCoverage":false}
            """;
        var left = StructuredQueryCanonical.Write(StructuredQueryParser.Parse(terse).Query!);
        var right = StructuredQueryCanonical.Write(StructuredQueryParser.Parse(explicitForm).Query!);
        Assert.Equal(left, right);
        Assert.Equal(StructuredQueryCanonical.Fingerprint(left), StructuredQueryCanonical.Fingerprint(right));
        Assert.Matches("^[0-9a-f]{64}$", StructuredQueryCanonical.Fingerprint(left));
    }

    [Fact]
    public void APlateOrSubclassPredicateStatesItsImpliedVehicleClass()
    {
        var parsed = StructuredQueryParser.Parse("""
            {"contractVersion":"mavi-query-v1","unit":"track",
             "where":{"timeWindow":{"fromUtc":"2026-09-21T05:00:00Z","toUtc":"2026-09-21T07:00:00Z"},"plateText":{"text":"ab-12c"}},
             "operation":{"op":"count"}}
            """);
        Assert.Equal(Domain.Intelligence.ObjectClass.Vehicle, parsed.Query!.Where.ObjectClass);
        Assert.Equal("AB12C", parsed.Query.Where.Plate!.Text);
        Assert.Contains("\"objectClass\":\"Vehicle\"", StructuredQueryCanonical.Write(parsed.Query), StringComparison.Ordinal);
    }

    internal static JsonDocument Corpus() =>
        JsonDocument.Parse(File.ReadAllText(Path.Combine(CompletionDigestGoldenTests.FindRepositoryRoot(), CorpusPath)));
}
