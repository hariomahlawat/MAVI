using System.Security.Cryptography;
using Mavi.Domain.Common;
using Mavi.Domain.Plates;

namespace Mavi.Domain.Tests;

/// <summary>
/// The PlateAnalysis lifecycle: attempt consumed at claim, VisionJob-style expiry for lease-scoped
/// operations, ownership fencing (not wall-clock) for Phase C publication, retryable versus terminal
/// failure, and an absolute deadline anchored at the first claim. Ported scenario for scenario from
/// <c>VisualAttributeAnalysisTests</c>: ADR-013 implementation amendment 2026-10-13, item 11 duplicates
/// that state machine rather than abstracting it, so the same scenarios pin both.
/// </summary>
public sealed class PlateAnalysisTests
{
    private static readonly DateTimeOffset T0 = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);
    private static readonly PlateLeasePolicy Policy = new(
        LeaseDuration: TimeSpan.FromMinutes(2),
        HeartbeatExtension: TimeSpan.FromMinutes(2),
        MaximumAttempts: 3,
        MaximumAnalysisDuration: TimeSpan.FromHours(1));
    private const string Worker = "plates-01";

    internal static PlateIdentityFields Identity(char fill = 'a') => new(
        Fingerprint: new string(fill, 64),
        PipelineId: "plates-fixture",
        PipelineVersion: "1.0.0",
        PredictionsSchemaVersion: "mavi-plate-predictions-v1",
        NormalisationId: "mavi-plate-normalisation-v1",
        NormalisationSha256: new string('b', 64),
        SummaryPolicyId: "plate-track-text-rank0",
        SummaryPolicyVersion: "1.0.0",
        SummaryPolicySha256: new string('c', 64),
        CapabilitiesCanonical: "[{\"capabilityId\":\"ocr\",\"modelPackId\":\"mavi-model-v2-" + new string('1', 64) +
            "\"},{\"capabilityId\":\"plate-detector\",\"modelPackId\":\"mavi-model-v2-" + new string('2', 64) + "\"}]",
        ParametersSha256: new string('d', 64));

    private static PlateAnalysis Queued() => PlateAnalysis.Queue(Guid.CreateVersion7(), Identity(), T0);

    private static byte[] Hash(byte fill) => SHA256.HashData(Enumerable.Repeat(fill, 32).ToArray());

    private static PlateAnalysis Claimed(DateTimeOffset? at = null, byte fill = 1)
    {
        var unit = Queued();
        unit.Claim(Worker, Hash(fill), at ?? T0, Policy);
        return unit;
    }

    private static readonly PlateCompletion Facts = new(
        CompletionDigest: new string('e', 64),
        VisibilitySequence: 7,
        PredictionArtifactId: Guid.CreateVersion7(),
        ProvenanceJson: "{}",
        TracksAnalysed: 2,
        TracksUnavailable: 1,
        PlateObservationsRead: 3,
        PlateObservationsUnreadable: 1);

    // --- Queue and claim ---------------------------------------------------------------

    [Fact]
    public void QueueCreatesAnUnclaimedUnitWithNoDeadline()
    {
        var unit = Queued();
        Assert.Equal(PlateAnalysisStatus.Queued, unit.Status);
        Assert.Equal(0, unit.AttemptCount);
        Assert.Null(unit.FirstClaimedAtUtc);
        Assert.Null(unit.Deadline(Policy.MaximumAnalysisDuration));
        Assert.Null(unit.LeaseTokenHash);
    }

    [Fact]
    public void QueueRefusesANonCanonicalIdentity()
    {
        Assert.Throws<DomainValidationException>(() =>
            PlateAnalysis.Queue(Guid.CreateVersion7(), Identity() with { Fingerprint = new string('A', 64) }, T0));
        Assert.Throws<DomainValidationException>(() =>
            PlateAnalysis.Queue(Guid.CreateVersion7(), Identity() with { PipelineId = "Bad Id" }, T0));
        Assert.Throws<DomainValidationException>(() =>
            PlateAnalysis.Queue(Guid.CreateVersion7(), Identity() with { NormalisationSha256 = "abc" }, T0));
        Assert.Throws<DomainValidationException>(() =>
            PlateAnalysis.Queue(Guid.CreateVersion7(), Identity() with { SummaryPolicyVersion = "1.0" }, T0));
        Assert.Throws<DomainValidationException>(() =>
            PlateAnalysis.Queue(Guid.CreateVersion7(), Identity() with { CapabilitiesCanonical = "{}" }, T0));
        Assert.Throws<DomainValidationException>(() =>
            PlateAnalysis.Queue(Guid.Empty, Identity(), T0));
    }

    [Fact]
    public void TheFirstClaimConsumesAnAttemptAndAnchorsTheDeadline()
    {
        var unit = Claimed();
        Assert.Equal(PlateAnalysisStatus.Running, unit.Status);
        Assert.Equal(1, unit.AttemptCount);
        Assert.Equal(Worker, unit.LeaseOwner);
        Assert.Equal(T0, unit.FirstClaimedAtUtc);
        Assert.Equal(T0 + Policy.MaximumAnalysisDuration, unit.Deadline(Policy.MaximumAnalysisDuration));
        Assert.Equal(T0 + Policy.LeaseDuration, unit.LeaseExpiresAtUtc);
    }

    [Fact]
    public void ALiveLeaseCannotBeClaimed()
    {
        var unit = Claimed();
        Assert.False(unit.CanClaim(T0.AddSeconds(119), Policy));
        Assert.Throws<DomainValidationException>(() => unit.Claim("plates-02", Hash(2), T0.AddSeconds(119), Policy));
    }

    [Fact]
    public void AnExpiredLeaseIsReclaimedWithANewAttemptAndCapabilityButTheSameDeadline()
    {
        var unit = Claimed();
        var reclaimAt = T0 + Policy.LeaseDuration;

        unit.Claim("plates-02", Hash(2), reclaimAt, Policy);

        Assert.Equal(2, unit.AttemptCount);
        Assert.Equal("plates-02", unit.LeaseOwner);
        Assert.Equal(Hash(2), unit.LeaseTokenHash);
        Assert.Equal(T0, unit.FirstClaimedAtUtc);
        // The old owner is fenced out even though it presents its own attempt and capability.
        Assert.False(unit.IsOwnedBy(Worker, tokenMatches: true, attemptCount: 1));
    }

    [Fact]
    public void AttemptsAreBoundedAtClaim()
    {
        var unit = Claimed();
        unit.Claim(Worker, Hash(2), T0.AddMinutes(2), Policy);
        unit.Claim(Worker, Hash(3), T0.AddMinutes(4), Policy);
        Assert.Equal(3, unit.AttemptCount);
        Assert.False(unit.CanClaim(T0.AddMinutes(6), Policy));
    }

    [Fact]
    public void TheLeaseNeverOutlivesTheDeadline()
    {
        var shortPolicy = Policy with { MaximumAnalysisDuration = TimeSpan.FromMinutes(3) };
        var unit = Queued();
        unit.Claim(Worker, Hash(1), T0, shortPolicy);
        Assert.Equal(T0.AddMinutes(2), unit.LeaseExpiresAtUtc);

        unit.Heartbeat(Worker, tokenMatches: true, attemptCount: 1, T0.AddSeconds(90), shortPolicy);

        Assert.Equal(T0.AddMinutes(3), unit.LeaseExpiresAtUtc);
        // At the deadline itself nothing extends ownership any further.
        Assert.Throws<DomainValidationException>(() =>
            unit.Heartbeat(Worker, true, 1, T0.AddMinutes(3), shortPolicy));
    }

    [Fact]
    public void NoClaimAtOrAfterTheDeadline()
    {
        var unit = Claimed();
        unit.FailAttempt(Worker, true, 1, "plate_inference_failed", retryable: true, null, T0.AddMinutes(1), Policy);
        Assert.Equal(PlateAnalysisStatus.Queued, unit.Status);
        Assert.False(unit.CanClaim(T0 + Policy.MaximumAnalysisDuration, Policy));
    }

    // --- Heartbeat ----------------------------------------------------------------------

    [Fact]
    public void AHeartbeatExtendsOnlyAnUnexpiredMatchingLease()
    {
        var unit = Claimed();
        unit.Heartbeat(Worker, tokenMatches: true, attemptCount: 1, T0.AddSeconds(60), Policy);
        Assert.Equal(T0.AddSeconds(60) + Policy.HeartbeatExtension, unit.LeaseExpiresAtUtc);
        Assert.Equal(T0.AddSeconds(60), unit.LastHeartbeatUtc);
    }

    public static TheoryData<string, bool, int, int> RefusedHeartbeats => new()
    {
        // worker, token matches, attempt, seconds after claim
        { "plates-02", true, 1, 10 },
        { Worker, false, 1, 10 },
        { Worker, true, 2, 10 },
        // At the expiry instant the lease is already gone: no revival.
        { Worker, true, 1, 120 },
        { Worker, true, 1, 500 },
    };

    [Theory]
    [MemberData(nameof(RefusedHeartbeats))]
    public void ARefusedHeartbeatChangesNothing(string worker, bool tokenMatches, int attempt, int seconds)
    {
        var unit = Claimed();
        var expiry = unit.LeaseExpiresAtUtc;
        Assert.Throws<DomainValidationException>(() =>
            unit.Heartbeat(worker, tokenMatches, attempt, T0.AddSeconds(seconds), Policy));
        Assert.Equal(expiry, unit.LeaseExpiresAtUtc);
        Assert.Null(unit.LastHeartbeatUtc);
    }

    // --- Failure --------------------------------------------------------------------------

    [Fact]
    public void ARetryableFailureRequeuesAndRecordsHistory()
    {
        var unit = Claimed();
        var outcome = unit.FailAttempt(Worker, true, 1, "plate_evidence_transport_failed", retryable: true,
            "reset", T0.AddSeconds(30), Policy);

        Assert.Equal(PlateFailOutcome.Requeued, outcome.Outcome);
        Assert.Equal(PlateAnalysisStatus.Queued, unit.Status);
        Assert.Null(unit.LeaseOwner);
        Assert.Null(unit.LeaseTokenHash);
        Assert.Null(unit.LeaseExpiresAtUtc);
        Assert.Null(unit.FailureCode);
        Assert.Equal(1, outcome.Record.AttemptNumber);
        Assert.Equal("plate_evidence_transport_failed", outcome.Record.FailureCode);
        Assert.True(outcome.Record.Retryable);
        Assert.True(unit.CanClaim(T0.AddSeconds(31), Policy));
    }

    [Fact]
    public void ATerminalFailureFailsTheUnit()
    {
        var unit = Claimed();
        var outcome = unit.FailAttempt(Worker, true, 1, "plate_output_invalid", retryable: false,
            null, T0.AddSeconds(30), Policy);
        Assert.Equal(PlateFailOutcome.Failed, outcome.Outcome);
        Assert.Equal(PlateAnalysisStatus.Failed, unit.Status);
        Assert.Equal("plate_output_invalid", unit.FailureCode);
        Assert.False(unit.CanClaim(T0.AddMinutes(10), Policy));
    }

    [Fact]
    public void ARetryableFailureOnTheLastAttemptIsTerminal()
    {
        var unit = Claimed();
        unit.Claim(Worker, Hash(2), T0.AddMinutes(2), Policy);
        unit.Claim(Worker, Hash(3), T0.AddMinutes(4), Policy);
        var outcome = unit.FailAttempt(Worker, true, 3, "plate_inference_failed", retryable: true,
            null, T0.AddMinutes(5), Policy);
        Assert.Equal(PlateFailOutcome.Failed, outcome.Outcome);
        Assert.Equal(PlateAnalysisStatus.Failed, unit.Status);
    }

    [Fact]
    public void AStaleOrExpiredAttemptCannotFail()
    {
        var unit = Claimed();
        Assert.Throws<DomainValidationException>(() =>
            unit.FailAttempt(Worker, true, 2, "plate_inference_failed", true, null, T0.AddSeconds(5), Policy));
        Assert.Throws<DomainValidationException>(() =>
            unit.FailAttempt(Worker, false, 1, "plate_inference_failed", true, null, T0.AddSeconds(5), Policy));
        Assert.Throws<DomainValidationException>(() =>
            unit.FailAttempt(Worker, true, 1, "plate_inference_failed", true, null, T0.AddMinutes(3), Policy));
        Assert.Equal(PlateAnalysisStatus.Running, unit.Status);
    }

    [Fact]
    public void AFailureCodeMustBeACanonicalWorkerCode()
    {
        var unit = Claimed();
        Assert.Throws<DomainValidationException>(() =>
            unit.FailAttempt(Worker, true, 1, "Bad Code", true, null, T0.AddSeconds(5), Policy));
        Assert.Throws<DomainValidationException>(() =>
            unit.FailAttempt(Worker, true, 1, "plate_inference_failed", true, new string('x', 4001), T0.AddSeconds(5), Policy));
    }

    // --- Platform-owned terminal transitions -----------------------------------------------

    [Fact]
    public void ANeverClaimedUnitNeverFailsOnTheClock()
    {
        var unit = Queued();
        Assert.False(unit.IsDeadlineExceeded(T0.AddYears(1), Policy.MaximumAnalysisDuration));
        Assert.Throws<DomainValidationException>(() => unit.FailDeadlineExceeded(T0.AddYears(1), Policy));
        Assert.Equal(PlateAnalysisStatus.Queued, unit.Status);
    }

    [Fact]
    public void ADeadlineFailsAClaimedUnitAsAWholeWhateverItsLease()
    {
        var unit = Claimed();
        var deadline = T0 + Policy.MaximumAnalysisDuration;
        Assert.Throws<DomainValidationException>(() => unit.FailDeadlineExceeded(deadline.AddTicks(-1), Policy));

        unit.FailDeadlineExceeded(deadline, Policy);

        Assert.Equal(PlateAnalysisStatus.Failed, unit.Status);
        Assert.Equal("plate_deadline_exceeded", unit.FailureCode);
        Assert.False(unit.IsOwnedBy(Worker, true, 1));
    }

    [Fact]
    public void ARequeuedUnitPastItsDeadlineFails()
    {
        var unit = Claimed();
        unit.FailAttempt(Worker, true, 1, "plate_inference_failed", true, null, T0.AddMinutes(1), Policy);
        unit.FailDeadlineExceeded(T0 + Policy.MaximumAnalysisDuration, Policy);
        Assert.Equal(PlateAnalysisStatus.Failed, unit.Status);
    }

    [Fact]
    public void ExhaustionNeedsTheLastAttemptsLeaseToHaveExpired()
    {
        var unit = Claimed();
        unit.Claim(Worker, Hash(2), T0.AddMinutes(2), Policy);
        unit.Claim(Worker, Hash(3), T0.AddMinutes(4), Policy);
        Assert.False(unit.IsExhausted(T0.AddMinutes(5), Policy));
        Assert.Throws<DomainValidationException>(() => unit.FailAttemptsExhausted(T0.AddMinutes(5), Policy));

        Assert.True(unit.IsExhausted(T0.AddMinutes(6), Policy));
        unit.FailAttemptsExhausted(T0.AddMinutes(6), Policy);

        Assert.Equal(PlateAnalysisStatus.Failed, unit.Status);
        Assert.Equal("plate_attempts_exhausted", unit.FailureCode);
    }

    // --- Completion (Phase C) ------------------------------------------------------------------

    [Fact]
    public void CompletionIsFencedByOwnershipNotByTheClock()
    {
        // Phase A validated before expiry; the lease expired while sealing; nobody reclaimed.
        var unit = Claimed();
        unit.Complete(Worker, tokenMatches: true, attemptCount: 1, T0.AddMinutes(10), Facts, isPreferred: true);

        Assert.Equal(PlateAnalysisStatus.Completed, unit.Status);
        Assert.Equal(Facts.CompletionDigest, unit.CompletionDigest);
        Assert.Equal(7, unit.VisibilitySequence);
        Assert.Equal(T0.AddMinutes(10), unit.CompletedAtUtc);
        Assert.True(unit.IsFactBearing);
    }

    [Fact]
    public void AReclaimedAttemptCannotComplete()
    {
        var unit = Claimed();
        unit.Claim("plates-02", Hash(2), T0 + Policy.LeaseDuration, Policy);

        var exception = Assert.Throws<DomainValidationException>(() =>
            unit.Complete(Worker, tokenMatches: true, attemptCount: 1, T0.AddMinutes(3), Facts, isPreferred: true));

        Assert.Equal("plate_attempt_stale", exception.Code);
        Assert.Equal(PlateAnalysisStatus.Running, unit.Status);
        Assert.Null(unit.VisibilitySequence);
    }

    [Theory]
    [InlineData("plates-02", true, 1)]
    [InlineData(Worker, false, 1)]
    [InlineData(Worker, true, 2)]
    public void EachOwnershipFactIsCheckedAtCompletion(string worker, bool tokenMatches, int attempt)
    {
        var unit = Claimed();
        var exception = Assert.Throws<DomainValidationException>(() =>
            unit.Complete(worker, tokenMatches, attempt, T0.AddSeconds(10), Facts, isPreferred: true));
        Assert.Equal("plate_attempt_stale", exception.Code);
    }

    [Fact]
    public void AFailedOrExhaustedUnitCannotComplete()
    {
        var unit = Claimed();
        unit.FailDeadlineExceeded(T0 + Policy.MaximumAnalysisDuration, Policy);
        Assert.Throws<DomainValidationException>(() =>
            unit.Complete(Worker, true, 1, T0 + Policy.MaximumAnalysisDuration, Facts, isPreferred: true));
    }

    [Fact]
    public void AnObsoleteIdentityCompletesDirectlyAsHistory()
    {
        var unit = Claimed();
        unit.Complete(Worker, true, 1, T0.AddSeconds(10), Facts, isPreferred: false);
        Assert.Equal(PlateAnalysisStatus.Superseded, unit.Status);
        Assert.True(unit.IsFactBearing);
        Assert.Equal(7, unit.VisibilitySequence);
    }

    [Fact]
    public void OnlyACompletedUnitCanBeSuperseded()
    {
        var unit = Claimed();
        Assert.Throws<DomainValidationException>(unit.Supersede);
        unit.Complete(Worker, true, 1, T0.AddSeconds(10), Facts, isPreferred: true);
        unit.Supersede();
        Assert.Equal(PlateAnalysisStatus.Superseded, unit.Status);
        // History keeps its facts.
        Assert.Equal(Facts.CompletionDigest, unit.CompletionDigest);
    }

    [Fact]
    public void ReplayAuthenticatesAgainstTheRetainedCapabilityAfterExpiry()
    {
        var unit = Claimed();
        unit.Complete(Worker, true, 1, T0.AddSeconds(10), Facts, isPreferred: true);

        Assert.True(unit.CanAuthenticateCompletionReplay(Worker, tokenMatches: true, attemptCount: 1));
        Assert.False(unit.CanAuthenticateCompletionReplay(Worker, tokenMatches: false, attemptCount: 1));
        Assert.False(unit.CanAuthenticateCompletionReplay(Worker, tokenMatches: true, attemptCount: 2));
        Assert.False(unit.CanAuthenticateCompletionReplay("plates-02", tokenMatches: true, attemptCount: 1));
        Assert.False(Claimed().CanAuthenticateCompletionReplay(Worker, true, 1));
    }

    [Fact]
    public void CompletionRefusesANonCanonicalDigestOrNegativeCounts()
    {
        var unit = Claimed();
        Assert.Throws<DomainValidationException>(() =>
            unit.Complete(Worker, true, 1, T0.AddSeconds(10), Facts with { CompletionDigest = "x" }, true));
        Assert.Throws<DomainValidationException>(() =>
            unit.Complete(Worker, true, 1, T0.AddSeconds(10), Facts with { TracksAnalysed = -1 }, true));
        Assert.Throws<DomainValidationException>(() =>
            unit.Complete(Worker, true, 1, T0.AddSeconds(10), Facts with { VisibilitySequence = 0 }, true));
        Assert.Equal(PlateAnalysisStatus.Running, unit.Status);
    }

    // --- Publication window (plan §13; ADR-013 implementation amendment item 4) ------------------

    [Fact]
    public void APublicationWindowHoldsTheUnitForOneLeaseFromPhaseA()
    {
        var unit = Claimed();
        unit.BeginPublication(Worker, tokenMatches: true, 1, T0.AddSeconds(100), Policy);

        Assert.Equal(T0.AddSeconds(100) + Policy.LeaseDuration, unit.LeaseExpiresAtUtc);
        // Past the claim's own lease, inside the window: not reclaimable, not exhausted.
        Assert.False(unit.CanClaim(T0.AddSeconds(130), Policy));
        Assert.True(unit.HasLiveLease(T0.AddSeconds(130)));
        Assert.False(unit.CanClaim(T0.AddSeconds(219), Policy));
        Assert.True(unit.CanClaim(T0.AddSeconds(220), Policy));
    }

    [Fact]
    public void APublicationWindowOutlivesTheDeadlineByAtMostOneLease()
    {
        var policy = Policy with { MaximumAnalysisDuration = TimeSpan.FromSeconds(150) };
        var unit = Queued();
        unit.Claim(Worker, Hash(1), T0, policy);
        unit.Heartbeat(Worker, tokenMatches: true, 1, T0.AddSeconds(100), policy);
        Assert.Equal(T0.AddSeconds(150), unit.LeaseExpiresAtUtc);   // an ordinary lease is capped at the deadline

        unit.BeginPublication(Worker, tokenMatches: true, 1, T0.AddSeconds(140), policy);
        Assert.Equal(T0.AddSeconds(140) + policy.LeaseDuration, unit.LeaseExpiresAtUtc);   // +260 s, past the +150 s deadline

        // Past the deadline the window protects the validated completion from the deadline...
        Assert.True(unit.IsDeadlineExceeded(T0.AddSeconds(200), policy.MaximumAnalysisDuration));
        Assert.False(unit.IsDeadlineEnforceable(T0.AddSeconds(200), policy));
        Assert.Throws<DomainValidationException>(() => unit.FailDeadlineExceeded(T0.AddSeconds(200), policy));
        // ...but a repeated Phase A cannot push it past deadline + one lease, and once that lapses
        // the deadline wins.
        unit.BeginPublication(Worker, tokenMatches: true, 1, T0.AddSeconds(250), policy);
        Assert.Equal(T0.AddSeconds(150) + policy.LeaseDuration, unit.LeaseExpiresAtUtc);
        Assert.True(unit.IsDeadlineEnforceable(T0.AddSeconds(270), policy));
        unit.FailDeadlineExceeded(T0.AddSeconds(270), policy);
        Assert.Equal(PlateAnalysisStatus.Failed, unit.Status);
    }

    [Fact]
    public void AHeartbeatNeverShortensAPublicationWindow()
    {
        var unit = Claimed();
        unit.BeginPublication(Worker, tokenMatches: true, 1, T0.AddSeconds(100), Policy);
        unit.Heartbeat(Worker, tokenMatches: true, 1, T0.AddSeconds(10), Policy);

        Assert.Equal(T0.AddSeconds(100) + Policy.LeaseDuration, unit.LeaseExpiresAtUtc);
    }

    [Theory]
    [InlineData("plates-01", true, 2, 10)]   // another attempt
    [InlineData("plates-01", false, 1, 10)]  // another capability
    [InlineData("plates-02", true, 1, 10)]   // another worker
    [InlineData("plates-01", true, 1, 500)]  // an expired lease: Phase A would have refused it
    public void OnlyTheActiveOwnerCanBeginAPublication(string worker, bool tokenMatches, int attempt, int seconds)
    {
        var unit = Claimed();
        var before = unit.LeaseExpiresAtUtc;
        Assert.Throws<DomainValidationException>(() => unit.BeginPublication(worker, tokenMatches, attempt, T0.AddSeconds(seconds), Policy));
        Assert.Equal(before, unit.LeaseExpiresAtUtc);
    }

    [Fact]
    public void TheFinalAttemptIsNotExhaustedWhilePublishing()
    {
        var policy = Policy with { MaximumAttempts = 1 };
        var unit = Queued();
        unit.Claim(Worker, Hash(1), T0, policy);
        unit.BeginPublication(Worker, tokenMatches: true, 1, T0.AddSeconds(110), policy);

        Assert.False(unit.IsExhausted(T0.AddSeconds(200), policy));
        Assert.True(unit.IsExhausted(T0.AddSeconds(230), policy));
    }
}
