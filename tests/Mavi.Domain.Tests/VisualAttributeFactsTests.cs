using System.Security.Cryptography;
using Mavi.Domain.Common;
using Mavi.Domain.VisualAttributes;

namespace Mavi.Domain.Tests;

/// <summary>ADR-013 §12/§14 fact invariants and the S2b §9 failure-replay rule.</summary>
public sealed class VisualAttributeFactsTests
{
    private static readonly Guid Analysis = Guid.CreateVersion7();
    private static readonly Guid Track = Guid.CreateVersion7();
    private static readonly Guid Observation = Guid.CreateVersion7();

    [Fact]
    public void ObservedCarriesAValueAConfidenceAndItsEvidence()
    {
        var fact = VisualAttribute.Observed(Analysis, Track, "fixture-person-upper", "dark", 0.75, Observation);
        Assert.Equal(VisualAttributeOutcome.Observed, fact.Outcome);
        Assert.Equal("dark", fact.Value);
        Assert.Equal(0.75, fact.Confidence);
        Assert.Equal(Observation, fact.SupportingObservationId);
    }

    [Theory]
    [InlineData(-0.01)]
    [InlineData(1.01)]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    public void ObservedConfidenceIsBounded(double confidence)
    {
        Assert.Throws<DomainValidationException>(() =>
            VisualAttribute.Observed(Analysis, Track, "fixture-person-upper", "dark", confidence, Observation));
    }

    [Fact]
    public void ObservedNeedsSupportingEvidenceAndASchemaValue()
    {
        Assert.Throws<DomainValidationException>(() =>
            VisualAttribute.Observed(Analysis, Track, "fixture-person-upper", "dark", 0.5, Guid.Empty));
        Assert.Throws<DomainValidationException>(() =>
            VisualAttribute.Observed(Analysis, Track, "fixture-person-upper", "Dark Blue", 0.5, Observation));
    }

    [Fact]
    public void UnknownAssertsNothing()
    {
        var fact = VisualAttribute.Unknown(Analysis, Track, "fixture-person-upper");
        Assert.Equal(VisualAttributeOutcome.Unknown, fact.Outcome);
        Assert.Null(fact.Value);
        Assert.Null(fact.Confidence);
        Assert.Null(fact.SupportingObservationId);
    }

    [Fact]
    public void UnavailableAlwaysHasAReasonAndAnalysedNever()
    {
        Assert.Equal("evidence_missing", VisualAttributeTrackOutcome.Unavailable(Analysis, Track, "evidence_missing").Reason);
        Assert.Null(VisualAttributeTrackOutcome.Analysed(Analysis, Track).Reason);
        Assert.Throws<DomainValidationException>(() => VisualAttributeTrackOutcome.Unavailable(Analysis, Track, ""));
        Assert.Throws<DomainValidationException>(() => VisualAttributeTrackOutcome.Unavailable(Analysis, Track, "Evidence Missing"));
    }

    [Fact]
    public void AFailureReplayMatchesOnlyTheRecordedTransition()
    {
        var policy = new VisualAttributeLeasePolicy(TimeSpan.FromMinutes(2), TimeSpan.FromMinutes(2), 3, TimeSpan.FromHours(1));
        var start = new DateTimeOffset(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);
        var unit = VisualAttributeAnalysis.Queue(Guid.CreateVersion7(), VisualAttributeAnalysisTests.Identity(), start);
        unit.Claim("attributes-01", SHA256.HashData(new byte[32]), start, policy);
        unit.FailAttempt("attributes-01", true, 1, "visual_attribute_inference_failed", true, "oom", start.AddSeconds(5), policy);

        Assert.True(unit.IsRecordedFailureReplay("attributes-01", true, 1, "visual_attribute_inference_failed", "oom"));
        Assert.Equal(VisualAttributeFailOutcome.Requeued, unit.LastFailedOutcome);
        Assert.False(unit.IsRecordedFailureReplay("attributes-01", false, 1, "visual_attribute_inference_failed", "oom"));
        Assert.False(unit.IsRecordedFailureReplay("attributes-01", true, 1, "visual_attribute_output_invalid", "oom"));
        Assert.False(unit.IsRecordedFailureReplay("attributes-01", true, 1, "visual_attribute_inference_failed", null));
        Assert.False(unit.IsRecordedFailureReplay("attributes-02", true, 1, "visual_attribute_inference_failed", "oom"));
        Assert.False(unit.IsRecordedFailureReplay("attributes-01", true, 2, "visual_attribute_inference_failed", "oom"));

        // A later attempt owns the unit now; the replay of attempt 1 still matches its own
        // transition and cannot be mistaken for anything of attempt 2.
        unit.Claim("attributes-02", SHA256.HashData(new byte[] { 9 }), start.AddSeconds(6), policy);
        Assert.True(unit.IsRecordedFailureReplay("attributes-01", true, 1, "visual_attribute_inference_failed", "oom"));
        Assert.Equal(2, unit.AttemptCount);
    }

    [Fact]
    public void AnActivationPinsAFingerprint()
    {
        Assert.Throws<DomainValidationException>(() => VisualAttributeIdentityActivation.Create("x", "{}", DateTimeOffset.UnixEpoch));
        var activation = VisualAttributeIdentityActivation.Create(new string('a', 64), "{}", DateTimeOffset.UnixEpoch);
        Assert.Equal(new string('a', 64), activation.Fingerprint);
    }
}
