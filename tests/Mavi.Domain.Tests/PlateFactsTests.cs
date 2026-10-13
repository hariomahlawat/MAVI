using Mavi.Domain.Common;
using Mavi.Domain.Plates;

namespace Mavi.Domain.Tests;

/// <summary>
/// The plate facts (ADR-013 implementation amendment 2026-10-13, items 12–15): a plate box inside its
/// crop, Read with a ranked kept-reading prefix and Unreadable with none, raw text kept verbatim beside
/// the platform's normalisation, Track outcomes that never turn Unavailable into "no plate", and Track
/// texts that are search acceleration only.
/// </summary>
public sealed class PlateFactsTests
{
    private static readonly Guid Analysis = Guid.CreateVersion7();
    private static readonly Guid Track = Guid.CreateVersion7();
    private static readonly Guid Source = Guid.CreateVersion7();

    private static PlateReadingValues Ok(int rank, string raw, double confidence, string normalised, string formatClass = "in-standard") =>
        new(rank, raw, 1 + raw.Count(character => character == '\n'), confidence, normalised, PlateNormalisationOutcome.Ok, null, formatClass);

    private static PlateObservation Observation(
        PlateObservationOutcome outcome,
        IReadOnlyList<PlateReadingValues> readings,
        int x = 70, int y = 120, int width = 64, int height = 16, int cropWidth = 212, int cropHeight = 168, int plateIndex = 0) =>
        PlateObservation.Create(Analysis, Track, Source, plateIndex, x, y, width, height, cropWidth, cropHeight, 0.91, outcome, readings);

    [Fact]
    public void AReadPlateKeepsItsRankedReadingsVerbatim()
    {
        var observation = Observation(PlateObservationOutcome.Read,
        [
            Ok(0, "KA 01 AB 1234", 0.88, "KA01AB1234"),
            Ok(1, "KA01AB1284", 0.61, "KA01AB1284"),
        ]);

        Assert.Equal(PlateObservationOutcome.Read, observation.Outcome);
        Assert.Equal(2, observation.Readings.Count);
        Assert.All(observation.Readings, reading => Assert.Equal(observation.Id, reading.PlateObservationId));
        Assert.Equal("KA 01 AB 1234", observation.Readings[0].RawText);
        Assert.Equal("KA01AB1234", observation.Readings[0].NormalisedText);
        Assert.Equal([0, 1], observation.Readings.Select(reading => reading.Rank));
    }

    [Fact]
    public void ATwoLineReadingDeclaresItsLines()
    {
        var observation = Observation(PlateObservationOutcome.Read, [Ok(0, "MH12\nDE 4321", 0.83, "MH12DE4321")]);
        Assert.Equal(2, observation.Readings[0].RawLineCount);
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read,
            [Ok(0, "MH12\nDE 4321", 0.83, "MH12DE4321") with { RawLineCount = 1 }]));
    }

    [Fact]
    public void ARejectedReadingKeepsItsRawTextButIsNeverSearchable()
    {
        var rejected = new PlateReadingValues(0, "का01", 1, 0.7, null, PlateNormalisationOutcome.Rejected, "non-alphanumeric", null);
        var observation = Observation(PlateObservationOutcome.Read, [rejected]);
        Assert.Null(observation.Readings[0].NormalisedText);
        Assert.Null(observation.Readings[0].FormatClass);
        Assert.Equal("का01", observation.Readings[0].RawText);
    }

    [Theory]
    [InlineData("KA01", PlateNormalisationOutcome.Rejected, "non-alphanumeric", null)]   // rejected with text
    [InlineData(null, PlateNormalisationOutcome.Ok, null, "in-standard")]               // ok without text
    [InlineData("ka01", PlateNormalisationOutcome.Ok, null, "other")]                   // not normalised
    [InlineData("KA01", PlateNormalisationOutcome.Ok, "empty", "other")]                // ok with a reason
    [InlineData("KA01", PlateNormalisationOutcome.Ok, null, null)]                      // ok without a class
    [InlineData("KA01", PlateNormalisationOutcome.Ok, null, "IN")]                      // unknown class
    [InlineData(null, PlateNormalisationOutcome.Rejected, null, null)]                  // rejected without a reason
    [InlineData(null, PlateNormalisationOutcome.Rejected, "too-long", null)]            // unknown reason
    public void TheNormalisationShapeIsExact(string? normalised, PlateNormalisationOutcome outcome, string? reason, string? formatClass)
    {
        var values = new PlateReadingValues(0, "KA01", 1, 0.7, normalised, outcome, reason, formatClass);
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read, [values]));
    }

    [Fact]
    public void AnUnreadablePlateHasNoReadingRows()
    {
        var observation = Observation(PlateObservationOutcome.Unreadable, []);
        Assert.Empty(observation.Readings);
        Assert.Throws<DomainValidationException>(() =>
            Observation(PlateObservationOutcome.Unreadable, [Ok(0, "KA0", 0.31, "KA0")]));
    }

    [Fact]
    public void AReadPlateNeedsRankZero()
    {
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read, []));
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read, [Ok(1, "KA01", 0.9, "KA01")]));
    }

    [Fact]
    public void RanksAreContiguousAndConfidenceNeverRises()
    {
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read,
            [Ok(0, "KA01", 0.9, "KA01"), Ok(2, "KA02", 0.8, "KA02")]));
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read,
            [Ok(0, "KA01", 0.6, "KA01"), Ok(1, "KA02", 0.8, "KA02")]));
        // Equal confidences are a tie, not a rise.
        Assert.Equal(2, Observation(PlateObservationOutcome.Read, [Ok(0, "KA01", 0.6, "KA01"), Ok(1, "KA02", 0.6, "KA02")]).Readings.Count);
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read,
            Enumerable.Range(0, 6).Select(rank => Ok(rank, "KA01", 0.9, "KA01")).ToList()));
    }

    [Theory]
    [InlineData(-1, 0, 10, 10, 100, 100)]
    [InlineData(0, -1, 10, 10, 100, 100)]
    [InlineData(0, 0, 0, 10, 100, 100)]
    [InlineData(0, 0, 10, 0, 100, 100)]
    [InlineData(91, 0, 10, 10, 100, 100)]
    [InlineData(0, 91, 10, 10, 100, 100)]
    [InlineData(0, 0, 10, 10, 0, 100)]
    [InlineData(0, 0, 10, 10, 4097, 100)]
    [InlineData(int.MaxValue, 0, 10, 10, 100, 100)]
    public void ThePlateBoxMustLieInsideItsCrop(int x, int y, int width, int height, int cropWidth, int cropHeight)
    {
        Assert.Throws<DomainValidationException>(() =>
            Observation(PlateObservationOutcome.Unreadable, [], x, y, width, height, cropWidth, cropHeight));
    }

    [Fact]
    public void ABoxMayTouchTheCropEdge()
    {
        var observation = Observation(PlateObservationOutcome.Unreadable, [], x: 90, y: 90, width: 10, height: 10, cropWidth: 100, cropHeight: 100);
        Assert.Equal(100, observation.BoxX + observation.BoxWidth);
    }

    [Theory]
    [InlineData(-1)]
    [InlineData(8)]
    public void ThePlateIndexIsBounded(int plateIndex)
    {
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Unreadable, [], plateIndex: plateIndex));
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(-0.01)]
    [InlineData(1.01)]
    [InlineData(double.PositiveInfinity)]
    public void ConfidencesAreFiniteProbabilities(double confidence)
    {
        Assert.Throws<DomainValidationException>(() =>
            PlateObservation.Create(Analysis, Track, Source, 0, 0, 0, 10, 10, 100, 100, confidence, PlateObservationOutcome.Unreadable, []));
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read, [Ok(0, "KA01", confidence, "KA01")]));
    }

    [Theory]
    [InlineData("")]
    [InlineData("123456789012345678901234567890123")]
    [InlineData("KA\u000001")]
    [InlineData("A\nB\nC")]
    public void RawTextIsBoundedAndStorable(string raw)
    {
        var values = new PlateReadingValues(0, raw, 1, 0.9, null, PlateNormalisationOutcome.Rejected, "empty", null);
        Assert.Throws<DomainValidationException>(() => Observation(PlateObservationOutcome.Read, [values]));
    }

    [Fact]
    public void AnAnalysedTrackWithoutPlatesIsNotUnavailable()
    {
        var outcome = PlateTrackOutcome.Analysed(Analysis, Track, plateObservationCount: 0, distinctTextCount: 0);
        Assert.Equal(PlateTrackOutcomeKind.Analysed, outcome.Outcome);
        Assert.Null(outcome.Reason);
    }

    [Fact]
    public void AnUnavailableTrackExplainsItselfAndHasNoPlates()
    {
        var outcome = PlateTrackOutcome.Unavailable(Analysis, Track, "evidence_integrity_failed");
        Assert.Equal(PlateTrackOutcomeKind.Unavailable, outcome.Outcome);
        Assert.Equal(0, outcome.PlateObservationCount);
        Assert.Throws<DomainValidationException>(() => PlateTrackOutcome.Unavailable(Analysis, Track, ""));
        Assert.Throws<DomainValidationException>(() => PlateTrackOutcome.Unavailable(Analysis, Track, "Network blip"));
    }

    [Theory]
    [InlineData(-1, 0)]
    [InlineData(33, 0)]
    [InlineData(1, 2)]
    [InlineData(2, -1)]
    public void TrackOutcomeCountsAreConsistent(int observations, int texts)
    {
        Assert.Throws<DomainValidationException>(() => PlateTrackOutcome.Analysed(Analysis, Track, observations, texts));
    }

    [Fact]
    public void ATrackTextIsANormalisedTextWithItsSupport()
    {
        var text = PlateTrackText.Create(Analysis, Track, "KA01AB1234", 2, 0.97, Guid.CreateVersion7());
        Assert.Equal("KA01AB1234", text.NormalisedText);
        Assert.Throws<DomainValidationException>(() => PlateTrackText.Create(Analysis, Track, "KA 01", 1, 0.9, Guid.CreateVersion7()));
        Assert.Throws<DomainValidationException>(() => PlateTrackText.Create(Analysis, Track, "KA01", 0, 0.9, Guid.CreateVersion7()));
        Assert.Throws<DomainValidationException>(() => PlateTrackText.Create(Analysis, Track, "KA01", 1, 0.9, Guid.Empty));
        Assert.Throws<DomainValidationException>(() =>
            PlateTrackText.Create(Analysis, Track, new string('A', 129), 1, 0.9, Guid.CreateVersion7()));
    }

    [Fact]
    public void AnActivationKeepsTheBytesItsIdentityPins()
    {
        var activation = PlateIdentityActivation.Create(new string('a', 64), "{}\n", "{\"p\":1}\n", "{\"s\":1}\n", DateTimeOffset.UnixEpoch);
        Assert.Equal("{\"p\":1}\n", activation.ParametersJson);
        Assert.Equal("{\"s\":1}\n", activation.SummaryPolicyJson);
        Assert.Throws<DomainValidationException>(() =>
            PlateIdentityActivation.Create(new string('A', 64), "{}\n", "{}", "{}", DateTimeOffset.UnixEpoch));
        Assert.Throws<DomainValidationException>(() =>
            PlateIdentityActivation.Create(new string('a', 64), "{}\n", "", "{}", DateTimeOffset.UnixEpoch));
    }

    [Fact]
    public void AnAttemptFailureNeedsACanonicalCode()
    {
        var failure = PlateAttemptFailure.Create(Analysis, 1, "plate_inference_failed", true, null, DateTimeOffset.UnixEpoch);
        Assert.Equal(1, failure.AttemptNumber);
        Assert.Throws<DomainValidationException>(() =>
            PlateAttemptFailure.Create(Analysis, 1, "Plate-Failed", true, null, DateTimeOffset.UnixEpoch));
        Assert.Throws<DomainValidationException>(() =>
            PlateAttemptFailure.Create(Analysis, 0, "plate_inference_failed", true, null, DateTimeOffset.UnixEpoch));
    }
}
