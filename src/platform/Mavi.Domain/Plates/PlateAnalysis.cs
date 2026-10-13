using Mavi.Domain.Common;
using Mavi.Domain.Processing;

namespace Mavi.Domain.Plates;

public enum PlateAnalysisStatus
{
    Queued,
    Running,
    Completed,
    Failed,
    Superseded,
}

public enum PlateFailOutcome
{
    Requeued,
    Failed,
}

/// <summary>The lifecycle bounds one host applies to every plate unit.</summary>
public sealed record PlateLeasePolicy(
    TimeSpan LeaseDuration,
    TimeSpan HeartbeatExtension,
    int MaximumAttempts,
    TimeSpan MaximumAnalysisDuration);

/// <summary>The immutable identity a unit is queued under (ADR-013 item 11), fingerprint included.</summary>
public sealed record PlateIdentityFields(
    string Fingerprint,
    string PipelineId,
    string PipelineVersion,
    string PredictionsSchemaVersion,
    string NormalisationId,
    string NormalisationSha256,
    string SummaryPolicyId,
    string SummaryPolicyVersion,
    string SummaryPolicySha256,
    string CapabilitiesCanonical,
    string ParametersSha256);

/// <summary>The facts a successful Phase C publishes onto the header.</summary>
public sealed record PlateCompletion(
    string CompletionDigest,
    long VisibilitySequence,
    Guid PredictionArtifactId,
    string ProvenanceJson,
    int TracksAnalysed,
    int TracksUnavailable,
    int PlateObservationsRead,
    int PlateObservationsUnreadable);

public sealed record PlateFailResult(PlateFailOutcome Outcome, PlateAttemptFailure Record);

/// <summary>
/// One plate analysis: a ProcessingRun's Vehicle Tracks analysed under one immutable plate identity
/// (ADR-013 §9, §11; implementation amendment 2026-10-13, item 11).
/// </summary>
/// <remarks>
/// <para>
/// Capability-specific by design (plan B1): the lease state machine deliberately repeats the
/// Visual Attribute analysis's rather than sharing a generic job abstraction (ADR-013 alternative G).
/// The semantics are the same and are pinned by this aggregate's own tests.
/// </para>
/// <para>
/// <b>Two fences, deliberately different.</b> Every lease-scoped operation — heartbeat, evidence read,
/// upload, failure and Phase A of completion — needs an unexpired lease presented by the current worker,
/// capability and attempt. Phase C is fenced by <i>ownership</i> alone (<see cref="Complete"/>): a
/// validated completion whose lease expired while it sealed may still publish, as long as no reclaim
/// changed hands (ADR-013 implementation amendment 2026-09-28, item 4).
/// </para>
/// <para>
/// <b>Attempts</b> are consumed at claim. A retryable failure returns the unit to
/// <see cref="PlateAnalysisStatus.Queued"/> while attempts and time remain; a terminal one, exhaustion
/// and the deadline end it as <see cref="PlateAnalysisStatus.Failed"/>.
/// </para>
/// <para>
/// <b>The deadline</b> is <c>FirstClaimedAtUtc + MaximumAnalysisDuration</c>. It exists only once a unit
/// has been claimed, so work queued while no plates worker is deployed never fails on the clock. No
/// ordinary lease extends past it; only the publication window may, by at most one lease duration.
/// </para>
/// </remarks>
public sealed class PlateAnalysis
{
    public const int LeaseTokenHashLength = 32;
    public const int MaximumFailureDetailsLength = 4000;
    public const int MaximumCapabilitiesCanonicalLength = 1024;
    public const string StaleAttemptCode = "plate_attempt_stale";
    public const string DeadlineExceededCode = "plate_deadline_exceeded";
    public const string AttemptsExhaustedCode = "plate_attempts_exhausted";
    public const string NotRunningCode = "plate_not_running";
    public const string LeaseInvalidCode = "plate_lease_invalid";
    public const string TransitionInvalidCode = "plate_transition_invalid";

    private PlateAnalysis() { }

    public static PlateAnalysis Queue(Guid processingRunId, PlateIdentityFields identity, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(identity);
        if (processingRunId == Guid.Empty || !IsValid(identity)) throw Invalid();
        return new PlateAnalysis
        {
            Id = Guid.CreateVersion7(),
            ProcessingRunId = processingRunId,
            IdentityFingerprint = identity.Fingerprint,
            PipelineId = identity.PipelineId,
            PipelineVersion = identity.PipelineVersion,
            PredictionsSchemaVersion = identity.PredictionsSchemaVersion,
            NormalisationId = identity.NormalisationId,
            NormalisationSha256 = identity.NormalisationSha256,
            SummaryPolicyId = identity.SummaryPolicyId,
            SummaryPolicyVersion = identity.SummaryPolicyVersion,
            SummaryPolicySha256 = identity.SummaryPolicySha256,
            CapabilitiesCanonical = identity.CapabilitiesCanonical,
            ParametersSha256 = identity.ParametersSha256,
            Status = PlateAnalysisStatus.Queued,
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
        Status == PlateAnalysisStatus.Running && LeaseExpiresAtUtc is { } expiry && expiry > nowUtc.ToUniversalTime();

    public bool CanClaim(DateTimeOffset nowUtc, PlateLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (policy.MaximumAttempts < 1 || AttemptCount >= policy.MaximumAttempts) return false;
        if (IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration)) return false;
        return Status switch
        {
            PlateAnalysisStatus.Queued => true,
            PlateAnalysisStatus.Running => !HasLiveLease(nowUtc),
            _ => false,
        };
    }

    /// <summary>A first claim or a reclaim: a new attempt, a new capability, a new lease.</summary>
    public void Claim(string workerId, byte[] leaseTokenHash, DateTimeOffset nowUtc, PlateLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (!CanClaim(nowUtc, policy) || !WorkerIdRules.IsCanonical(workerId) ||
            leaseTokenHash is not { Length: LeaseTokenHashLength } || policy.LeaseDuration <= TimeSpan.Zero ||
            policy.MaximumAnalysisDuration <= TimeSpan.Zero)
            throw Invalid();

        var now = nowUtc.ToUniversalTime();
        FirstClaimedAtUtc ??= now;
        Status = PlateAnalysisStatus.Running;
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
        Status == PlateAnalysisStatus.Running &&
        tokenMatches &&
        LeaseTokenHash is not null &&
        attemptCount == AttemptCount &&
        string.Equals(LeaseOwner, workerId, StringComparison.Ordinal);

    /// <summary>The fence of every lease-scoped operation: owned and unexpired.</summary>
    public bool HoldsActiveLease(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc) =>
        IsOwnedBy(workerId, tokenMatches, attemptCount) && HasLiveLease(nowUtc);

    public void Heartbeat(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc, PlateLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        RequireActiveLease(workerId, tokenMatches, attemptCount, nowUtc);
        if (IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration))
            throw new DomainValidationException(DeadlineExceededCode, "The analysis has exceeded its maximum duration.");
        if (policy.HeartbeatExtension <= TimeSpan.Zero) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        LastHeartbeatUtc = now;
        // A renewal never shortens a lease: after Phase A the lease may already cover the
        // publication window, which a late heartbeat must not cut back.
        LeaseExpiresAtUtc = Later(LeaseExpiresAtUtc, CapAtDeadline(now.Add(policy.HeartbeatExtension), policy));
    }

    /// <summary>
    /// Phase A of a completion passed: the owner holds its lease for one publication window — a lease
    /// duration from now, and never more than one lease duration past the deadline — so no reclaim,
    /// attempts-exhausted or deadline transition can overtake the seal (Phase B). Phase C is still fenced
    /// on ownership, not on this expiry.
    /// </summary>
    public void BeginPublication(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc, PlateLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        RequireActiveLease(workerId, tokenMatches, attemptCount, nowUtc);
        if (policy.LeaseDuration <= TimeSpan.Zero) throw Invalid();
        var window = nowUtc.ToUniversalTime().Add(policy.LeaseDuration);
        if (Deadline(policy.MaximumAnalysisDuration) is { } deadline && deadline.Add(policy.LeaseDuration) < window)
            window = deadline.Add(policy.LeaseDuration);
        LeaseExpiresAtUtc = Later(LeaseExpiresAtUtc, window);
    }

    public PlateFailResult FailAttempt(
        string workerId,
        bool tokenMatches,
        int attemptCount,
        string failureCode,
        bool retryable,
        string? failureDetails,
        DateTimeOffset nowUtc,
        PlateLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        RequireActiveLease(workerId, tokenMatches, attemptCount, nowUtc);
        if (!IsFailureCode(failureCode) || failureDetails?.Length > MaximumFailureDetailsLength) throw Invalid();

        var now = nowUtc.ToUniversalTime();
        var record = PlateAttemptFailure.Create(Id, AttemptCount, failureCode, retryable, failureDetails, now);
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
            Status = PlateAnalysisStatus.Queued;
            LastFailedOutcome = PlateFailOutcome.Requeued;
            return new PlateFailResult(PlateFailOutcome.Requeued, record);
        }

        Terminate(failureCode, failureDetails, now);
        LastFailedOutcome = PlateFailOutcome.Failed;
        return new PlateFailResult(PlateFailOutcome.Failed, record);
    }

    /// <summary>
    /// Whether a failure request is an exact duplicate of the last recorded worker failure: the same
    /// worker, capability, attempt, code and details. A later attempt's state is never touched by it.
    /// </summary>
    public bool IsRecordedFailureReplay(string workerId, bool lastFailedTokenMatches, int attemptCount, string failureCode, string? failureDetails) =>
        lastFailedTokenMatches &&
        LastFailedTokenHash is not null &&
        LastFailedAttempt == attemptCount &&
        string.Equals(LastFailedWorkerId, workerId, StringComparison.Ordinal) &&
        string.Equals(LastFailedCode, failureCode, StringComparison.Ordinal) &&
        string.Equals(LastFailedDetails, failureDetails, StringComparison.Ordinal);

    // --- Platform-owned terminal transitions ---------------------------------------------

    /// <summary>
    /// No permitted attempt is left and none is live: a Running unit whose last attempt's lease expired, or a
    /// Queued unit (requeued by a retryable failure) whose attempts already reach a lowered
    /// <see cref="PlateLeasePolicy.MaximumAttempts"/> — which no claim could take, so it would otherwise wait forever.
    /// </summary>
    public bool IsExhausted(DateTimeOffset nowUtc, PlateLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        return Status is PlateAnalysisStatus.Running or PlateAnalysisStatus.Queued &&
               AttemptCount >= policy.MaximumAttempts && !HasLiveLease(nowUtc);
    }

    /// <summary>
    /// Whether the platform may end the unit for its deadline now: the deadline has passed and no lease is
    /// live. This differs from <see cref="IsDeadlineExceeded"/> only while a completion validated before the
    /// deadline is publishing inside its bounded window (<see cref="BeginPublication"/>).
    /// </summary>
    public bool IsDeadlineEnforceable(DateTimeOffset nowUtc, PlateLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        return Status is PlateAnalysisStatus.Queued or PlateAnalysisStatus.Running &&
               IsDeadlineExceeded(nowUtc, policy.MaximumAnalysisDuration) &&
               !HasLiveLease(nowUtc);
    }

    /// <summary>The platform ends a claimed unit whose deadline passed and whose lease ended.</summary>
    public void FailDeadlineExceeded(DateTimeOffset nowUtc, PlateLeasePolicy policy)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (!IsDeadlineEnforceable(nowUtc, policy)) throw Invalid();
        ClearLease();
        Terminate(DeadlineExceededCode, null, nowUtc.ToUniversalTime());
    }

    /// <summary>The platform ends a unit with no permitted attempt left (<see cref="IsExhausted"/>).</summary>
    public void FailAttemptsExhausted(DateTimeOffset nowUtc, PlateLeasePolicy policy)
    {
        if (!IsExhausted(nowUtc, policy)) throw Invalid();
        ClearLease();
        Terminate(AttemptsExhaustedCode, null, nowUtc.ToUniversalTime());
    }

    // --- Completion ----------------------------------------------------------------------

    /// <summary>
    /// Phase C: publish, fenced by ownership (status, worker, capability, attempt), not by the clock.
    /// <paramref name="isPreferred"/> is whether this unit's identity is the currently preferred one; an
    /// obsolete identity completes directly as history.
    /// </summary>
    public void Complete(
        string workerId,
        bool tokenMatches,
        int attemptCount,
        DateTimeOffset completedAtUtc,
        PlateCompletion completion,
        bool isPreferred)
    {
        ArgumentNullException.ThrowIfNull(completion);
        if (!IsOwnedBy(workerId, tokenMatches, attemptCount))
            throw new DomainValidationException(StaleAttemptCode, "The attempt no longer owns the analysis.");
        if (!CanonicalSha256.IsCanonical(completion.CompletionDigest) || completion.VisibilitySequence < 1 ||
            completion.PredictionArtifactId == Guid.Empty || string.IsNullOrWhiteSpace(completion.ProvenanceJson) ||
            completion.TracksAnalysed < 0 || completion.TracksUnavailable < 0 ||
            completion.PlateObservationsRead < 0 || completion.PlateObservationsUnreadable < 0)
            throw Invalid();

        Status = isPreferred ? PlateAnalysisStatus.Completed : PlateAnalysisStatus.Superseded;
        CompletionDigest = completion.CompletionDigest;
        VisibilitySequence = completion.VisibilitySequence;
        PredictionArtifactId = completion.PredictionArtifactId;
        ProvenanceJson = completion.ProvenanceJson;
        TracksAnalysed = completion.TracksAnalysed;
        TracksUnavailable = completion.TracksUnavailable;
        PlateObservationsRead = completion.PlateObservationsRead;
        PlateObservationsUnreadable = completion.PlateObservationsUnreadable;
        CompletedAtUtc = completedAtUtc.ToUniversalTime();
        // The capability hash is kept: it authenticates an exact replay after an ambiguous HTTP
        // outcome (CanAuthenticateCompletionReplay). The lease is over.
        LeaseExpiresAtUtc = null;
    }

    /// <summary>A newer preferred completion moved currency; the facts stay exactly as committed.</summary>
    public void Supersede()
    {
        if (Status != PlateAnalysisStatus.Completed) throw Invalid();
        Status = PlateAnalysisStatus.Superseded;
    }

    public bool IsFactBearing => Status is PlateAnalysisStatus.Completed or PlateAnalysisStatus.Superseded;

    /// <summary>
    /// Whether a duplicate completion presents the capability that published this unit. Expiry is not
    /// consulted: the publication ended the lease.
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
    public string PipelineId { get; private set; } = string.Empty;
    public string PipelineVersion { get; private set; } = string.Empty;
    public string PredictionsSchemaVersion { get; private set; } = string.Empty;
    public string NormalisationId { get; private set; } = string.Empty;
    public string NormalisationSha256 { get; private set; } = string.Empty;
    public string SummaryPolicyId { get; private set; } = string.Empty;
    public string SummaryPolicyVersion { get; private set; } = string.Empty;
    public string SummaryPolicySha256 { get; private set; } = string.Empty;
    public string CapabilitiesCanonical { get; private set; } = string.Empty;
    public string ParametersSha256 { get; private set; } = string.Empty;
    public PlateAnalysisStatus Status { get; private set; }
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
    public PlateFailOutcome? LastFailedOutcome { get; private set; }
    public string? CompletionDigest { get; private set; }
    public Guid? PredictionArtifactId { get; private set; }
    public string? ProvenanceJson { get; private set; }
    public int TracksAnalysed { get; private set; }
    public int TracksUnavailable { get; private set; }
    public int PlateObservationsRead { get; private set; }
    public int PlateObservationsUnreadable { get; private set; }
    public long? VisibilitySequence { get; private set; }

    public PlateIdentityFields Identity => new(
        IdentityFingerprint, PipelineId, PipelineVersion, PredictionsSchemaVersion, NormalisationId, NormalisationSha256,
        SummaryPolicyId, SummaryPolicyVersion, SummaryPolicySha256, CapabilitiesCanonical, ParametersSha256);

    // --- Helpers ------------------------------------------------------------------------

    private void RequireActiveLease(string workerId, bool tokenMatches, int attemptCount, DateTimeOffset nowUtc)
    {
        if (Status != PlateAnalysisStatus.Running)
            throw new DomainValidationException(NotRunningCode, "The analysis is not running.");
        if (!HoldsActiveLease(workerId, tokenMatches, attemptCount, nowUtc))
            throw new DomainValidationException(LeaseInvalidCode, "The lease is not held by this attempt.");
    }

    private static DateTimeOffset Later(DateTimeOffset? current, DateTimeOffset proposed) =>
        current is { } existing && existing > proposed ? existing : proposed;

    private DateTimeOffset CapAtDeadline(DateTimeOffset expiry, PlateLeasePolicy policy) =>
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
        Status = PlateAnalysisStatus.Failed;
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

    private static bool IsValid(PlateIdentityFields identity) =>
        CanonicalSha256.IsCanonical(identity.Fingerprint) &&
        IsToken(identity.PipelineId) && IsVersion(identity.PipelineVersion) &&
        IsToken(identity.PredictionsSchemaVersion) &&
        IsToken(identity.NormalisationId) && CanonicalSha256.IsCanonical(identity.NormalisationSha256) &&
        IsToken(identity.SummaryPolicyId) && IsVersion(identity.SummaryPolicyVersion) &&
        CanonicalSha256.IsCanonical(identity.SummaryPolicySha256) &&
        identity.CapabilitiesCanonical is { Length: >= 2 and <= MaximumCapabilitiesCanonicalLength } capabilities &&
        capabilities[0] == '[' && capabilities[^1] == ']' &&
        CanonicalSha256.IsCanonical(identity.ParametersSha256);

    private static DomainValidationException Invalid() =>
        new(TransitionInvalidCode, "The plate analysis operation is invalid.");
}
