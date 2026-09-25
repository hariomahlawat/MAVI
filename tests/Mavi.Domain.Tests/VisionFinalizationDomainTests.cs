using System.Security.Cryptography;
using Mavi.Domain.Common;
using Mavi.Domain.Processing;

namespace Mavi.Domain.Tests;

/// <summary>
/// <c>Leased → Finalizing → Completed | Failed</c> and the finalizer claim
/// (S1.4 B3 asynchronous finalization plan §3, §6, §7, §10; slice F1).
/// </summary>
public sealed class VisionFinalizationDomainTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 25, 8, 0, 0, TimeSpan.Zero);
    private static readonly string Digest = new('a', 64);
    private static readonly TimeSpan Lease = TimeSpan.FromMinutes(2);

    private static VisionJob LeasedJob(string workerId = "worker-a")
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "phase1", Now);
        job.Lease(workerId, new byte[32], Now, Lease, 3);
        return job;
    }

    private static VisionJob FinalizingJob(string workerId = "worker-a")
    {
        var job = LeasedJob(workerId);
        job.BeginFinalization(workerId, true, 1, Now.AddSeconds(30), Digest);
        return job;
    }

    private static (byte[] Token, byte[] Hash) ClaimToken(byte fill = 7)
    {
        var token = new byte[VisionJob.FinalizationClaimTokenByteLength];
        Array.Fill(token, fill);
        return (token, SHA256.HashData(token));
    }

    // -- Leased → Finalizing ------------------------------------------------------------------

    [Fact]
    public void BeginFinalizationRetainsHandOffFactsAndResetsClaimState()
    {
        var job = LeasedJob();
        var accepted = Now.AddSeconds(30);

        job.BeginFinalization("worker-a", true, 1, accepted, Digest);

        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal(Digest, job.CompletionDigest);
        Assert.Equal(accepted, job.FinalizationAcceptedAtUtc);
        Assert.Equal(100, job.ProgressPercent);
        Assert.Null(job.CompletedAtUtc);
        // Replay authentication facts survive the hand-off (plan §6).
        Assert.Equal("worker-a", job.LeaseOwner);
        Assert.NotNull(job.LeaseTokenHash);
        Assert.Equal(1, job.AttemptCount);
        Assert.Equal(Now.Add(Lease), job.LeaseExpiresAtUtc);
        // Finalizer claim state starts empty.
        Assert.Equal(0, job.FinalizationAttemptCount);
        Assert.Null(job.FinalizationClaimTokenHash);
        Assert.Null(job.FinalizationClaimExpiresAtUtc);
        Assert.Null(job.FinalizationClaimExtendedAtUtc);
        Assert.Null(job.FinalizationLastErrorCode);
    }

    [Theory]
    [InlineData("worker-b", true, 1, 30)]   // wrong owner
    [InlineData("worker-a", false, 1, 30)]  // wrong lease token
    [InlineData("Worker-A", true, 1, 30)]   // non-canonical worker id
    [InlineData("worker-a", true, 1, 120)]  // lease expired at authority time
    [InlineData("worker-a", true, 1, 121)]
    public void BeginFinalizationRequiresTheLiveLeaseAuthority(string workerId, bool tokenMatches, int attempt, int atSeconds)
    {
        var job = LeasedJob();

        Assert.Throws<DomainValidationException>(() =>
            job.BeginFinalization(workerId, tokenMatches, attempt, Now.AddSeconds(atSeconds), Digest));

        Assert.Equal(VisionJobStatus.Leased, job.Status);
        Assert.Null(job.CompletionDigest);
        Assert.Null(job.FinalizationAcceptedAtUtc);
    }

    [Fact]
    public void BeginFinalizationAcceptsTheLastInstantBeforeExpiry()
    {
        var job = LeasedJob();

        job.BeginFinalization("worker-a", true, 1, Now.Add(Lease).AddTicks(-1), Digest);

        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(2)]
    public void BeginFinalizationRejectsAnotherAttempt(int attempt)
    {
        var job = LeasedJob();

        var error = Assert.Throws<DomainValidationException>(() =>
            job.BeginFinalization("worker-a", true, attempt, Now.AddSeconds(1), Digest));

        Assert.Equal("vision_job_attempt_mismatch", error.Code);
        Assert.Equal(VisionJobStatus.Leased, job.Status);
    }

    [Theory]
    [InlineData("")]
    [InlineData("abc")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")]
    [InlineData("gggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggg")]
    public void BeginFinalizationRejectsANonCanonicalDigestBeforeTouchingState(string digest)
    {
        var job = LeasedJob();

        var error = Assert.Throws<DomainValidationException>(() =>
            job.BeginFinalization("worker-a", true, 1, Now.AddSeconds(1), digest));

        Assert.Equal("vision_job_completion_digest_invalid", error.Code);
        Assert.Equal(VisionJobStatus.Leased, job.Status);
        Assert.Null(job.CompletionDigest);
    }

    [Fact]
    public void BeginFinalizationIsNotAvailableFromQueuedOrTerminalStates()
    {
        var queued = VisionJob.Create(Guid.CreateVersion7(), "phase1", Now);
        Assert.Throws<DomainValidationException>(() => queued.BeginFinalization("worker-a", true, 0, Now, Digest));

        var finalizing = FinalizingJob();
        Assert.Throws<DomainValidationException>(() => finalizing.BeginFinalization("worker-a", true, 1, Now.AddSeconds(31), Digest));
        Assert.Equal(VisionJobStatus.Finalizing, finalizing.Status);

        var completed = LeasedJob();
        completed.Complete("worker-a", true, Now.AddSeconds(1), Digest);
        Assert.Throws<DomainValidationException>(() => completed.BeginFinalization("worker-a", true, 1, Now.AddSeconds(2), Digest));
    }

    // -- Finalizing blocks the lease surface by status -------------------------------------------

    [Fact]
    public void FinalizingRefusesHeartbeatWorkerFailureReLeaseAndExhaustion()
    {
        var job = FinalizingJob();
        var duringLease = Now.AddSeconds(40);
        var afterLease = Now.Add(Lease).AddMinutes(10);

        Assert.Throws<DomainValidationException>(() => job.Heartbeat("worker-a", true, 50, duringLease, TimeSpan.FromMinutes(1)));
        Assert.Throws<DomainValidationException>(() => job.Fail("worker-a", true, "vision_worker_crash", null, duringLease));
        Assert.Throws<DomainValidationException>(() => job.Complete("worker-a", true, duringLease, Digest));
        Assert.False(job.CanLease(afterLease, 3));
        Assert.Throws<DomainValidationException>(() => job.Lease("worker-b", new byte[32], afterLease, Lease, 3));
        Assert.Throws<DomainValidationException>(() => job.Exhaust(afterLease));

        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal("worker-a", job.LeaseOwner);
        Assert.Equal(1, job.AttemptCount);
    }

    [Fact]
    public void LeasedBehaviourIsUnchanged()
    {
        var job = LeasedJob();
        Assert.False(job.CanLease(Now.AddSeconds(30), 3));
        Assert.True(job.CanLease(Now.Add(Lease), 3));

        job.Lease("worker-b", new byte[32], Now.Add(Lease), Lease, 3);
        Assert.Equal(2, job.AttemptCount);
        Assert.Equal("worker-b", job.LeaseOwner);
    }

    // -- replay authentication ----------------------------------------------------------------

    [Fact]
    public void ReplayAuthenticatesWithTheHandOffCapabilityRegardlessOfLeaseExpiry()
    {
        var job = FinalizingJob();

        Assert.True(job.CanAuthenticateCompletionReplay("worker-a", true, 1));
        Assert.False(job.CanAuthenticateCompletionReplay("worker-b", true, 1));
        Assert.False(job.CanAuthenticateCompletionReplay("worker-a", false, 1));
        Assert.False(job.CanAuthenticateCompletionReplay("worker-a", true, 2));
        Assert.False(job.CanAuthenticateCompletionReplay("Worker-A", true, 1));

        var (_, hash) = ClaimToken();
        job.ClaimFinalization(hash, Now.AddMinutes(1), TimeSpan.FromMinutes(5), 3);
        job.CompleteFinalization(Now.AddMinutes(2));
        Assert.True(job.CanAuthenticateCompletionReplay("worker-a", true, 1));
    }

    [Fact]
    public void ReplayDoesNotAuthenticateAgainstLeasedQueuedOrFailedJobs()
    {
        Assert.False(LeasedJob().CanAuthenticateCompletionReplay("worker-a", true, 1));
        Assert.False(VisionJob.Create(Guid.CreateVersion7(), "phase1", Now).CanAuthenticateCompletionReplay("worker-a", true, 0));

        var failed = FinalizingJob();
        failed.FailFinalization("vision_finalization_payload_invalid", null, Now.AddMinutes(1));
        Assert.False(failed.CanAuthenticateCompletionReplay("worker-a", true, 1));
    }

    // -- finalizer claim ----------------------------------------------------------------------

    [Fact]
    public void ClaimRotatesTheTokenAndIsFencedByExpiry()
    {
        var job = FinalizingJob();
        var (first, firstHash) = ClaimToken(1);
        var (second, secondHash) = ClaimToken(2);
        var claimed = Now.AddMinutes(1);

        Assert.True(job.CanClaimFinalization(claimed, 3));
        job.ClaimFinalization(firstHash, claimed, TimeSpan.FromMinutes(5), 3);

        Assert.Equal(1, job.FinalizationAttemptCount);
        Assert.Equal(claimed.AddMinutes(5), job.FinalizationClaimExpiresAtUtc);
        Assert.Equal(claimed, job.FinalizationClaimExtendedAtUtc);
        Assert.True(job.FinalizationOwnedBy(first, claimed.AddMinutes(4)));
        Assert.False(job.FinalizationOwnedBy(second, claimed.AddMinutes(4)));
        Assert.False(job.FinalizationOwnedBy(first, claimed.AddMinutes(5)), "an expired claim proves nothing");
        Assert.False(job.FinalizationOwnedBy(first.AsSpan(..31), claimed.AddMinutes(4)));

        // Live claim cannot be taken over.
        Assert.False(job.CanClaimFinalization(claimed.AddMinutes(4), 3));
        Assert.Throws<DomainValidationException>(() => job.ClaimFinalization(secondHash, claimed.AddMinutes(4), TimeSpan.FromMinutes(5), 3));

        // Expired claim is retaken with a rotated token; the old token is dead.
        job.ClaimFinalization(secondHash, claimed.AddMinutes(6), TimeSpan.FromMinutes(5), 3);
        Assert.Equal(2, job.FinalizationAttemptCount);
        Assert.True(job.FinalizationOwnedBy(second, claimed.AddMinutes(7)));
        Assert.False(job.FinalizationOwnedBy(first, claimed.AddMinutes(7)));
    }

    [Fact]
    public void ClaimIsBoundedByMaximumAttemptsAndValidatesItsInputs()
    {
        var job = FinalizingJob();
        var (_, hash) = ClaimToken();

        Assert.False(job.CanClaimFinalization(Now.AddMinutes(1), 0));
        Assert.Throws<DomainValidationException>(() => job.ClaimFinalization(new byte[31], Now.AddMinutes(1), TimeSpan.FromMinutes(5), 3));
        Assert.Throws<DomainValidationException>(() => job.ClaimFinalization(hash, Now.AddMinutes(1), TimeSpan.Zero, 3));
        Assert.Equal(0, job.FinalizationAttemptCount);

        job.ClaimFinalization(hash, Now.AddMinutes(1), TimeSpan.FromMinutes(1), 2);
        job.ClaimFinalization(hash, Now.AddMinutes(3), TimeSpan.FromMinutes(1), 2);
        Assert.False(job.CanClaimFinalization(Now.AddMinutes(5), 2));
        Assert.Throws<DomainValidationException>(() => job.ClaimFinalization(hash, Now.AddMinutes(5), TimeSpan.FromMinutes(1), 2));
        Assert.Equal(2, job.FinalizationAttemptCount);
    }

    [Fact]
    public void ClaimIsOnlyAvailableWhileFinalizing()
    {
        var (token, hash) = ClaimToken();
        var leased = LeasedJob();
        Assert.False(leased.CanClaimFinalization(Now, 3));
        Assert.Throws<DomainValidationException>(() => leased.ClaimFinalization(hash, Now, TimeSpan.FromMinutes(1), 3));
        Assert.False(leased.FinalizationOwnedBy(token, Now));
    }

    [Fact]
    public void ExtensionNeedsTheLiveClaim()
    {
        var job = FinalizingJob();
        var (token, hash) = ClaimToken();
        var (other, _) = ClaimToken(9);
        job.ClaimFinalization(hash, Now.AddMinutes(1), TimeSpan.FromMinutes(5), 3);

        job.ExtendFinalizationClaim(token, Now.AddMinutes(4), TimeSpan.FromMinutes(5));
        Assert.Equal(Now.AddMinutes(9), job.FinalizationClaimExpiresAtUtc);
        Assert.Equal(Now.AddMinutes(4), job.FinalizationClaimExtendedAtUtc);

        Assert.Throws<DomainValidationException>(() => job.ExtendFinalizationClaim(other, Now.AddMinutes(5), TimeSpan.FromMinutes(5)));
        Assert.Throws<DomainValidationException>(() => job.ExtendFinalizationClaim(token, Now.AddMinutes(5), TimeSpan.Zero));
        Assert.Throws<DomainValidationException>(() => job.ExtendFinalizationClaim(token, Now.AddMinutes(9), TimeSpan.FromMinutes(5)));
        Assert.Equal(Now.AddMinutes(9), job.FinalizationClaimExpiresAtUtc);
    }

    [Fact]
    public void TransientErrorsAreNotedWithoutLeavingFinalizing()
    {
        var job = FinalizingJob();

        job.NoteFinalizationError("vision_finalization_seal_io");

        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal("vision_finalization_seal_io", job.FinalizationLastErrorCode);
        Assert.Null(job.FailureCode);
        Assert.Throws<DomainValidationException>(() => job.NoteFinalizationError("vision_worker_crash"));
    }

    // -- Finalizing → Completed ---------------------------------------------------------------

    [Fact]
    public void CompleteFinalizationIsClaimDependentAndLeaseIndependent()
    {
        var job = FinalizingJob();
        var (_, hash) = ClaimToken();
        var afterLease = Now.Add(Lease).AddHours(1);

        Assert.Throws<DomainValidationException>(() => job.CompleteFinalization(afterLease));
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);

        job.ClaimFinalization(hash, afterLease, TimeSpan.FromMinutes(5), 3);
        job.CompleteFinalization(afterLease.AddMinutes(1));

        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(afterLease.AddMinutes(1), job.CompletedAtUtc);
        Assert.Equal(Digest, job.CompletionDigest);
        Assert.Equal("worker-a", job.LeaseOwner);
        Assert.Equal(1, job.AttemptCount);
        Assert.Null(job.FinalizationClaimTokenHash);
        Assert.Null(job.FinalizationClaimExpiresAtUtc);
        Assert.Equal(1, job.FinalizationAttemptCount);
        Assert.Throws<DomainValidationException>(() => job.CompleteFinalization(afterLease.AddMinutes(2)));
    }

    [Fact]
    public void CompleteFinalizationRefusesACompletionBeforeAcceptance()
    {
        var job = FinalizingJob();
        var (_, hash) = ClaimToken();
        job.ClaimFinalization(hash, Now.AddMinutes(1), TimeSpan.FromMinutes(5), 3);

        Assert.Throws<DomainValidationException>(() => job.CompleteFinalization(Now.AddSeconds(29)));
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
    }

    // -- Finalizing → Failed ------------------------------------------------------------------

    [Fact]
    public void FailFinalizationIsTerminalKeepsTheHandOffFactsAndClearsTheClaim()
    {
        var job = FinalizingJob();
        var (_, hash) = ClaimToken();
        job.ClaimFinalization(hash, Now.AddMinutes(1), TimeSpan.FromMinutes(5), 3);

        job.FailFinalization("vision_finalization_attempts_exhausted", "seal timed out", Now.AddMinutes(2));

        Assert.Equal(VisionJobStatus.Failed, job.Status);
        Assert.Equal("vision_finalization_attempts_exhausted", job.FailureCode);
        Assert.Equal("vision_finalization_attempts_exhausted", job.FinalizationLastErrorCode);
        Assert.Equal("seal timed out", job.FailureDetails);
        Assert.Equal(Now.AddMinutes(2), job.CompletedAtUtc);
        Assert.Equal(Digest, job.CompletionDigest);
        Assert.Equal(Now.AddSeconds(30), job.FinalizationAcceptedAtUtc);
        Assert.Null(job.FinalizationClaimTokenHash);
        Assert.Null(job.FinalizationClaimExpiresAtUtc);
        Assert.False(job.CanLease(Now.AddDays(1), 3));
        Assert.False(job.CanClaimFinalization(Now.AddDays(1), 3));
        Assert.Throws<DomainValidationException>(() => job.CompleteFinalization(Now.AddMinutes(3)));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("vision_finalization_")]
    [InlineData("vision_job_attempts_exhausted")]
    [InlineData("vision_finalization_Seal")]
    [InlineData("vision_finalization_seal io")]
    [InlineData("vision_finalization_0123456789012345678901234567890123456789012345")]
    public void FailFinalizationAcceptsOnlyBoundedFinalizationCodes(string? code)
    {
        Assert.False(VisionJob.IsFinalizationFailureCode(code));
        var job = FinalizingJob();

        Assert.Throws<DomainValidationException>(() => job.FailFinalization(code!, null, Now.AddMinutes(1)));

        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Null(job.FailureCode);
    }

    [Fact]
    public void FinalizationFailureCodeBoundsAreExact()
    {
        Assert.True(VisionJob.IsFinalizationFailureCode("vision_finalization_x"));
        Assert.True(VisionJob.IsFinalizationFailureCode("vision_finalization_" + new string('a', 64 - "vision_finalization_".Length)));
        Assert.False(VisionJob.IsFinalizationFailureCode("vision_finalization_" + new string('a', 65 - "vision_finalization_".Length)));
    }

    [Fact]
    public void FailFinalizationBoundsDetailsAndRequiresFinalizing()
    {
        var job = FinalizingJob();
        Assert.Throws<DomainValidationException>(() =>
            job.FailFinalization("vision_finalization_payload_invalid", new string('d', 4001), Now.AddMinutes(1)));
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);

        job.FailFinalization("vision_finalization_payload_invalid", new string('d', 4000), Now.AddMinutes(1));
        Assert.Equal(VisionJobStatus.Failed, job.Status);

        var leased = LeasedJob();
        Assert.Throws<DomainValidationException>(() => leased.FailFinalization("vision_finalization_payload_invalid", null, Now));
        Assert.Equal(VisionJobStatus.Leased, leased.Status);
    }

    // -- synchronous completion is untouched --------------------------------------------------

    [Fact]
    public void SynchronousCompletionStillGoesStraightToCompleted()
    {
        var job = LeasedJob();

        job.Complete("worker-a", true, Now.AddSeconds(1), Digest);

        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Null(job.FinalizationAcceptedAtUtc);
        Assert.Equal(0, job.FinalizationAttemptCount);
        Assert.True(job.CanAuthenticateCompletionReplay("worker-a", true, 1));
    }

    // -- retained payload ---------------------------------------------------------------------

    [Fact]
    public void PayloadRetainsExactBytesWithLengthShaAndDigest()
    {
        var jobId = Guid.CreateVersion7();
        byte[] bytes = [0x7b, 0x22, 0x61, 0x22, 0x3a, 0x31, 0x7d];

        var payload = VisionFinalizationPayload.Create(jobId, 2, bytes, Digest, Now.ToOffset(TimeSpan.FromHours(5)), 1024);
        bytes[0] = 0x00; // the caller's buffer is not shared

        Assert.Equal(jobId, payload.JobId);
        Assert.Equal(2, payload.AttemptCount);
        Assert.Equal(new byte[] { 0x7b, 0x22, 0x61, 0x22, 0x3a, 0x31, 0x7d }, payload.Payload);
        Assert.Equal(7, payload.PayloadLength);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(payload.Payload)), payload.PayloadSha256);
        Assert.Equal(Digest, payload.CompletionDigest);
        Assert.Equal(Now, payload.AcceptedAtUtc);
        Assert.Equal(TimeSpan.Zero, payload.AcceptedAtUtc.Offset);
        Assert.True(payload.Matches(payload.Payload));
        Assert.False(payload.Matches(bytes));
        Assert.False(payload.Matches([.. payload.Payload, 0x20]));
        Assert.False(payload.Matches(payload.Payload.AsSpan(..6)));
    }

    [Fact]
    public void PayloadCreationIsBoundedAndCanonical()
    {
        var jobId = Guid.CreateVersion7();
        byte[] ok = [1, 2, 3];

        static string Code(Action action) => Assert.Throws<DomainValidationException>(action).Code;

        Assert.Equal("vision_finalization_payload_job_required", Code(() => VisionFinalizationPayload.Create(Guid.Empty, 1, ok, Digest, Now, 8)));
        Assert.Equal("vision_finalization_payload_attempt_invalid", Code(() => VisionFinalizationPayload.Create(jobId, 0, ok, Digest, Now, 8)));
        Assert.Equal("vision_finalization_payload_bound_invalid", Code(() => VisionFinalizationPayload.Create(jobId, 1, ok, Digest, Now, 0)));
        Assert.Equal("vision_finalization_payload_size_invalid", Code(() => VisionFinalizationPayload.Create(jobId, 1, [], Digest, Now, 8)));
        Assert.Equal("vision_finalization_payload_size_invalid", Code(() => VisionFinalizationPayload.Create(jobId, 1, new byte[9], Digest, Now, 8)));
        Assert.Equal("vision_finalization_payload_digest_invalid", Code(() => VisionFinalizationPayload.Create(jobId, 1, ok, Digest.ToUpperInvariant(), Now, 8)));
        Assert.Equal("vision_finalization_payload_digest_invalid", Code(() => VisionFinalizationPayload.Create(jobId, 1, ok, Digest[..63], Now, 8)));

        Assert.Equal(8, VisionFinalizationPayload.Create(jobId, 1, new byte[8], Digest, Now, 8).PayloadLength);
    }
}
