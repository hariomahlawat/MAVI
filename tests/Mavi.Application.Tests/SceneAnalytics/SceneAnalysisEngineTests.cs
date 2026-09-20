using System.Text.Json;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;

namespace Mavi.Application.Tests.SceneAnalytics;

public sealed class SceneAnalysisEngineTests
{
    private static readonly SceneAnalyticsParameters Parameters = SceneAnalyticsParameters.Default;

    private static readonly JsonSerializerOptions CanonicalOptions = new() { WriteIndented = false };

    private static readonly JsonSerializerOptions GoldenOptions = new() { WriteIndented = true };

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
    public void ScriptedWalkMatchesTheCommittedGoldenFacts()
    {
        // The expected facts are committed, not computed here, so a change to
        // rounding, to the median's even-count rule, to the ordering or to any
        // threshold shows up as a diff rather than as silence. The scripted path
        // enters a zone, stands still inside it long enough to loiter, leaves across
        // the trip line, and is interrupted by a gap longer than the bridging limit.
        var expected = File.ReadAllText(GoldenFixturePath).ReplaceLineEndings("\n").Trim();

        var actual = GoldenReport();

        Assert.Equal(expected, actual);
    }

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

    private static string GoldenFixturePath =>
        TrajectoryDecoderTests.FixturePath("scripted-walk-expected-facts.json");

    /// <summary>
    /// The scripted scenario and its facts, rendered as canonical JSON.
    /// </summary>
    /// <remarks>
    /// Zone and trip line identities are server-issued and differ on every run, so
    /// the report names each one by the operator's own name instead. Everything the
    /// algorithm actually decides, including ordering, is compared literally.
    /// </remarks>
    internal static string GoldenReport()
    {
        var revision = SceneFixture.Revision(
            zones: [SceneFixture.CentreZone("Courtyard", loiteringThresholdSeconds: 5)],
            lines: [SceneFixture.HorizontalLine("Kerb")]);
        var result = SceneAnalysisEngine.Analyse(
            ScriptedWalk(),
            revision,
            ObjectClass.Person,
            Parameters);

        var zoneNames = revision.Zones.ToDictionary(zone => zone.ZoneId, zone => zone.Name);
        var lineNames = revision.TripLines.ToDictionary(line => line.LineId, line => line.Name);

        var report = new
        {
            algorithmVersion = SceneAnalyticsAlgorithm.Version,
            parametersSha256 = Parameters.ParametersSha256(),
            referencePoint = result.ReferencePoint,
            sampleCount = result.SampleCount,
            gapCount = result.GapCount,
            gapTotalMs = result.GapTotalMs,
            zoneVisits = result.ZoneVisits.Select(visit => new
            {
                zone = zoneNames[visit.ZoneId],
                visitIndex = visit.VisitIndex,
                entryOffsetMs = visit.EntryOffsetMs,
                exitOffsetMs = visit.ExitOffsetMs,
                dwellMs = visit.DwellMs,
                beganInside = visit.BeganInside,
                endedInside = visit.EndedInside,
                closedByGap = visit.ClosedByGap,
                entryHeading = visit.EntryHeading,
                exitHeading = visit.ExitHeading,
            }),
            zoneSummaries = result.ZoneSummaries.Select(summary => new
            {
                zone = zoneNames[summary.ZoneId],
                visitCount = summary.VisitCount,
                totalDwellMs = summary.TotalDwellMs,
                firstEntryOffsetMs = summary.FirstEntryOffsetMs,
                lastExitOffsetMs = summary.LastExitOffsetMs,
                loitering = summary.Loitering,
                loiteringThresholdSeconds = summary.LoiteringThresholdSeconds,
                loiteringDwellMs = summary.LoiteringDwellMs,
                loiteringVisitIndexes = summary.LoiteringVisitIndexes,
            }),
            lineCrossings = result.LineCrossings.Select(crossing => new
            {
                line = lineNames[crossing.LineId],
                crossingIndex = crossing.CrossingIndex,
                offsetMs = crossing.OffsetMs,
                direction = crossing.Direction,
                x = crossing.Point.X,
                y = crossing.Point.Y,
            }),
            motion = new
            {
                heading = result.Motion.Heading,
                pathLengthNormalised = result.Motion.PathLengthNormalised,
                meanDisplacementRateNormalisedPerSecond =
                    result.Motion.MeanDisplacementRateNormalisedPerSecond,
                longestStationaryMs = result.Motion.LongestStationaryMs,
                totalStationaryMs = result.Motion.TotalStationaryMs,
                stationaryIntervals = result.Motion.StationaryIntervals.Select(interval => new
                {
                    startOffsetMs = interval.StartOffsetMs,
                    endOffsetMs = interval.EndOffsetMs,
                }),
                stationaryZones = result.Motion.StationaryZoneIds.Select(id => zoneNames[id]),
            },
        };

        return JsonSerializer.Serialize(report, GoldenOptions);
    }

    /// <summary>
    /// Walks in from the top of the frame, stands still inside the zone above the
    /// trip line for eight seconds, vanishes for six, then returns and leaves
    /// downwards across both the line and the far edge of the zone.
    /// </summary>
    private static IReadOnlyList<TrajectorySample> ScriptedWalk() => SceneFixture.Concat(
        SceneFixture.Line(7, 100, (0.5, 0.10), (0.5, 0.40)),
        SceneFixture.Held(41, 200, (0.5, 0.40), startMs: 700),
        SceneFixture.Line(11, 100, (0.5, 0.40), (0.5, 0.90), startMs: 15_000));
}
