using Mavi.Domain.Common;
using Mavi.Domain.Processing;

namespace Mavi.Domain.VisualAttributes;

public enum VisualAttributeAnalysisStatus
{
    Queued,
    Running,
    Completed,
    Failed,
    Superseded,
}

public enum VisualAttributeFailOutcome
{
    Requeued,
    Failed,
}

/// <summary>The lifecycle bounds one host applies to every unit (S2b plan §8).</summary>
public sealed record VisualAttributeLeasePolicy(
    TimeSpan LeaseDuration,
    TimeSpan HeartbeatExtension,
    int MaximumAttempts,
    TimeSpan MaximumAnalysisDuration);

/// <summary>The immutable identity a unit is queued under (ADR-013 §11), fingerprint included.</summary>
public sealed record VisualAttributeIdentityFields(
    string Fingerprint,
    string AttributeSchemaId,
    string AttributeSchemaVersion,
    string AttributeSchemaSha256,
    string PipelineId,
    string PipelineVersion,
    string AggregationPolicyId,
    string AggregationPolicyVersion,
    string AggregationPolicySha256,
    string CapabilitiesCanonical,
    string ParametersSha256);

/// <summary>The facts a successful Phase C publishes onto the header.</summary>
public sealed record VisualAttributeCompletion(
    string CompletionDigest,
    long VisibilitySequence,
    Guid PredictionArtifactId,
    string ProvenanceJson,
    int TracksAnalysed,
    int TracksUnavailable,
    int AttributesObserved,
    int AttributesUnknown);

public sealed record VisualAttributeFailResult(VisualAttributeFailOutcome Outcome, VisualAttributeAttemptFailure Record);

/// <summary>
/// One Visual Attribute analysis: a ProcessingRun analysed under one immutable identity
/// (ADR-013 §9, §11). Capability-specific by design; it shares transport and fencing
/// primitives with VisionJob, never a generic job table.
/// </summary>
/// <remarks>
/// <para>
/// <b>Two fences, deliberately different.</b> Every lease-scoped operation — heartbeat,
/// evidence read, upload, failure and Phase A of completion — follows the VisionJob shape:
/// the lease must be unexpired and the worker, capability and attempt must match. Phase C of
/// completion is fenced by <i>ownership</i> alone (<see cref="Complete"/>): a validated
/// completion whose lease expired while it sealed may still publish, as long as no reclaim
/// changed hands in the meantime (ADR-013 implementation amendment 2026-09-28, item 4).
/// </para>
/// <para>
/// <b>Attempts</b> are consumed at claim. A retryable failure returns the unit to
/// <see cref="VisualAttributeAnalysisStatus.Queued"/> while attempts and time remain; a
/// terminal one, exhaustion and the deadline end it as
/// <see cref="VisualAttributeAnalysisStatus.Failed"/>.
/// </para>
/// <para>
/// <b>The deadline</b> is <c>FirstClaimedAtUtc + MaximumAnalysisDuration</c>. It exists only
/// once a unit has been claimed, so work queued while no attributes worker is deployed never
/// fails on the clock. No lease ever extends past it.
/// </para>
/// </remarks>
public sealed class VisualAttributeAnalysis
{
    public const int LeaseTokenHashLength = 32;
    public const int MaximumFailureDetailsLength = 4000;
    public const string StaleAttemptCode = "visual_attribute_attempt_stale";
    public const string DeadlineExceededCode = "visual_attribute_deadline_exceeded";
    public const string AttemptsExhaustedCode = "visual_attribute_attempts_exhausted";

    private VisualAttributeAnalysis() { }

    public static VisualAttributeAnalysis Queue(Guid processingRunId, VisualAttributeIdentityFields identity, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(identity);
        if (processingRunId == Guid.Empty || !IsValid(identity)) throw Invalid();
        return new VisualAttributeAnalysis
        {
            Id = Guid.CreateVersion7(),
            ProcessingRunId = processingRunId,
            IdentityFingerprint = identity.Fingerprint,
            AttributeSchemaId = identity.AttributeSchemaId,
            AttributeSchemaVersion = identity.AttributeSchemaVersion,
            AttributeSchemaSha256 = identity.AttributeSchemaSha256,
            PipelineId = identity.PipelineId,
            PipelineVersion = identity.PipelineVersion,
            AggregationPolicyId = identity.AggregationPolicyId,
            AggregationPolicyVersion = identity.AggregationPolicyVersion,
            AggregationPolicySha256 = identity.AggregationPolicySha256,
            CapabilitiesCanonical = identity.CapabilitiesCanonical,
            ParametersSha256 = identity.ParametersSha256,
            Status = VisualAttributeAnalysisStatus.Queued,
            QueuedAtUtc = nowUtc.ToUniversalTime(),
        };
    }

    // --- Deadline and claims ----------------------------------------------------------

    public DateTimeOffset? Deadline(TimeSpan maximumAnalysisDuration) =>
        FirstClaimedAtUtc is { } first && maximumAnalysisDuration > TimeSpan.Zero ? first.Add(maximumAnalysisDuration) : null;

    /// <summary>Only a claimed unit has a deadline; <c>now ≥ deadline</c> is exceeded.</summary>
    public bool IsDeadlineExceeded(DateTimeOffset nowUtc, TimeSpan maximumAnalysisDuration) =>
        Deadline(maximumAnalysisDuration) is { } deadline && nowUtc.ToUniversalTime() >= deadline;

    public bool HasLiveLease(DateTimeOffset nowUtc) =>
        Status == VisualAttributeAnalysisStatus.Running && LeaseExpiresAtUtc is { } expiry && expiry > nowUtc.ToUniversalTime();

    public bool CanClaim(DateTimeOffset nowUtc, VisualAttributeLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (policy.MaximumAttempts < 1 || AttemptCount >= policy.MaximumAttempts) return false;
        if (IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration)) return false;
        return Status switch
        {
            VisualAttributeAnalysisStatus.Queued => true,
            VisualAttributeAnalysisStatus.Running => !HasLiveLease(nowUtc),
            _ => false,
        };
    }

    /// <summary>A first claim or a reclaim: a new attempt, a new capability, a new lease.</summary>
    public void Claim(string workerId, byte[] leaseTokenHash, DateTimeOffset nowUtc, VisualAttributeLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (!CanClaim(nowUtc, policy) || !WorkerIdRules.IsCanonical(workerId) ||
            leaseTokenHash is not { Length: LeaseTokenHashLength } || policy.LeaseDuration <= TimeSpan.Zero ||
            policy.MaximumAnalysisDuration <= TimeSpan.Zero)
            throw Invalid();

        var now = nowUtc.ToUniversalTime();
        FirstClaimedAtUtc ??= now;
        Status = VisualAttributeAnalysisStatus.Running;
        AttemptCount++;
        LeaseOwner = workerId;
        LeaseTokenHash = [.. leaseTokenHash];
        LeaseExpiresAtUtc = CapAtDeadline(now.Add(policy.LeaseDuration), policy);
        LastHeartbeatUtc = null;
        CompletionDigest = null;
    }

    // --- Lease-scoped operations -----------------------------------------------------

    /// <summary>Running and presented by the current worker, capability and attempt — expiry not consulted.</summary>
    public bool IsOwnedBy(string workerId, bool tokenMatches, int attemptCount) =>
        Status == VisualAttributeAnalysisStatus.Running &&
        tokenMatches &&
        LeaseTokenHash is not null &&
        attemptCount == AttemptCount &&
        string.Equals(LeaseOwner, workerId, StringComparison.Ordinal);

    /// <summary>The VisionJob-shape fence of every lease-scoped operation: owned and unexpired.</summary>
    public bool HoldsActiveLease(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc) =>
        IsOwnedBy(workerId, tokenMatches, attemptCount) && HasLiveLease(nowUtc);

    public void Heartbeat(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc, VisualAttributeLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        RequireActiveLease(workerId, tokenMatches, attemptCount, nowUtc);
        if (IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration))
            throw new DomainValidationException(DeadlineExceededCode, "The analysis has exceeded its maximum duration.");
        if (policy.HeartbeatExtension <= TimeSpan.Zero) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        LastHeartbeatUtc = now;
        LeaseExpiresAtUtc = CapAtDeadline(now.Add(policy.HeartbeatExtension), policy);
    }

    public VisualAttributeFailResult FailAttempt(
        string workerId,
        bool tokenMatches,
        int attemptCount,
        string failureCode,
        bool retryable,
        string? failureDetails,
        DateTimeOffset nowUtc,
        VisualAttributeLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        RequireActiveLease(workerId, tokenMatches, attemptCount, nowUtc);
        if (!IsFailureCode(failureCode) || failureDetails?.Length > MaximumFailureDetailsLength) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        var record = VisualAttributeAttemptFailure.Create(Id, AttemptCount, failureCode, retryable, failureDetails, now);
        // Kept so that an exact duplicate of this transition, after an ambiguous HTTP outcome,
        // authenticates against the capability that made it — and nothing later.
        LastFailedWorkerId = LeaseOwner;
        LastFailedAttempt = AttemptCount;
        LastFailedTokenHash = LeaseTokenHash;
        LastFailedCode = failureCode;
        LastFailedDetails = failureDetails;
        ClearLease();
        var requeue = retryable && AttemptCount < policy.MaximumAttempts && !IsDeadlineExceeded(now, policy.MaximumAnalysisDuration);
        if (requeue)
        {
            Status = VisualAttributeAnalysisStatus.Queued;
            LastFailedOutcome = VisualAttributeFailOutcome.Requeued;
            return new VisualAttributeFailResult(VisualAttributeFailOutcome.Requeued, record);
        }

        Terminate(failureCode, failureDetails, now);
        LastFailedOutcome = VisualAttributeFailOutcome.Failed;
        return new VisualAttributeFailResult(VisualAttributeFailOutcome.Failed, record);
    }

    /// <summary>
    /// Whether a failure request is an exact duplicate of the last recorded worker failure: the
    /// same worker, capability, attempt, code and details. A later attempt's state is never
    /// touched by it (S2b plan §9).
    /// </summary>
    public bool IsRecordedFailureReplay(string workerId, bool lastFailedTokenMatches, int attemptCount, string failureCode, string? failureDetails) =>
        lastFailedTokenMatches &&
        LastFailedTokenHash is not null &&
        LastFailedAttempt == attemptCount &&
        string.Equals(LastFailedWorkerId, workerId, StringComparison.Ordinal) &&
        string.Equals(LastFailedCode, failureCode, StringComparison.Ordinal) &&
        string.Equals(LastFailedDetails, failureDetails, StringComparison.Ordinal);

    // --- Platform-owned terminal transitions ---------------------------------------------

    public bool IsExhausted(DateTimeOffset nowUtc, VisualAttributeLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        return Status == VisualAttributeAnalysisStatus.Running && AttemptCount >= policy.MaximumAttempts && !HasLiveLease(nowUtc);
    }

    /// <summary>The platform ends a claimed unit that reached its deadline, whatever its lease.</summary>
    public void FailDeadlineExceeded(DateTimeOffset nowUtc, VisualAttributeLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (Status is not (VisualAttributeAnalysisStatus.Queued or VisualAttributeAnalysisStatus.Running) ||
            !IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration))
            throw Invalid();
        ClearLease();
        Terminate(DeadlineExceededCode, null, nowUtc.ToUniversalTime());
    }

    /// <summary>The platform ends a unit whose last permitted attempt's lease expired unfinished.</summary>
    public void FailAttemptsExhausted(DateTimeOffset nowUtc, VisualAttributeLeasePolicy policy)
    {
        if (!IsExhausted(nowUtc, policy)) throw Invalid();
        ClearLease();
        Terminate(AttemptsExhaustedCode, null, nowUtc.ToUniversalTime());
    }

    // --- Completion ----------------------------------------------------------------------

    /// <summary>
    /// Phase C: publish, fenced by ownership (status, worker, capability, attempt), not by
    /// the clock. <paramref name="isPreferred"/> is whether this unit's identity is the
    /// currently preferred one; an obsolete identity completes directly as history.
    /// </summary>
    public void Complete(
        string workerId,
        bool tokenMatches,
        int attemptCount,
        DateTimeOffset completedAtUtc,
        VisualAttributeCompletion completion,
        bool isPreferred)
    {
        ArgumentNullException.ThrowIfNull(completion);
        if (!IsOwnedBy(workerId, tokenMatches, attemptCount))
            throw new DomainValidationException(StaleAttemptCode, "The attempt no longer owns the analysis.");
        if (!CanonicalSha256.IsCanonical(completion.CompletionDigest) || completion.VisibilitySequence < 1 ||
            completion.PredictionArtifactId == Guid.Empty || string.IsNullOrWhiteSpace(completion.ProvenanceJson) ||
            completion.TracksAnalysed < 0 || completion.TracksUnavailable < 0 ||
            completion.AttributesObserved < 0 || completion.AttributesUnknown < 0)
            throw Invalid();

        Status = isPreferred ? VisualAttributeAnalysisStatus.Completed : VisualAttributeAnalysisStatus.Superseded;
        CompletionDigest = completion.CompletionDigest;
        VisibilitySequence = completion.VisibilitySequence;
        PredictionArtifactId = completion.PredictionArtifactId;
        ProvenanceJson = completion.ProvenanceJson;
        TracksAnalysed = completion.TracksAnalysed;
        TracksUnavailable = completion.TracksUnavailable;
        AttributesObserved = completion.AttributesObserved;
        AttributesUnknown = completion.AttributesUnknown;
        CompletedAtUtc = completedAtUtc.ToUniversalTime();
        // The capability hash is kept: it authenticates an exact replay after an ambiguous
        // HTTP outcome (CanAuthenticateCompletionReplay). The lease is over.
        LeaseExpiresAtUtc = null;
    }

    /// <summary>A newer preferred completion moved currency; the facts stay exactly as committed.</summary>
    public void Supersede()
    {
        if (Status != VisualAttributeAnalysisStatus.Completed) throw Invalid();
        Status = VisualAttributeAnalysisStatus.Superseded;
    }

    public bool IsFactBearing => Status is VisualAttributeAnalysisStatus.Completed or VisualAttributeAnalysisStatus.Superseded;

    /// <summary>
    /// Whether a duplicate completion presents the capability that published this unit. Expiry
    /// is not consulted: the publication ended the lease.
    /// </summary>
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
    public string AttributeSchemaId { get; private set; } = string.Empty;
    public string AttributeSchemaVersion { get; private set; } = string.Empty;
    public string AttributeSchemaSha256 { get; private set; } = string.Empty;
    public string PipelineId { get; private set; } = string.Empty;
    public string PipelineVersion { get; private set; } = string.Empty;
    public string AggregationPolicyId { get; private set; } = string.Empty;
    public string AggregationPolicyVersion { get; private set; } = string.Empty;
    public string AggregationPolicySha256 { get; private set; } = string.Empty;
    public string CapabilitiesCanonical { get; private set; } = string.Empty;
    public string ParametersSha256 { get; private set; } = string.Empty;
    public VisualAttributeAnalysisStatus Status { get; private set; }
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
    public VisualAttributeFailOutcome? LastFailedOutcome { get; private set; }
    public string? CompletionDigest { get; private set; }
    public Guid? PredictionArtifactId { get; private set; }
    public string? ProvenanceJson { get; private set; }
    public int TracksAnalysed { get; private set; }
    public int TracksUnavailable { get; private set; }
    public int AttributesObserved { get; private set; }
    public int AttributesUnknown { get; private set; }
    public long? VisibilitySequence { get; private set; }

    public VisualAttributeIdentityFields Identity => new(
        IdentityFingerprint, AttributeSchemaId, AttributeSchemaVersion, AttributeSchemaSha256,
        PipelineId, PipelineVersion, AggregationPolicyId, AggregationPolicyVersion, AggregationPolicySha256,
        CapabilitiesCanonical, ParametersSha256);

    // --- Helpers ------------------------------------------------------------------------

    private void RequireActiveLease(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc)
    {
        if (Status != VisualAttributeAnalysisStatus.Running)
            throw new DomainValidationException("visual_attribute_not_running", "The analysis is not running.");
        if (!HoldsActiveLease(workerId, tokenMatches, attemptCount, nowUtc))
            throw new DomainValidationException("visual_attribute_lease_invalid", "The lease is not held by this attempt.");
    }

    private DateTimeOffset CapAtDeadline(DateTimeOffset expiry, VisualAttributeLeasePolicy policy) =>
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
        Status = VisualAttributeAnalysisStatus.Failed;
        FailureCode = code;
        FailureDetails = details;
        CompletedAtUtc = nowUtc;
    }

    public static bool IsFailureCode(string? value) =>
        value is { Length: >= 1 and <= 64 } &&
        value[0] is >= 'a' and <= 'z' &&
        value.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '_');

    internal static bool IsToken(string? value) =>
        value is { Length: >= 1 and <= 64 } &&
        value[0] is >= 'a' and <= 'z' &&
        value[^1] != '-' &&
        !value.Contains("--", StringComparison.Ordinal) &&
        value.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '-');

    private static bool IsVersion(string? value) =>
        value is { Length: >= 5 and <= 64 } &&
        value.Split('.') is { Length: 3 } parts &&
        parts.All(part => part.Length > 0 && part.All(char.IsAsciiDigit));

    private static bool IsValid(VisualAttributeIdentityFields identity) =>
        CanonicalSha256.IsCanonical(identity.Fingerprint) &&
        IsToken(identity.AttributeSchemaId) && IsVersion(identity.AttributeSchemaVersion) &&
        CanonicalSha256.IsCanonical(identity.AttributeSchemaSha256) &&
        IsToken(identity.PipelineId) && IsVersion(identity.PipelineVersion) &&
        IsToken(identity.AggregationPolicyId) && IsVersion(identity.AggregationPolicyVersion) &&
        CanonicalSha256.IsCanonical(identity.AggregationPolicySha256) &&
        identity.CapabilitiesCanonical is { Length: >= 2 and <= 1024 } capabilities &&
        capabilities[0] == '[' && capabilities[^1] == ']' &&
        CanonicalSha256.IsCanonical(identity.ParametersSha256);

    private static DomainValidationException Invalid() =>
        new("visual_attribute_transition_invalid", "The visual attribute analysis operation is invalid.");
}
