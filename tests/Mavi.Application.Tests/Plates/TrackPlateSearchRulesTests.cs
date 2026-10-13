using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Plates;
using Mavi.Domain.Plates;

namespace Mavi.Application.Tests.Plates;

/// <summary>
/// The plate predicate's grammar and rules (Stage 4 PR-4, plan §5.4): the query text is the frozen
/// <c>mavi-plate-normalisation-v1</c> output of 3–15 <c>[A-Z0-9]</c> characters, matching is literal, and
/// coverage and agreement are derived by fixed rules.
/// </summary>
public sealed class TrackPlateSearchRulesTests
{
    // --- Grammar ---------------------------------------------------------------------------

    [Fact]
    public void NoPlateKeysIsNoPredicate()
    {
        Assert.True(TrackPlateQueryRules.TryParse(null, null, out var query));
        Assert.Null(query);
    }

    [Fact]
    public void PlateMatchAloneIsRefused()
    {
        Assert.False(TrackPlateQueryRules.TryParse(null, "exact", out _));
        Assert.False(TrackPlateQueryRules.TryParse(null, "contains", out _));
    }

    [Theory]
    [InlineData(null, TrackPlateMatch.Contains)]
    [InlineData("contains", TrackPlateMatch.Contains)]
    [InlineData("prefix", TrackPlateMatch.Prefix)]
    [InlineData("exact", TrackPlateMatch.Exact)]
    public void TheMatchModeDefaultsToContains(string? raw, TrackPlateMatch expected)
    {
        Assert.True(TrackPlateQueryRules.TryParse("KA01", raw, out var query));
        Assert.Equal(new TrackPlateQuery("KA01", expected), query);
    }

    [Theory]
    [InlineData("Contains")]
    [InlineData("EXACT")]
    [InlineData("starts")]
    [InlineData("fuzzy")]
    [InlineData("similar")]
    public void AnUnknownMatchModeIsRefused(string raw) =>
        Assert.False(TrackPlateQueryRules.TryParse("KA01", raw, out _));

    [Theory]
    // Separators go, case folds, NFKC applies: the same function the platform applies to readings.
    [InlineData("ka 01", "KA01")]
    [InlineData("KA-01-AB", "KA01AB")]
    [InlineData("ka.01/ab:12·34", "KA01AB1234")]
    [InlineData("KA01\nAB1234", "KA01AB1234")]
    [InlineData("ＫＡ０１", "KA01")]
    // No confusable substitution: O stays O and 0 stays 0, I stays I and 1 stays 1.
    [InlineData("KAO1", "KAO1")]
    [InlineData("KA0I", "KA0I")]
    [InlineData("B8S5Z2", "B8S5Z2")]
    // The bounds: exactly 3 and exactly 15 normalised characters.
    [InlineData("K-A-0", "KA0")]
    [InlineData("ABCDEFGHIJ12345", "ABCDEFGHIJ12345")]
    public void TheQueryTextIsTheFrozenNormalisation(string raw, string expected)
    {
        Assert.True(TrackPlateQueryRules.TryParse(raw, null, out var query));
        Assert.Equal(expected, query!.Text);
        Assert.Equal(PlateNormalisation.Normalise(raw).Normalised, query.Text);
    }

    [Theory]
    [InlineData("KA")]
    [InlineData("K-A")]
    [InlineData("ABCDEFGHIJ123456")]
    [InlineData("- . /")]
    [InlineData("KA_01")]
    [InlineData("KA01*")]
    [InlineData("KA%01")]
    [InlineData("KA01क")]
    [InlineData("KA\ud80001")]
    public void ATextOutsideThreeToFifteenAlphanumericsIsRefused(string raw) =>
        Assert.False(TrackPlateQueryRules.TryParse(raw, null, out _));

    [Fact]
    public void ARawTextOverItsBoundIsRefusedBeforeNormalisation()
    {
        var spaced = "K A 0 1 " + new string(' ', 60);
        Assert.True(spaced.Length > 64);
        Assert.False(TrackPlateQueryRules.TryParse(spaced, null, out _));
        Assert.True(TrackPlateQueryRules.TryParse(spaced[..64], null, out _));
    }

    [Fact]
    public void EveryNormalisationVectorParsesExactlyWhenItIsAnOkTextOfThreeToFifteen()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            CompletionDigestGoldenTests.FindRepositoryRoot(), "contracts/test-vectors/plate-normalisation-v1.json")));
        var vectors = document.RootElement.GetProperty("vectors").EnumerateArray().ToList();
        Assert.NotEmpty(vectors);
        foreach (var vector in vectors)
        {
            var raw = vector.GetProperty("raw").GetString()!;
            var normalised = vector.GetProperty("normalised").ValueKind == JsonValueKind.String
                ? vector.GetProperty("normalised").GetString()
                : null;
            var searchable = normalised is { Length: >= 3 and <= 15 } && raw.Length <= 64;

            Assert.Equal(searchable, TrackPlateQueryRules.TryParse(raw, null, out var query));
            if (searchable)
                Assert.Equal(normalised, query!.Text);
        }
    }

    // --- Literal matching ------------------------------------------------------------------

    [Theory]
    [InlineData("KA01AB1234", "KA01", TrackPlateMatch.Contains, true)]
    [InlineData("KA01AB1234", "AB12", TrackPlateMatch.Contains, true)]
    [InlineData("KA01AB1234", "1234", TrackPlateMatch.Contains, true)]
    [InlineData("KA01AB1234", "KAO1", TrackPlateMatch.Contains, false)]
    [InlineData("KA01AB1234", "KA01", TrackPlateMatch.Prefix, true)]
    [InlineData("KA01AB1234", "AB12", TrackPlateMatch.Prefix, false)]
    [InlineData("KA01AB1234", "KA01AB1234", TrackPlateMatch.Exact, true)]
    [InlineData("KA01AB1234", "KA01AB123", TrackPlateMatch.Exact, false)]
    [InlineData("KA01AB123", "KA01AB1234", TrackPlateMatch.Contains, false)]
    public void MatchingIsLiteral(string stored, string text, TrackPlateMatch match, bool expected) =>
        Assert.Equal(expected, TrackPlateQueryRules.Matches(new TrackPlateQuery(text, match), stored));

    [Fact]
    public void ThePatternsCarryNoMetacharacterBeyondTheAnchor()
    {
        Assert.Equal("%KA01%", TrackPlateQueryRules.LikePattern(new TrackPlateQuery("KA01", TrackPlateMatch.Contains)));
        Assert.Equal("KA01%", TrackPlateQueryRules.LikePattern(new TrackPlateQuery("KA01", TrackPlateMatch.Prefix)));
        Assert.Throws<ArgumentException>(() => TrackPlateQueryRules.LikePattern(new TrackPlateQuery("KA01", TrackPlateMatch.Exact)));
    }

    // --- Agreement -------------------------------------------------------------------------

    [Theory]
    [InlineData(new int[0], "none")]
    [InlineData(new[] { 1 }, "single")]
    [InlineData(new[] { 2 }, "consistent")]
    [InlineData(new[] { 4 }, "consistent")]
    [InlineData(new[] { 3, 1 }, "conflicting")]
    [InlineData(new[] { 1, 1, 1 }, "conflicting")]
    public void AgreementIsDerivedFromTheTexts(int[] supports, string expected) =>
        Assert.Equal(expected, PlateAgreementRule.Derive(supports));

    // --- Coverage as of a snapshot -----------------------------------------------------------

    private const string Preferred = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    private const string Obsolete = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    private static readonly Guid Run = Guid.CreateVersion7();

    private static PlateCoverageAnalysis Analysis(string fingerprint, PlateAnalysisStatus status, long? sequence = null) =>
        new(Guid.CreateVersion7(), fingerprint, status, sequence);

    [Fact]
    public void WithoutAPreferredIdentityEveryRunIsNotConfigured() =>
        Assert.Equal(PlateReadinessState.NotConfigured,
            PlateCoverageRule.Classify(Run, null, [Analysis(Preferred, PlateAnalysisStatus.Completed, 5)], 10));

    [Fact]
    public void APublishedAnalysisOfThePinnedIdentityIsReadyEvenWhenSuperseded()
    {
        Assert.Equal(PlateReadinessState.Ready,
            PlateCoverageRule.Classify(Run, Preferred, [Analysis(Preferred, PlateAnalysisStatus.Completed, 5)], 10));
        Assert.Equal(PlateReadinessState.Ready,
            PlateCoverageRule.Classify(Run, Preferred, [Analysis(Preferred, PlateAnalysisStatus.Superseded, 5)], 10));
    }

    [Fact]
    public void AnAnalysisPublishedAfterTheSnapshotIsStillPending() =>
        Assert.Equal(PlateReadinessState.Pending,
            PlateCoverageRule.Classify(Run, Preferred, [Analysis(Preferred, PlateAnalysisStatus.Completed, 11)], 10));

    [Fact]
    public void QueuedRunningMissingFailedAndObsoleteFollowTheReadinessRule()
    {
        Assert.Equal(PlateReadinessState.Pending, PlateCoverageRule.Classify(Run, Preferred, [], 10));
        Assert.Equal(PlateReadinessState.Pending,
            PlateCoverageRule.Classify(Run, Preferred, [Analysis(Preferred, PlateAnalysisStatus.Queued)], 10));
        Assert.Equal(PlateReadinessState.Pending,
            PlateCoverageRule.Classify(Run, Preferred, [Analysis(Preferred, PlateAnalysisStatus.Running)], 10));
        Assert.Equal(PlateReadinessState.Failed,
            PlateCoverageRule.Classify(Run, Preferred, [Analysis(Preferred, PlateAnalysisStatus.Failed)], 10));
        Assert.Equal(PlateReadinessState.Stale,
            PlateCoverageRule.Classify(Run, Preferred, [Analysis(Obsolete, PlateAnalysisStatus.Completed, 3)], 10));
        // An obsolete identity's facts make the run Stale whatever the preferred unit is doing (PR-3's rule).
        Assert.Equal(PlateReadinessState.Stale,
            PlateCoverageRule.Classify(Run, Preferred,
                [Analysis(Obsolete, PlateAnalysisStatus.Superseded, 3), Analysis(Preferred, PlateAnalysisStatus.Failed)], 10));
        // ...but obsolete facts published after the snapshot did not yet exist for it.
        Assert.Equal(PlateReadinessState.Pending,
            PlateCoverageRule.Classify(Run, Preferred, [Analysis(Obsolete, PlateAnalysisStatus.Completed, 12)], 10));
    }
}
