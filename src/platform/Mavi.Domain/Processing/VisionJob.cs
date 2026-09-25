using System.Security.Cryptography;
using Mavi.Domain.Common;

namespace Mavi.Domain.Processing;

public sealed class VisionJob
{
    /// <summary>Random bytes of a finalizer claim token; only its SHA-256 is persisted.</summary>
    public const int FinalizationClaimTokenByteLength = 32;
    private const int Sha256ByteLength = 32;
    /// <summary>Every finalization failure code carries this prefix, so it is never read as an inference failure.</summary>
    public const string FinalizationFailureCodePrefix = "vision_finalization_";
    /// <summary>
    /// The terminal code of platform reconciliation (<see cref="ExhaustFinalization"/>): no live
    /// claim remained and no further claim was permitted (F3 plan §5.3).
    /// </summary>
    public const string FinalizationExhaustedFailureCode = "vision_finalization_exhausted";

    private VisionJob() { }

    public static VisionJob Create(Guid processingRunId, string pipeline, DateTimeOffset nowUtc)
    {
        if (processingRunId == Guid.Empty || string.IsNullOrWhiteSpace(pipeline) || pipeline.Trim().Length > 64) throw Invalid();
        var now = nowUtc.ToUniversalTime();
        return new VisionJob
        {
            Id = Guid.CreateVersion7(),
            ProcessingRunId = processingRunId,
            Pipeline = pipeline.Trim(),
            Status = VisionJobStatus.Queued,
            CreatedAtUtc = now,
            AvailableAtUtc = now
        };
    }

    public bool CanLease(DateTimeOffset nowUtc, int maximumAttempts) => maximumAttempts >= 1 && AttemptCount < maximumAttempts &&
        ((Status == VisionJobStatus.Queued && AvailableAtUtc <= nowUtc) || (Status == VisionJobStatus.Leased && LeaseExpiresAtUtc <= nowUtc));

    public void Lease(string workerId, byte[] leaseTokenHash, DateTimeOffset nowUtc, TimeSpan duration, int maximumAttempts)
    {
        if (!CanLease(nowUtc, maximumAttempts) || !WorkerIdRules.IsCanonical(workerId) ||
            leaseTokenHash is not { Length: 32 } || duration <= TimeSpan.Zero) throw Invalid();

        Status = VisionJobStatus.Leased;
        LeaseOwner = workerId;
        LeaseTokenHash = [.. leaseTokenHash];
        LeaseExpiresAtUtc = nowUtc.ToUniversalTime().Add(duration);
        AttemptCount++;
        ProgressPercent = 0;
        LastHeartbeatUtc = null;
        CompletionDigest = null;
    }

    public void Heartbeat(string workerId, bool leaseTokenMatches, double progressPercent, DateTimeOffset nowUtc, TimeSpan extension)
    {
        RequireValidLease(workerId, leaseTokenMatches, nowUtc);
        if (!double.IsFinite(progressPercent) || progressPercent is < 0 or > 100 || extension <= TimeSpan.Zero) throw Invalid();
        if (progressPercent < ProgressPercent)
            throw new DomainValidationException("vision_job_progress_regression", "Vision job progress cannot decrease.");

        ProgressPercent = progressPercent;
        LastHeartbeatUtc = nowUtc.ToUniversalTime();
        LeaseExpiresAtUtc = nowUtc.ToUniversalTime().Add(extension);
    }

    public void Complete(string workerId, bool leaseTokenMatches, DateTimeOffset nowUtc) =>
        CompleteCore(workerId, leaseTokenMatches, nowUtc, nowUtc, null);

    public void Complete(string workerId, bool leaseTokenMatches, DateTimeOffset nowUtc, string completionDigest)
    {
        if (!IsCanonicalSha256(completionDigest))
            throw new DomainValidationException("vision_job_completion_digest_invalid", "Completion digest must be canonical SHA-256.");
        CompleteCore(workerId, leaseTokenMatches, nowUtc, nowUtc, completionDigest);
    }

    public void Complete(
        string workerId,
        bool leaseTokenMatches,
        DateTimeOffset authorityNowUtc,
        DateTimeOffset completedAtUtc,
        string completionDigest)
    {
        if (!IsCanonicalSha256(completionDigest))
            throw new DomainValidationException("vision_job_completion_digest_invalid", "Completion digest must be canonical SHA-256.");
        if (completedAtUtc < authorityNowUtc)
            throw Invalid();

        CompleteCore(
            workerId,
            leaseTokenMatches,
            authorityNowUtc,
            completedAtUtc,
            completionDigest);
    }

    private void CompleteCore(
        string workerId,
        bool leaseTokenMatches,
        DateTimeOffset authorityNowUtc,
        DateTimeOffset completedAtUtc,
        string? completionDigest)
    {
        RequireValidLease(workerId, leaseTokenMatches, authorityNowUtc);
        Status = VisionJobStatus.Completed;
        ProgressPercent = 100;
        CompletionDigest = completionDigest;
        CompletedAtUtc = completedAtUtc.ToUniversalTime();
    }

    public void Fail(string workerId, bool leaseTokenMatches, string code, string? details, DateTimeOffset nowUtc)
    {
        RequireValidLease(workerId, leaseTokenMatches, nowUtc);
        if (string.IsNullOrWhiteSpace(code) || code.Length > 64 || details?.Length > 4000) throw Invalid();
        Status = VisionJobStatus.Failed;
        FailureCode = code;
        FailureDetails = details;
        CompletedAtUtc = nowUtc.ToUniversalTime();
    }

    // -- Finalizing (S1.4 B3 asynchronous finalization plan §3, §6, §7, §10) ----------------

    /// <summary>
    /// The durable hand-off, <c>Leased → Finalizing</c>: the worker's completion has been
    /// validated and retained. It needs the same live lease authority as a completion did.
    /// </summary>
    /// <remarks>
    /// <c>LeaseOwner</c>, <c>LeaseTokenHash</c> and <c>AttemptCount</c> are kept, so an exact
    /// duplicate completion after an ambiguous HTTP outcome can still authenticate against the
    /// capability that handed the job off (<see cref="CanAuthenticateCompletionReplay"/>).
    /// They are replay authentication only: from here the status, not the lease expiry,
    /// refuses heartbeat, worker failure and re-lease.
    /// </remarks>
    public void BeginFinalization(
        string workerId,
        bool leaseTokenMatches,
        int attemptCount,
        DateTimeOffset authorityNowUtc,
        string completionDigest)
    {
        if (!IsCanonicalSha256(completionDigest))
            throw new DomainValidationException("vision_job_completion_digest_invalid", "Completion digest must be canonical SHA-256.");
        RequireValidLease(workerId, leaseTokenMatches, authorityNowUtc);
        if (attemptCount != AttemptCount)
            throw new DomainValidationException("vision_job_attempt_mismatch", "The completion is for another attempt.");

        Status = VisionJobStatus.Finalizing;
        ProgressPercent = 100;
        CompletionDigest = completionDigest;
        FinalizationAcceptedAtUtc = authorityNowUtc.ToUniversalTime();
        FinalizationAttemptCount = 0;
        FinalizationClaimTokenHash = null;
        FinalizationClaimExpiresAtUtc = null;
        FinalizationClaimExtendedAtUtc = null;
        FinalizationLastErrorCode = null;
    }

    /// <summary>
    /// Whether a duplicate completion POST presents the capability that handed this job off:
    /// same worker, same token, same attempt, on a job that is Finalizing or Completed. Lease
    /// expiry is deliberately not consulted; the hand-off ended the lease.
    /// </summary>
    public bool CanAuthenticateCompletionReplay(string workerId, bool leaseTokenMatches, int attemptCount) =>
        Status is VisionJobStatus.Finalizing or VisionJobStatus.Completed &&
        WorkerIdRules.IsCanonical(workerId) &&
        string.Equals(LeaseOwner, workerId, StringComparison.Ordinal) &&
        leaseTokenMatches &&
        attemptCount == AttemptCount &&
        CompletionDigest is not null;

    /// <summary>
    /// The absolute finalization deadline, <c>FinalizationAcceptedAtUtc + maximumFinalizationDuration</c>
    /// (F3 plan §5.4): the one instant that exists before any claim and survives every reclaim.
    /// <see langword="null"/> before the hand-off.
    /// </summary>
    public DateTimeOffset? FinalizationDeadline(TimeSpan maximumFinalizationDuration) =>
        maximumFinalizationDuration > TimeSpan.Zero && FinalizationAcceptedAtUtc is { } accepted
            ? accepted.Add(maximumFinalizationDuration)
            : null;

    /// <summary>
    /// The strict rule every creation or prolongation of ownership shares: <c>now &lt; deadline</c>.
    /// At the deadline instant itself it is already false.
    /// </summary>
    public bool IsBeforeFinalizationDeadline(DateTimeOffset nowUtc, TimeSpan maximumFinalizationDuration) =>
        FinalizationDeadline(maximumFinalizationDuration) is { } deadline && nowUtc.ToUniversalTime() < deadline;

    /// <summary>
    /// The canonical classification of the ownership metadata triple (F3 plan §5.2). The aggregate
    /// writes the three columns together, so only <see cref="FinalizationClaimState.Unclaimed"/>,
    /// <see cref="FinalizationClaimState.Live"/> and <see cref="FinalizationClaimState.Expired"/>
    /// are reachable through it; anything else is <see cref="FinalizationClaimState.Malformed"/>
    /// and fails closed everywhere: never claimed, never exhausted, never owned, never repaired.
    /// </summary>
    public FinalizationClaimState FinalizationClaimStateAt(DateTimeOffset nowUtc)
    {
        if (FinalizationClaimTokenHash is null && FinalizationClaimExpiresAtUtc is null && FinalizationClaimExtendedAtUtc is null)
            return FinalizationClaimState.Unclaimed;
        if (FinalizationClaimTokenHash is { Length: Sha256ByteLength } &&
            FinalizationClaimExpiresAtUtc is { } expiresAtUtc &&
            FinalizationClaimExtendedAtUtc is not null)
            return expiresAtUtc > nowUtc.ToUniversalTime() ? FinalizationClaimState.Live : FinalizationClaimState.Expired;
        return FinalizationClaimState.Malformed;
    }

    /// <summary>
    /// Whether a finalizer may take (or retake) ownership now: Finalizing, attempts remaining,
    /// strictly before the deadline, and a canonical unclaimed or expired claim.
    /// </summary>
    public bool CanClaimFinalization(DateTimeOffset nowUtc, int maximumFinalizationAttempts, TimeSpan maximumFinalizationDuration) =>
        Status == VisionJobStatus.Finalizing &&
        maximumFinalizationAttempts >= 1 &&
        FinalizationAttemptCount < maximumFinalizationAttempts &&
        IsBeforeFinalizationDeadline(nowUtc, maximumFinalizationDuration) &&
        FinalizationClaimStateAt(nowUtc) is FinalizationClaimState.Unclaimed or FinalizationClaimState.Expired;

    /// <summary>
    /// A finalizer takes (or, after expiry, retakes) ownership. Every claim rotates the token,
    /// so a claimant that lost its claim can no longer prove ownership with the old token. The
    /// transition proves the deadline itself: a caller that bypassed the SQL pre-filter is refused
    /// here (F3 plan §8.6).
    /// </summary>
    public void ClaimFinalization(
        byte[] claimTokenHash,
        DateTimeOffset nowUtc,
        TimeSpan claimDuration,
        int maximumFinalizationAttempts,
        TimeSpan maximumFinalizationDuration)
    {
        if (!CanClaimFinalization(nowUtc, maximumFinalizationAttempts, maximumFinalizationDuration)) throw Invalid();
        if (claimTokenHash is not { Length: Sha256ByteLength } || claimDuration <= TimeSpan.Zero) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        FinalizationAttemptCount++;
        FinalizationClaimTokenHash = [.. claimTokenHash];
        FinalizationClaimExpiresAtUtc = now.Add(claimDuration);
        FinalizationClaimExtendedAtUtc = now;
    }

    /// <summary>
    /// Whether <paramref name="claimToken"/> is the live finalizer claim of this job. Ownership is
    /// independent of the deadline: a claim that was live when the deadline passed stays live until
    /// its granted expiry and may still publish or fail (F3 plan §5.4).
    /// </summary>
    public bool FinalizationOwnedBy(ReadOnlySpan<byte> claimToken, DateTimeOffset nowUtc)
    {
        if (Status != VisionJobStatus.Finalizing) return false;
        if (FinalizationClaimStateAt(nowUtc) != FinalizationClaimState.Live) return false;
        if (claimToken.Length != FinalizationClaimTokenByteLength) return false;

        Span<byte> actual = stackalloc byte[Sha256ByteLength];
        SHA256.HashData(claimToken, actual);
        return CryptographicOperations.FixedTimeEquals(actual, FinalizationClaimTokenHash);
    }

    /// <summary>
    /// The live claimant keeps ownership across a long seal; a lost claim cannot be extended, and
    /// neither can a live one at or after the deadline: repeated extension can never push a claim
    /// indefinitely past <c>MaximumFinalizationDuration</c> (F3 plan §5.4).
    /// </summary>
    public void ExtendFinalizationClaim(
        ReadOnlySpan<byte> claimToken,
        DateTimeOffset nowUtc,
        TimeSpan extension,
        TimeSpan maximumFinalizationDuration)
    {
        if (!FinalizationOwnedBy(claimToken, nowUtc) || extension <= TimeSpan.Zero) throw Invalid();
        if (!IsBeforeFinalizationDeadline(nowUtc, maximumFinalizationDuration)) throw Invalid();
        var now = nowUtc.ToUniversalTime();
        FinalizationClaimExpiresAtUtc = now.Add(extension);
        FinalizationClaimExtendedAtUtc = now;
    }

    /// <summary>
    /// The live claimant gives its claim up now (a transient failure it will not retry itself), so
    /// the next cycle may reclaim without waiting out the granted duration. The hash stays: the
    /// row is a canonical expired claim, never an unclaimed one, and the old token proves nothing.
    /// </summary>
    public void ReleaseFinalizationClaim(ReadOnlySpan<byte> claimToken, DateTimeOffset nowUtc)
    {
        if (!FinalizationOwnedBy(claimToken, nowUtc)) throw Invalid();
        var now = nowUtc.ToUniversalTime();
        FinalizationClaimExpiresAtUtc = now;
        FinalizationClaimExtendedAtUtc = now;
    }

    /// <summary>A transient finalization error, kept for the next claimant and the operator.</summary>
    public void NoteFinalizationError(string code)
    {
        if (Status != VisionJobStatus.Finalizing || !IsFinalizationFailureCode(code)) throw Invalid();
        FinalizationLastErrorCode = code;
    }

    /// <summary>
    /// <c>Finalizing → Completed</c>, by the platform finalizer that holds the live claim at
    /// <paramref name="nowUtc"/>. The worker lease plays no part. A claimant whose claim expired
    /// or was rotated away cannot publish: the transition verifies the token itself, like
    /// <see cref="ExtendFinalizationClaim"/>, instead of trusting the caller to have checked.
    /// </summary>
    public void CompleteFinalization(ReadOnlySpan<byte> claimToken, DateTimeOffset nowUtc)
    {
        if (!FinalizationOwnedBy(claimToken, nowUtc)) throw Invalid();
        if (nowUtc.ToUniversalTime() < FinalizationAcceptedAtUtc) throw Invalid();

        Status = VisionJobStatus.Completed;
        ProgressPercent = 100;
        CompletedAtUtc = nowUtc.ToUniversalTime();
        ClearFinalizationClaim();
    }

    /// <summary>
    /// <c>Finalizing → Failed</c>, by the platform finalizer that holds the live claim at
    /// <paramref name="nowUtc"/>: a deterministic finalization failure, or transient failures
    /// exhausted. Fenced like <see cref="CompleteFinalization"/>: a claimant whose claim expired
    /// or was rotated away cannot terminate the recovery attempt that superseded it. The code is
    /// finalization-scoped, never a worker inference code, and the hand-off facts stay for audit.
    /// </summary>
    public void FailFinalization(ReadOnlySpan<byte> claimToken, string code, string? details, DateTimeOffset nowUtc)
    {
        if (!FinalizationOwnedBy(claimToken, nowUtc)) throw Invalid();
        if (!IsFinalizationFailureCode(code) || details?.Length > 4000) throw Invalid();

        Status = VisionJobStatus.Failed;
        FailureCode = code;
        FailureDetails = details;
        FinalizationLastErrorCode = code;
        CompletedAtUtc = nowUtc.ToUniversalTime();
        ClearFinalizationClaim();
    }

    /// <summary>
    /// <c>Finalizing → Failed</c> by platform reconciliation, never by a claimant (F3 plan §5.3,
    /// §7.5). Tokenless and failure-only: it proves from the row alone that no live claim exists
    /// (a canonical unclaimed or expired claim; a live or malformed one throws) and that no further
    /// claim is permitted (attempts or the absolute deadline exhausted). It cannot publish, and it
    /// is the only way the final permitted claimant's crash ends. Hand-off facts stay for audit.
    /// </summary>
    public void ExhaustFinalization(DateTimeOffset nowUtc, int maximumFinalizationAttempts, TimeSpan maximumFinalizationDuration)
    {
        if (Status != VisionJobStatus.Finalizing || FinalizationAcceptedAtUtc is null) throw Invalid();
        if (maximumFinalizationAttempts < 1 || maximumFinalizationDuration <= TimeSpan.Zero) throw Invalid();
        if (FinalizationClaimStateAt(nowUtc) is not (FinalizationClaimState.Unclaimed or FinalizationClaimState.Expired)) throw Invalid();
        var attemptsExhausted = FinalizationAttemptCount >= maximumFinalizationAttempts;
        var durationExhausted = !IsBeforeFinalizationDeadline(nowUtc, maximumFinalizationDuration);
        if (!attemptsExhausted && !durationExhausted) throw Invalid();

        Status = VisionJobStatus.Failed;
        FailureCode = FinalizationExhaustedFailureCode;
        FailureDetails = null;
        CompletedAtUtc = nowUtc.ToUniversalTime();
        ClearFinalizationClaim();
    }

    private void ClearFinalizationClaim()
    {
        FinalizationClaimTokenHash = null;
        FinalizationClaimExpiresAtUtc = null;
        FinalizationClaimExtendedAtUtc = null;
    }

    public static bool IsFinalizationFailureCode(string? code) =>
        code is { Length: <= 64 } &&
        code.StartsWith(FinalizationFailureCodePrefix, StringComparison.Ordinal) &&
        code.Length > FinalizationFailureCodePrefix.Length &&
        code.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '_');

    public Guid Id { get; private set; }
    public Guid ProcessingRunId { get; private set; }
    public string Pipeline { get; private set; } = string.Empty;
    public VisionJobStatus Status { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset AvailableAtUtc { get; private set; }
    public string? LeaseOwner { get; private set; }
    public byte[]? LeaseTokenHash { get; private set; }
    public DateTimeOffset? LeaseExpiresAtUtc { get; private set; }
    public int AttemptCount { get; private set; }
    public double ProgressPercent { get; private set; }
    public DateTimeOffset? LastHeartbeatUtc { get; private set; }
    public DateTimeOffset? CompletedAtUtc { get; private set; }
    public string? FailureCode { get; private set; }
    public string? FailureDetails { get; private set; }
    public string? CompletionDigest { get; private set; }
    public DateTimeOffset? FinalizationAcceptedAtUtc { get; private set; }
    public int FinalizationAttemptCount { get; private set; }
    public byte[]? FinalizationClaimTokenHash { get; private set; }
    public DateTimeOffset? FinalizationClaimExpiresAtUtc { get; private set; }
    public DateTimeOffset? FinalizationClaimExtendedAtUtc { get; private set; }
    public string? FinalizationLastErrorCode { get; private set; }

    private void RequireValidLease(string workerId, bool leaseTokenMatches, DateTimeOffset nowUtc)
    {
        if (!WorkerIdRules.IsCanonical(workerId) || Status != VisionJobStatus.Leased ||
            !string.Equals(LeaseOwner, workerId, StringComparison.Ordinal) ||
            !leaseTokenMatches || LeaseExpiresAtUtc <= nowUtc.ToUniversalTime()) throw Invalid();
    }

    public void Exhaust(DateTimeOffset nowUtc)
    {
        if (Status is not (VisionJobStatus.Queued or VisionJobStatus.Leased)) throw Invalid();
        Status = VisionJobStatus.Failed;
        FailureCode = "vision_job_attempts_exhausted";
        FailureDetails = null;
        CompletedAtUtc = nowUtc.ToUniversalTime();
        LeaseOwner = null;
        LeaseTokenHash = null;
        LeaseExpiresAtUtc = null;
        LastHeartbeatUtc = null;
        CompletionDigest = null;
    }

    internal static bool IsCanonicalSha256(string value) =>
        value is { Length: 64 } && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static DomainValidationException Invalid() =>
        new("vision_job_transition_invalid", "The vision job operation is invalid.");
}
