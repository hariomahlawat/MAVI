using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Tracks;

namespace Mavi.Application.Tests;

/// <summary>
/// The analytic query grammar frozen in plan §S: which keys make a query
/// analytics-dependent, which depend on which, and what two equal queries look like.
/// </summary>
public sealed class TrackAnalyticsQueryRulesTests
{
    private static readonly Guid Revision = Guid.Parse("0199a1f0-0000-7000-8000-00000000b001");
    private static readonly Guid Zone = Guid.Parse("0199a1f0-0000-7000-8000-00000000d001");
    private static readonly Guid Line = Guid.Parse("0199a1f0-0000-7000-8000-00000000e001");

    private static TrackAnalyticsQuery Empty => TrackAnalyticsQuery.Empty;

    [Fact]
    public void TheCoverageFlagAloneIsNotAnAnalyticQuery()
    {
        var partial = Empty with { RequireCompleteCoverage = false };
        var complete = Empty with { RequireCompleteCoverage = true };

        Assert.False(partial.HasAnalyticsDependentKey);
        Assert.False(complete.HasAnalyticsDependentKey);
        Assert.False(TrackAnalyticsQueryRules.IsValid(partial));
        Assert.False(TrackAnalyticsQueryRules.IsValid(complete));
    }

    [Fact]
    public void EveryDependentKeyStandsAloneWhereThePlanSaysItMay()
    {
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { SceneRevisionId = Revision }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { ZoneId = Zone }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { LineId = Line }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { MotionDirection = "NE" }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { MinStationaryMs = 0 }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { Loitering = true }));
    }

    [Fact]
    public void ZoneRelationAndMinimumDwellRequireAZone()
    {
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { ZoneRelation = TrackZoneRelation.Entered }));
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { MinDwellMs = 1_000 }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { ZoneId = Zone, ZoneRelation = TrackZoneRelation.Exited, MinDwellMs = 1_000 }));
    }

    [Fact]
    public void CrossingDirectionRequiresALine()
    {
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { CrossingDirection = TrackCrossingDirection.AToB }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { LineId = Line, CrossingDirection = TrackCrossingDirection.BToA }));
    }

    [Fact]
    public void AlgorithmVersionRequiresAnExplicitRevisionAndTheFrozenShape()
    {
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { AnalyticsAlgorithmVersion = "scene-analytics-v1" }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { SceneRevisionId = Revision, AnalyticsAlgorithmVersion = "scene-analytics-v1" }));
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { SceneRevisionId = Revision, AnalyticsAlgorithmVersion = "v1" }));
    }

    [Theory]
    [InlineData("scene-analytics-v1", true)]
    [InlineData("scene-analytics-v12", true)]
    [InlineData("scene-analytics-v", false)]
    [InlineData("scene-analytics-v0", false)]
    [InlineData("scene-analytics-v01", false)]
    [InlineData("scene-analytics-v1 ", false)]
    [InlineData("Scene-Analytics-v1", false)]
    [InlineData("scene-analytics-v12345", false)]
    [InlineData("", false)]
    public void AlgorithmVersionShapeIsClosed(string value, bool expected) =>
        Assert.Equal(expected, TrackSearchContractRules.IsAlgorithmVersion(value));

    [Fact]
    public void LoiteringMayCombineWithAZoneOrStandAlone()
    {
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { Loitering = true }));
        Assert.True(TrackAnalyticsQueryRules.IsValid(Empty with { Loitering = true, ZoneId = Zone }));
    }

    [Fact]
    public void NegativeDurationsAndEmptyIdentifiersAreRejected()
    {
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { ZoneId = Zone, MinDwellMs = -1 }));
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { MinStationaryMs = -1 }));
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { ZoneId = Guid.Empty }));
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { LineId = Guid.Empty }));
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { SceneRevisionId = Guid.Empty }));
    }

    [Fact]
    public void MotionDirectionExcludesTheEngineNoneHeading()
    {
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { MotionDirection = "None" }));
        Assert.False(TrackAnalyticsQueryRules.IsValid(Empty with { MotionDirection = "n" }));
        Assert.Equal(8, TrackSearchContractRules.MotionDirectionValues.Count);
        Assert.DoesNotContain("None", TrackSearchContractRules.MotionDirectionValues);
    }

    [Fact]
    public void AnOmittedRelationCanonicalisesToDwelledOnlyWhenAZoneIsNamed()
    {
        var omitted = TrackAnalyticsQueryRules.Canonicalise(Empty with { ZoneId = Zone });
        var explicitDwelled = TrackAnalyticsQueryRules.Canonicalise(Empty with { ZoneId = Zone, ZoneRelation = TrackZoneRelation.Dwelled });
        var noZone = TrackAnalyticsQueryRules.Canonicalise(Empty with { Loitering = true });

        Assert.Equal(explicitDwelled, omitted);
        Assert.Equal(TrackZoneRelation.Dwelled, omitted.ZoneRelation);
        Assert.Null(noZone.ZoneRelation);
    }

    [Fact]
    public void WireDirectionsMapToThePersistedVocabularyAndBack()
    {
        Assert.True(TrackAnalyticsQueryRules.TryParseCrossingDirection("aToB", out var aToB));
        Assert.True(TrackAnalyticsQueryRules.TryParseCrossingDirection("bToA", out var bToA));
        Assert.False(TrackAnalyticsQueryRules.TryParseCrossingDirection("AToB", out _));
        Assert.False(TrackAnalyticsQueryRules.TryParseCrossingDirection("atob", out _));

        Assert.Equal("AToB", TrackAnalyticsQueryRules.ToPersisted(aToB));
        Assert.Equal("BToA", TrackAnalyticsQueryRules.ToPersisted(bToA));
        Assert.Equal("aToB", TrackAnalyticsQueryRules.PersistedDirectionToWire("AToB"));
        Assert.Equal("bToA", TrackAnalyticsQueryRules.PersistedDirectionToWire("BToA"));
        Assert.Equal(["aToB", "bToA"], TrackSearchContractRules.CrossingDirectionValues);
    }

    [Fact]
    public void ZoneRelationsRoundTripTheWireVocabulary()
    {
        foreach (var value in TrackSearchContractRules.ZoneRelationValues)
        {
            Assert.True(TrackAnalyticsQueryRules.TryParseZoneRelation(value, out var relation));
            Assert.Equal(value, TrackAnalyticsQueryRules.ToWire(relation));
        }

        Assert.False(TrackAnalyticsQueryRules.TryParseZoneRelation("Dwelled", out _));
        Assert.Equal("dwelled", TrackSearchContractRules.DefaultZoneRelation);
    }

    [Fact]
    public void TheDependentKeySetIsExactlyTheFrozenTen()
    {
        Assert.Equal(
            [
                "sceneRevisionId", "analyticsAlgorithmVersion", "zoneId", "zoneRelation", "minDwellMs",
                "lineId", "crossingDirection", "motionDirection", "minStationaryMs", "loitering",
            ],
            TrackSearchContractRules.AnalyticsDependentKeys);
        Assert.Equal(11, TrackSearchContractRules.AnalyticsQueryKeys.Count);
        Assert.Contains("analyticsCoverage", TrackSearchContractRules.AnalyticsQueryKeys);
        Assert.False(TrackSearchContractRules.IsAnalyticsDependentKey("analyticsCoverage"));
    }
}
