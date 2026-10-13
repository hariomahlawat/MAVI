using Mavi.Application.Modules.Plates.Release;
using Mavi.Domain.Plates;

namespace Mavi.Application.Modules.Plates;

/// <summary>The plate definition the running release declares, resolved once at startup.</summary>
public interface IPlateRelease
{
    PlateReleaseResolution Resolution { get; }
}

public sealed record PlateLeaseObservation(Guid ObservationId, string Role, int EvidenceRank, long SizeBytes, string Sha256);

public sealed record PlateLeaseTrack(Guid TrackId, IReadOnlyList<PlateLeaseObservation> Observations);

/// <summary>A successful claim: the new capability exists here and in the response header only.</summary>
public sealed record PlateLeaseGrant(
    Guid AnalysisId,
    Guid ProcessingRunId,
    string WorkerId,
    string LeaseToken,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    DateTimeOffset DeadlineAtUtc,
    PlateIdentityFields Identity,
    IReadOnlyList<PlateLeaseTrack> Tracks);

/// <summary>An operation refused with a stable code (never echoing a capability).</summary>
public sealed record PlateRefusal(string Code);

/// <param name="IdentityFingerprint">The renewed unit's identity: a renewal is proof of a READY worker for it.</param>
public sealed record PlateHeartbeatOutcome(DateTimeOffset? LeaseExpiresAtUtc, PlateRefusal? Refusal, string? IdentityFingerprint = null)
{
    public bool IsSuccess => Refusal is null;
}

public sealed record PlateFailureOutcome(PlateFailOutcome? Outcome, PlateRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;
}

public sealed record PlateSweepResult(int DeadlineFailed, int ExhaustedFailed);

/// <summary>What one attempt is authorised to read: the Observation's accepted crop.</summary>
public sealed record PlateEvidenceGrant(
    Guid AnalysisId,
    int AttemptCount,
    Guid ObservationId,
    Guid ArtifactId,
    string StorageKey,
    string MimeType,
    long SizeBytes,
    string Sha256,
    DateTimeOffset LeaseExpiresAtUtc);

public sealed record PlateEvidenceAuthorization(PlateEvidenceGrant? Grant, PlateRefusal? Refusal)
{
    public bool IsAuthorised => Refusal is null;
}

/// <summary>
/// An explicit, bounded historical re-analysis request (plan §2.2; ADR-013 §9): exactly one of a run
/// list — exactly those runs, never substituted by newer ones — or a camera time window, which selects
/// only the latest completed, visible run of each overlapping video before the bound applies.
/// </summary>
public sealed record PlateReanalysisRequest(
    IReadOnlyList<Guid>? ProcessingRunIds,
    Guid? CameraId,
    DateTimeOffset? FromUtc,
    DateTimeOffset? ToUtc);

/// <summary>
/// The runs a re-analysis request resolved to: those queued now, those that already had a unit of the
/// preferred identity (idempotent), and those skipped as not eligible (not completed and visible, or
/// without a Vehicle Track).
/// </summary>
public sealed record PlateReanalysisResult(
    string IdentityFingerprint,
    int RunsMatched,
    int Queued,
    int AlreadyQueued,
    int NotEligible,
    PlateRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;

    /// <summary>The exact runs the request selected, in selection order (audited and returned).</summary>
    public IReadOnlyList<Guid> SelectedRunIds { get; init; } = [];

    public static PlateReanalysisResult Refused(string code) => new(string.Empty, 0, 0, 0, 0, new PlateRefusal(code));
}

/// <summary>
/// The transactional lifecycle of plate analyses. Every transaction is short and takes its row lock
/// explicitly; no transaction is ever open while a worker infers, reads evidence or uploads.
/// </summary>
public interface IPlateLifecycle
{
    /// <summary>
    /// Records the release's preferred identity if it is not the current activation, and returns when
    /// the current activation began (the start of the automatic queueing window).
    /// </summary>
    Task<DateTimeOffset> EnsureActivationAsync(PlateReleaseDefinition definition, CancellationToken cancellationToken);

    /// <summary>Queues one unit per eligible visible run, completed within the activation, that has none for the identity.</summary>
    Task<int> QueueEligibleAsync(PlateReleaseDefinition definition, DateTimeOffset activatedAtUtc, int batchSize,
        CancellationToken cancellationToken);

    /// <summary>Queues historical runs on explicit request, bounded by <paramref name="maximumRuns"/>; idempotent.</summary>
    Task<PlateReanalysisResult> RequestReanalysisAsync(PlateReleaseDefinition definition, PlateReanalysisRequest request, int maximumRuns,
        CancellationToken cancellationToken);

    /// <summary>Claims the oldest claimable unit of the worker's own identity, or none.</summary>
    Task<PlateLeaseGrant?> ClaimNextAsync(string workerId, string identityFingerprint, PlateLeasePolicy policy,
        CancellationToken cancellationToken);

    Task<PlateHeartbeatOutcome> HeartbeatAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount,
        PlateLeasePolicy policy, CancellationToken cancellationToken);

    Task<PlateFailureOutcome> FailAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount,
        string failureCode, bool retryable, string? failureMessage, PlateLeasePolicy policy, CancellationToken cancellationToken);

    /// <summary>The platform's deadline and exhaustion authority; needs no worker to be polling.</summary>
    Task<PlateSweepResult> SweepAsync(PlateLeasePolicy policy, int batchSize, CancellationToken cancellationToken);

    /// <summary>
    /// Authorises one evidence read: an active lease of this attempt, and an accepted EvidenceCrop of an
    /// Observation of a Vehicle Track of the unit's own run.
    /// </summary>
    Task<PlateEvidenceAuthorization> AuthorizeEvidenceReadAsync(Guid analysisId, string workerId, string leaseToken,
        int attemptCount, Guid observationId, CancellationToken cancellationToken);

    /// <summary>Authorises one prediction upload; <see langword="null"/> when the attempt may write its own staging.</summary>
    Task<PlateRefusal?> AuthorizeUploadAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount,
        CancellationToken cancellationToken);

    /// <summary>The current lease expiry while this attempt still holds an active lease, otherwise null.</summary>
    Task<DateTimeOffset?> RevalidateLeaseAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount,
        CancellationToken cancellationToken);

    /// <summary>The parameters text of an identity the platform has activated, or none.</summary>
    Task<string?> ParametersJsonAsync(string identityFingerprint, CancellationToken cancellationToken);
}
