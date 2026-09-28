using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Modules.VisualAttributes;

public sealed record VisualAttributeLeaseObservation(Guid ObservationId, string Role, int EvidenceRank, long SizeBytes, string Sha256);

public sealed record VisualAttributeLeaseTrack(Guid TrackId, string ObjectClass, IReadOnlyList<VisualAttributeLeaseObservation> Observations);

/// <summary>A successful claim: the new capability exists here and in the response header only.</summary>
public sealed record VisualAttributeLeaseGrant(
    Guid AnalysisId,
    Guid ProcessingRunId,
    string WorkerId,
    string LeaseToken,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    DateTimeOffset DeadlineAtUtc,
    VisualAttributeIdentityFields Identity,
    IReadOnlyList<VisualAttributeLeaseTrack> Tracks);

/// <summary>An operation refused with a stable code (never echoing a capability).</summary>
public sealed record VisualAttributeRefusal(string Code);

public sealed record VisualAttributeHeartbeatOutcome(DateTimeOffset? LeaseExpiresAtUtc, VisualAttributeRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;
}

public sealed record VisualAttributeFailureOutcome(VisualAttributeFailOutcome? Outcome, VisualAttributeRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;
}

public sealed record VisualAttributeSweepResult(int DeadlineFailed, int ExhaustedFailed);

/// <summary>What one attempt is authorised to read: the Observation's accepted crop.</summary>
public sealed record VisualAttributeEvidenceGrant(
    Guid AnalysisId,
    int AttemptCount,
    Guid ObservationId,
    Guid ArtifactId,
    string StorageKey,
    string MimeType,
    long SizeBytes,
    string Sha256,
    DateTimeOffset LeaseExpiresAtUtc);

public sealed record VisualAttributeEvidenceAuthorization(VisualAttributeEvidenceGrant? Grant, VisualAttributeRefusal? Refusal)
{
    public bool IsAuthorised => Refusal is null;
}

/// <summary>
/// The transactional lifecycle of Visual Attribute analyses (S2b plan §8). Every
/// transaction is short and takes its row lock explicitly; no transaction is ever open while
/// a worker infers, reads evidence or uploads.
/// </summary>
public interface IVisualAttributeLifecycle
{
    /// <summary>
    /// Records the release's preferred identity if it is not the current activation, and
    /// returns when the current activation began (the start of the automatic queueing window).
    /// </summary>
    Task<DateTimeOffset> EnsureActivationAsync(VisualAttributeReleaseDefinition definition, CancellationToken cancellationToken);

    /// <summary>Queues one unit per eligible visible run that has none for the preferred identity.</summary>
    Task<int> QueueEligibleAsync(VisualAttributeReleaseDefinition definition, DateTimeOffset activatedAtUtc, int batchSize,
        CancellationToken cancellationToken);

    /// <summary>Claims the oldest claimable unit of the worker's own identity, or none.</summary>
    Task<VisualAttributeLeaseGrant?> ClaimNextAsync(string workerId, string identityFingerprint, VisualAttributeLeasePolicy policy,
        CancellationToken cancellationToken);

    Task<VisualAttributeHeartbeatOutcome> HeartbeatAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount,
        VisualAttributeLeasePolicy policy, CancellationToken cancellationToken);

    Task<VisualAttributeFailureOutcome> FailAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount,
        string failureCode, bool retryable, string? failureMessage, VisualAttributeLeasePolicy policy,
        CancellationToken cancellationToken);

    /// <summary>The platform's deadline and exhaustion authority; needs no worker to be polling.</summary>
    Task<VisualAttributeSweepResult> SweepAsync(VisualAttributeLeasePolicy policy, int batchSize, CancellationToken cancellationToken);

    /// <summary>
    /// Authorises one evidence read: an active lease of this attempt, and an accepted
    /// EvidenceCrop of an Observation of a Track of the unit's own run.
    /// </summary>
    Task<VisualAttributeEvidenceAuthorization> AuthorizeEvidenceReadAsync(Guid analysisId, string workerId, string leaseToken,
        int attemptCount, Guid observationId, CancellationToken cancellationToken);

    /// <summary>
    /// Authorises one prediction upload: an active lease of this attempt. Returns the refusal,
    /// or <see langword="null"/> when the attempt may write its own staging.
    /// </summary>
    Task<VisualAttributeRefusal?> AuthorizeUploadAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount,
        CancellationToken cancellationToken);

    /// <summary>
    /// The current lease expiry when this attempt still holds an active lease, otherwise null:
    /// the re-check a streamed evidence read or upload makes over its lifetime (plan §10, §12).
    /// One primary-key read; no lock, no write.
    /// </summary>
    Task<DateTimeOffset?> RevalidateLeaseAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount,
        CancellationToken cancellationToken);

    /// <summary>The schema text of an identity the platform has activated, or none.</summary>
    Task<string?> AttributeSchemaJsonAsync(string identityFingerprint, CancellationToken cancellationToken);
}
