using System.Text.Json;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;

namespace Mavi.Application.Tests.SceneAnalytics;

public sealed class SceneAnalysisEngineTests
{
    private static readonly SceneAnalyticsParameters Parameters = SceneAnalyticsParameters.Default;

    private static readonly JsonSerializerOptions CanonicalOptions = new() { WriteIndented = false };

    // Composition
    [Fact]
    public void WalkThroughTheSceneProducesVisitsAndCrossings()
    {
        var revision = SceneFixture.Revision(
            zones: [SceneFixture.CentreZone()],
            lines: [SceneFixture.HorizontalLine()]);

        var result = SceneAnalysisEngine.Analyse(
            SceneFixture.Line(21, 100, (0.5, 0.05), (0.5, 0.95)),
            revision,
            ObjectClass.Person,
            Parameters);

        Assert.Equal(AnalysisReferencePoint.BoundingBoxCentre, result.ReferencePoint);
        Assert.Equal(21, result.SampleCount);
        Assert.Equal(0, result.GapCount);
        Assert.Single(result.ZoneVisits);
        Assert.Single(result.ZoneSummaries);
        Assert.Single(result.LineCrossings);
        Assert.Equal(AnalysisHeading.South, result.Motion.Heading);
        Assert.True(result.Motion.PathLengthNormalised > 0);
    }

    [Fact]
    public void DisabledGeometryIsNotEvaluatedAtAll()
    {
        var revision = SceneFixture.Revision(
            zones: [SceneFixture.CentreZone(enabled: false)],
            lines: [SceneFixture.HorizontalLine(enabled: false)]);

        var result = SceneAnalysisEngine.Analyse(
            SceneFixture.Line(21, 100, (0.5, 0.05), (0.5, 0.95)),
            revision,
            ObjectClass.Person,
            Parameters);

        Assert.Empty(result.ZoneVisits);
        Assert.Empty(result.ZoneSummaries);
        Assert.Empty(result.LineCrossings);
    }

    [Fact]
    public void ZoneNeverEnteredStillGetsASummary()
    {
        var revision = SceneFixture.Revision(zones: [SceneFixture.CentreZone()]);

        var result = SceneAnalysisEngine.Analyse(
            SceneFixture.Line(11, 100, (0.05, 0.05), (0.2, 0.2)),
            revision,
            ObjectClass.Person,
            Parameters);

        var summary = Assert.Single(result.ZoneSummaries);
        Assert.Equal(0, summary.VisitCount);
        Assert.Empty(result.ZoneVisits);
    }

    [Fact]
    public void PathLengthIgnoresWhatHappenedDuringALongGap()
    {
        var revision = SceneFixture.Revision(zones: [SceneFixture.CentreZone()]);
        var samples = SceneFixture.Concat(
            SceneFixture.Line(3, 100, (0.1, 0.5), (0.2, 0.5)),
            SceneFixture.Line(3, 100, (0.8, 0.5), (0.9, 0.5), startMs: 6_000));

        var result = SceneAnalysisEngine.Analyse(samples, revision, ObjectClass.Person, Parameters);

        // Two observed runs of 0.1 each; the 0.6 jump across the gap is not evidence.
        Assert.Equal(0.2, result.Motion.PathLengthNormalised, 6);
        Assert.Equal(1, result.GapCount);
        Assert.Equal(5_800, result.GapTotalMs);
    }

    // Determinism
    [Fact]
    public void RepeatedAnalysisOfTheSameInputsIsByteIdentical()
    {
        var revision = SceneFixture.Revision(
            zones: [SceneFixture.CentreZone(), SceneFixture.CentreZone("Second")],
            lines: [SceneFixture.HorizontalLine()]);
        var samples = SceneFixture.Line(41, 100, (0.5, 0.05), (0.5, 0.95));

        var first = Canonical(SceneAnalysisEngine.Analyse(samples, revision, ObjectClass.Person, Parameters));
        var second = Canonical(SceneAnalysisEngine.Analyse(samples, revision, ObjectClass.Person, Parameters));

        Assert.Equal(first, second);
    }

    [Fact]
    public void ResultsAreOrderedIndependentlyOfTheOrderTheGeometryArrivedIn()
    {
        var samples = SceneFixture.Line(41, 100, (0.5, 0.05), (0.5, 0.95));
        var revision = SceneFixture.Revision(
            zones: [SceneFixture.CentreZone("A"), SceneFixture.CentreZone("B")],
            lines: [SceneFixture.HorizontalLine()]);

        var result = SceneAnalysisEngine.Analyse(samples, revision, ObjectClass.Person, Parameters);

        Assert.Equal(
            result.ZoneSummaries.Select(summary => summary.ZoneId).Order(),
            result.ZoneSummaries.Select(summary => summary.ZoneId));
        Assert.Equal(
            result.ZoneVisits.Select(visit => visit.EntryOffsetMs).Order(),
            result.ZoneVisits.Select(visit => visit.EntryOffsetMs));
        Assert.Equal(
            result.LineCrossings.Select(crossing => crossing.OffsetMs).Order(),
            result.LineCrossings.Select(crossing => crossing.OffsetMs));
    }

    [Fact]
    public void EngineNeverLooksOutsideTheSampledRange()
    {
        var revision = SceneFixture.Revision(
            zones: [SceneFixture.CentreZone()],
            lines: [SceneFixture.HorizontalLine()]);
        var samples = SceneFixture.Line(21, 100, (0.5, 0.05), (0.5, 0.95));

        var result = SceneAnalysisEngine.Analyse(samples, revision, ObjectClass.Person, Parameters);

        var first = samples[0].OffsetMs;
        var last = samples[^1].OffsetMs;
        Assert.All(result.ZoneVisits, visit =>
        {
            Assert.InRange(visit.EntryOffsetMs, first, last);
            Assert.InRange(visit.ExitOffsetMs, visit.EntryOffsetMs, last);
        });
        Assert.All(result.LineCrossings, crossing => Assert.InRange(crossing.OffsetMs, first, last));
    }

    // Algorithm identity
    [Fact]
    public void AlgorithmVersionIsTheFrozenDomainString() =>
        Assert.Equal("scene-analytics-v1", SceneAnalyticsAlgorithm.Version);

    [Fact]
    public void CanonicalParameterJsonIsStable() =>
        Assert.Equal(
            """
            {"algorithmVersion":"scene-analytics-v1","confirmationSamples":3,"epsilon":0.005,"headingMinimumDisplacement":0.02,"loiteringDefaultSeconds":120,"maximumGapMs":2000,"personStationaryDisplacement":0.015,"personStationaryMinimumMs":5000,"referencePoint":"bbox-centre","repeatSuppressionMs":1000,"smoothingWindowSamples":5,"stationaryWindowMs":3000,"vehicleStationaryDisplacement":0.01,"vehicleStationaryMinimumMs":10000}
            """.Trim(),
            Parameters.ToCanonicalJson());

    [Fact]
    public void ParameterDigestIsStableAndLowercaseHexadecimal()
    {
        var digest = Parameters.ParametersSha256();

        Assert.Equal(64, digest.Length);
        Assert.Equal(digest.ToLowerInvariant(), digest);
        Assert.Equal(digest, Parameters.ParametersSha256());
    }

    [Fact]
    public void ChangingAnyParameterChangesTheDigest()
    {
        var altered = Parameters with { Epsilon = 0.006 };

        Assert.NotEqual(Parameters.ParametersSha256(), altered.ParametersSha256());
    }

    [Fact]
    public void ParameterDigestDoesNotDependOnTheCurrentCulture()
    {
        // A culture that writes 0,005 for 0.005 would silently change every digest.
        var original = System.Globalization.CultureInfo.CurrentCulture;
        var expectedJson = Parameters.ToCanonicalJson();
        var expectedDigest = Parameters.ParametersSha256();
        try
        {
            System.Globalization.CultureInfo.CurrentCulture =
                new System.Globalization.CultureInfo("de-DE");
            Assert.Equal(expectedJson, Parameters.ToCanonicalJson());
            Assert.Equal(expectedDigest, Parameters.ParametersSha256());
        }
        finally
        {
            System.Globalization.CultureInfo.CurrentCulture = original;
        }
    }

    // Vocabularies shared with the transport contract
    [Fact]
    public void DomainAndContractSceneRulesAgree()
    {
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.UnattributedDevelopmentActor,
            SceneRules.UnattributedDevelopmentActor);
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.MinimumZoneVertices,
            SceneRules.MinimumZoneVertices);
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.MaximumZoneVertices,
            SceneRules.MaximumZoneVertices);
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.MaximumZonesPerRevision,
            SceneRules.MaximumZonesPerRevision);
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.MaximumTripLinesPerRevision,
            SceneRules.MaximumTripLinesPerRevision);
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.MaximumNameLength,
            SceneRules.MaximumNameLength);
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.MaximumDirectionLabelLength,
            SceneRules.MaximumDirectionLabelLength);
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.MaximumNoteLength,
            SceneRules.MaximumNoteLength);
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.CoordinateDecimals,
            Mavi.Domain.Scene.Geometry.NormalizedPoint.Decimals);
    }

    [Fact]
    public void EveryContractZoneKindIsADomainZoneKind()
    {
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.ZoneKindValues.Order(),
            Enum.GetNames<SceneZoneKind>().Order());
        Assert.Equal(
            Mavi.Contracts.Api.Scene.SceneContractRules.DefaultZoneKind,
            SceneZoneKind.General.ToString());
    }

    // Helpers
    private static string Canonical(TrackAnalysisResult result) =>
        JsonSerializer.Serialize(result, CanonicalOptions);
}
