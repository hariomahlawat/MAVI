using Mavi.Domain.Common;
using Mavi.Domain.Processing;

namespace Mavi.Domain.Embeddings;

public enum EmbeddingAnalysisStatus
{
    Queued,
    Running,
    Completed,
    Failed,
    Superseded,
}

public enum EmbeddingFailOutcome
{
    Requeued,
    Failed,
}

/// <summary>The lifecycle bounds one host applies to every embedding unit.</summary>
public sealed record EmbeddingLeasePolicy(
    TimeSpan LeaseDuration,
    TimeSpan HeartbeatExtension,
    int MaximumAttempts,
    TimeSpan MaximumAnalysisDuration);

/// <summary>The immutable identity a unit is queued under (ADR-021 §3), fingerprint included.</summary>
public sealed record EmbeddingIdentityFields(
    string Fingerprint,
    string ModelId,
    string ModelVersion,
    string ManifestSha256,
    int Dimension,
    string PipelineId,
    string PipelineVersion,
    string PipelineSha256);

/// <summary>The facts a successful completion publishes onto the header.</summary>
public sealed record EmbeddingCompletion(
    string CompletionDigest,
    long VisibilitySequence,
    string ProvenanceJson,
    int TracksEmbedded,
    int TracksUnavailable);

/// <summary>
/// One embedding analysis: a ProcessingRun's Person and Vehicle Tracks embedded under one immutable identity
/// (ADR-021 §3; the ADR-013 §9 lease shape).
/// </summary>
/// <remarks>
/// <para>
/// The lease state machine repeats the plate analysis's (ADR-013 alternative G: capability-specific, not a
/// generic job) with one simplification ADR-021 records: there is no sealed artefact, so completion is a single
/// fenced publication. It is fenced by an <i>active</i> lease (owner, capability, attempt and expiry) and
/// commits in one transaction.
/// </para>
/// <para>
/// Nothing here refers to the ProcessingRun beyond its id: an embedding failure, exhaustion or deadline ends
/// this unit and never touches the run, its Tracks or another role's units (ADR-021 §3, register C5.2).
/// </para>
/// </remarks>
public sealed class EmbeddingAnalysis
{
    public const int LeaseTokenHashLength = 32;
    public const int MaximumFailureDetailsLength = 2000;
    public const string StaleAttemptCode = "embedding_attempt_stale";
    public const string DeadlineExceededCode = "embedding_deadline_exceeded";
    public const string AttemptsExhaustedCode = "embedding_attempts_exhausted";
    public const string NotRunningCode = "embedding_not_running";
    public const string LeaseInvalidCode = "embedding_lease_invalid";
    public const string TransitionInvalidCode = "embedding_transition_invalid";

    private EmbeddingAnalysis() { }

    public static EmbeddingAnalysis Queue(Guid processingRunId, EmbeddingIdentityFields identity, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(identity);
        if (processingRunId == Guid.Empty || !IsValid(identity)) throw Invalid();
        return new EmbeddingAnalysis
        {
            Id = Guid.CreateVersion7(),
            ProcessingRunId = processingRunId,
            IdentityFingerprint = identity.Fingerprint,
            ModelId = identity.ModelId,
            ModelVersion = identity.ModelVersion,
            ManifestSha256 = identity.ManifestSha256,
            Dimension = identity.Dimension,
            PipelineId = identity.PipelineId,
            PipelineVersion = identity.PipelineVersion,
            PipelineSha256 = identity.PipelineSha256,
            Status = EmbeddingAnalysisStatus.Queued,
            QueuedAtUtc = nowUtc.ToUniversalTime(),
        };
    }

    // --- Deadline and claims ----------------------------------------------------------

    public DateTimeOffset? Deadline(TimeSpan maximumAnalysisDuration) =>
        FirstClaimedAtUtc is { } first && maximumAnalysisDuration > TimeSpan.Zero ? first.Add(maximumAnalysisDuration) : null;

    public bool IsDeadlineExceeded(DateTimeOffset nowUtc, TimeSpan maximumAnalysisDuration) =>
        Deadline(maximumAnalysisDuration) is { } deadline && nowUtc.ToUniversalTime() >= deadline;

    public bool HasLiveLease(DateTimeOffset nowUtc) =>
        Status == EmbeddingAnalysisStatus.Running && LeaseExpiresAtUtc is { } expiry && expiry > nowUtc.ToUniversalTime();

    public bool CanClaim(DateTimeOffset nowUtc, EmbeddingLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (policy.MaximumAttempts < 1 || AttemptCount >= policy.MaximumAttempts) return false;
        if (IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration)) return false;
        return Status switch
        {
            EmbeddingAnalysisStatus.Queued => true,
            EmbeddingAnalysisStatus.Running => !HasLiveLease(nowUtc),
            _ => false,
        };
    }

    /// <summary>A first claim or a reclaim: a new attempt, a new capability, a new lease.</summary>
    public void Claim(string workerId, byte[] leaseTokenHash, DateTimeOffset nowUtc, EmbeddingLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (!CanClaim(nowUtc, policy) || !WorkerIdRules.IsCanonical(workerId) ||
            leaseTokenHash is not { Length: LeaseTokenHashLength } || policy.LeaseDuration <= TimeSpan.Zero ||
            policy.MaximumAnalysisDuration <= TimeSpan.Zero)
            throw Invalid();

        var now = nowUtc.ToUniversalTime();
        FirstClaimedAtUtc ??= now;
        Status = EmbeddingAnalysisStatus.Running;
        AttemptCount++;
        LeaseOwner = workerId;
        LeaseTokenHash = [.. leaseTokenHash];
        LeaseExpiresAtUtc = CapAtDeadline(now.Add(policy.LeaseDuration), policy);
        LastHeartbeatUtc = null;
    }

    // --- Lease-scoped operations -----------------------------------------------------

    public bool IsOwnedBy(string workerId, bool tokenMatches, int attemptCount) =>
        Status == EmbeddingAnalysisStatus.Running &&
        tokenMatches &&
        LeaseTokenHash is not null &&
        attemptCount == AttemptCount &&
        string.Equals(LeaseOwner, workerId, StringComparison.Ordinal);

    public bool HoldsActiveLease(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc) =>
        IsOwnedBy(workerId, tokenMatches, attemptCount) && HasLiveLease(nowUtc);

    public void Heartbeat(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc, EmbeddingLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        RequireActiveLease(workerId, tokenMatches, attemptCount, nowUtc);
        if (IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration))
            throw new DomainValidationException(DeadlineExceededCode, "The analysis has exceeded its maximum duration.");
        if (policy.HeartbeatExtension <= TimeSpan.Zero) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        LastHeartbeatUtc = now;
        var proposed = CapAtDeadline(now.Add(policy.HeartbeatExtension), policy);
        if (LeaseExpiresAtUtc is not { } current || proposed > current) LeaseExpiresAtUtc = proposed;
    }

    public EmbeddingFailOutcome FailAttempt(
        string workerId,
        bool tokenMatches,
        int attemptCount,
        string failureCode,
        bool retryable,
        string? failureDetails,
        DateTimeOffset nowUtc,
        EmbeddingLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        RequireActiveLease(workerId, tokenMatches, attemptCount, nowUtc);
        if (!IsFailureCode(failureCode) || failureDetails?.Length > MaximumFailureDetailsLength) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        LastFailedWorkerId = LeaseOwner;
        LastFailedAttempt = AttemptCount;
        LastFailedTokenHash = LeaseTokenHash;
        LastFailedCode = failureCode;
        LastFailedDetails = failureDetails;
        ClearLease();
        if (retryable && AttemptCount < policy.MaximumAttempts && !IsDeadlineExceeded(now, policy.MaximumAnalysisDuration))
        {
            Status = EmbeddingAnalysisStatus.Queued;
            LastFailedOutcome = EmbeddingFailOutcome.Requeued;
            return EmbeddingFailOutcome.Requeued;
        }

        Terminate(failureCode, failureDetails, now);
        LastFailedOutcome = EmbeddingFailOutcome.Failed;
        return EmbeddingFailOutcome.Failed;
    }

    /// <summary>An exact duplicate of the last recorded worker failure (an ambiguous HTTP outcome replayed).</summary>
    public bool IsRecordedFailureReplay(string workerId, bool lastFailedTokenMatches, int attemptCount, string failureCode, string? failureDetails) =>
        lastFailedTokenMatches &&
        LastFailedTokenHash is not null &&
        LastFailedAttempt == attemptCount &&
        string.Equals(LastFailedWorkerId, workerId, StringComparison.Ordinal) &&
        string.Equals(LastFailedCode, failureCode, StringComparison.Ordinal) &&
        string.Equals(LastFailedDetails, failureDetails, StringComparison.Ordinal);

    // --- Platform-owned terminal transitions ---------------------------------------------

    public bool IsExhausted(DateTimeOffset nowUtc, EmbeddingLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        return Status is EmbeddingAnalysisStatus.Running or EmbeddingAnalysisStatus.Queued &&
               AttemptCount >= policy.MaximumAttempts && !HasLiveLease(nowUtc);
    }

    public bool IsDeadlineEnforceable(DateTimeOffset nowUtc, EmbeddingLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        return Status is EmbeddingAnalysisStatus.Queued or EmbeddingAnalysisStatus.Running &&
               IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration) &&
               !HasLiveLease(nowUtc);
    }

    public void FailDeadlineExceeded(DateTimeOffset nowUtc, EmbeddingLeasePolicy policy)
    {
        if (!IsDeadlineEnforceable(nowUtc, policy)) throw Invalid();
        ClearLease();
        Terminate(DeadlineExceededCode, null, nowUtc.ToUniversalTime());
    }

    public void FailAttemptsExhausted(DateTimeOffset nowUtc, EmbeddingLeasePolicy policy)
    {
        if (!IsExhausted(nowUtc, policy)) throw Invalid();
        ClearLease();
        Terminate(AttemptsExhaustedCode, null, nowUtc.ToUniversalTime());
    }

    // --- Completion ----------------------------------------------------------------------

    /// <summary>
    /// Publish, fenced by an active lease. <paramref name="isPreferred"/> is whether this unit's identity is the
    /// currently preferred one; an obsolete identity completes directly as history.
    /// </summary>
    public void Complete(
        string workerId,
        bool tokenMatches,
        int attemptCount,
        DateTimeOffset completedAtUtc,
        EmbeddingCompletion completion,
        bool isPreferred)
    {
        ArgumentNullException.ThrowIfNull(completion);
        if (!IsOwnedBy(workerId, tokenMatches, attemptCount))
            throw new DomainValidationException(StaleAttemptCode, "The attempt no longer owns the analysis.");
        if (!HasLiveLease(completedAtUtc))
            throw new DomainValidationException(LeaseInvalidCode, "The lease expired before the completion was published.");
        if (!CanonicalSha256.IsCanonical(completion.CompletionDigest) || completion.VisibilitySequence < 1 ||
            string.IsNullOrWhiteSpace(completion.ProvenanceJson) || completion.TracksEmbedded < 0 || completion.TracksUnavailable < 0)
            throw Invalid();

        Status = isPreferred ? EmbeddingAnalysisStatus.Completed : EmbeddingAnalysisStatus.Superseded;
        CompletionDigest = completion.CompletionDigest;
        VisibilitySequence = completion.VisibilitySequence;
        ProvenanceJson = completion.ProvenanceJson;
        TracksEmbedded = completion.TracksEmbedded;
        TracksUnavailable = completion.TracksUnavailable;
        CompletedAtUtc = completedAtUtc.ToUniversalTime();
        // The capability hash is kept to authenticate an exact replay; the lease is over.
        LeaseExpiresAtUtc = null;
    }

    /// <summary>A newer preferred completion moved currency; the facts stay exactly as committed.</summary>
    public void Supersede()
    {
        if (Status != EmbeddingAnalysisStatus.Completed) throw Invalid();
        Status = EmbeddingAnalysisStatus.Superseded;
    }

    public bool IsFactBearing => Status is EmbeddingAnalysisStatus.Completed or EmbeddingAnalysisStatus.Superseded;

    public bool CanAuthenticateCompletionReplay(string workerId, bool tokenMatches, int attemptCount) =>
        IsFactBearing &&
        CompletionDigest is not null &&
        tokenMatches &&
        LeaseTokenHash is not null &&
        attemptCount == AttemptCount &&
        string.Equals(LeaseOwner, workerId, StringComparison.Ordinal);

    // --- Properties ----------------------------------------------------------------------

    public Guid Id { get; private set; }
    public Guid ProcessingRunId { get; private set; }
    public string IdentityFingerprint { get; private set; } = string.Empty;
    public string ModelId { get; private set; } = string.Empty;
    public string ModelVersion { get; private set; } = string.Empty;
    public string ManifestSha256 { get; private set; } = string.Empty;
    public int Dimension { get; private set; }
    public string PipelineId { get; private set; } = string.Empty;
    public string PipelineVersion { get; private set; } = string.Empty;
    public string PipelineSha256 { get; private set; } = string.Empty;
    public EmbeddingAnalysisStatus Status { get; private set; }
    public int AttemptCount { get; private set; }
    public string? LeaseOwner { get; private set; }
    public byte[]? LeaseTokenHash { get; private set; }
    public DateTimeOffset? LeaseExpiresAtUtc { get; private set; }
    public DateTimeOffset? LastHeartbeatUtc { get; private set; }
    public DateTimeOffset QueuedAtUtc { get; private set; }
    public DateTimeOffset? FirstClaimedAtUtc { get; private set; }
    public DateTimeOffset? CompletedAtUtc { get; private set; }
    public string? FailureCode { get; private set; }
    public string? FailureDetails { get; private set; }
    public string? LastFailedWorkerId { get; private set; }
    public int? LastFailedAttempt { get; private set; }
    public byte[]? LastFailedTokenHash { get; private set; }
    public string? LastFailedCode { get; private set; }
    public string? LastFailedDetails { get; private set; }
    public EmbeddingFailOutcome? LastFailedOutcome { get; private set; }
    public string? CompletionDigest { get; private set; }
    public string? ProvenanceJson { get; private set; }
    public int TracksEmbedded { get; private set; }
    public int TracksUnavailable { get; private set; }
    public long? VisibilitySequence { get; private set; }

    public EmbeddingIdentityFields Identity => new(
        IdentityFingerprint, ModelId, ModelVersion, ManifestSha256, Dimension, PipelineId, PipelineVersion, PipelineSha256);

    // --- Helpers ------------------------------------------------------------------------

    private void RequireActiveLease(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc)
    {
        if (Status != EmbeddingAnalysisStatus.Running)
            throw new DomainValidationException(NotRunningCode, "The analysis is not running.");
        if (!HoldsActiveLease(workerId, tokenMatches, attemptCount, nowUtc))
            throw new DomainValidationException(LeaseInvalidCode, "The lease is not held by this attempt.");
    }

    private DateTimeOffset CapAtDeadline(DateTimeOffset expiry, EmbeddingLeasePolicy policy) =>
        Deadline(policy.MaximumAnalysisDuration) is { } deadline && deadline < expiry ? deadline : expiry;

    private void ClearLease()
    {
        LeaseOwner = null;
        LeaseTokenHash = null;
        LeaseExpiresAtUtc = null;
        LastHeartbeatUtc = null;
    }

    private void Terminate(string code, string? details, DateTimeOffset nowUtc)
    {
        Status = EmbeddingAnalysisStatus.Failed;
        FailureCode = code;
        FailureDetails = details;
        CompletedAtUtc = nowUtc;
    }

    public static bool IsFailureCode(string? value) =>
        value is { Length: >= 1 and <= 64 } &&
        value[0] is >= 'a' and <= 'z' &&
        value.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '_');

    private static bool IsValid(EmbeddingIdentityFields identity) =>
        CanonicalSha256.IsCanonical(identity.Fingerprint) &&
        identity.ModelId is { Length: >= 1 and <= 128 } &&
        identity.ModelVersion is { Length: >= 1 and <= 64 } &&
        CanonicalSha256.IsCanonical(identity.ManifestSha256) &&
        identity.Dimension is >= 1 and <= 4096 &&
        identity.PipelineId is { Length: >= 1 and <= 64 } &&
        identity.PipelineVersion is { Length: >= 5 and <= 64 } &&
        CanonicalSha256.IsCanonical(identity.PipelineSha256);

    private static DomainValidationException Invalid() =>
        new(TransitionInvalidCode, "The embedding analysis operation is invalid.");
}
