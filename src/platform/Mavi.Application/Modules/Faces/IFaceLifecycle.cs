using Mavi.Contracts.Worker.Faces;
using Mavi.Domain.Faces;

namespace Mavi.Application.Modules.Faces;

public sealed record FaceLeaseObservation(Guid ObservationId, string Role, int EvidenceRank, long SizeBytes, string Sha256);

public sealed record FaceLeaseTrack(Guid TrackId, IReadOnlyList<FaceLeaseObservation> Observations);

/// <summary>A successful claim: the new capability exists here and in the response header only.</summary>
public sealed record FaceLeaseGrant(
    Guid AnalysisId,
    Guid ProcessingRunId,
    string WorkerId,
    string LeaseToken,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    DateTimeOffset DeadlineAtUtc,
    FaceIdentityFields Identity,
    IReadOnlyList<FaceLeaseTrack> Tracks);

public sealed record FaceRefusal(string Code);

public sealed record FaceHeartbeatOutcome(DateTimeOffset? LeaseExpiresAtUtc, FaceRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;
}

public sealed record FaceFailureOutcome(FaceFailOutcome? Outcome, FaceRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;
}

public sealed record FaceSweepResult(int DeadlineFailed, int ExhaustedFailed, int QueriesExhausted, int QueryImagesErased, int QueriesPurged);

public sealed record FaceEvidenceGrant(string StorageKey, string MimeType, long SizeBytes, DateTimeOffset LeaseExpiresAtUtc);

public sealed record FaceEvidenceAuthorization(FaceEvidenceGrant? Grant, FaceRefusal? Refusal)
{
    public bool IsAuthorised => Refusal is null;
}

public sealed record FaceQueryLeaseGrant(
    Guid QueryId, string WorkerId, string LeaseToken, int AttemptCount, DateTimeOffset LeaseExpiresAtUtc, string MimeType, long SizeBytes,
    string Sha256);

public sealed record FaceQueryImage(byte[]? Bytes, string? MimeType, FaceRefusal? Refusal);

/// <summary>The completion of one analysis: published, an idempotent replay, or refused with an HTTP status.</summary>
public sealed record FaceCompletionResult(
    string? Status,
    int HttpStatus,
    string? Code,
    Guid? ProcessingRunId,
    DateTimeOffset? CompletedAtUtc,
    int TracksObserved,
    int TracksUnknown,
    int FacesUsable)
{
    public bool IsSuccess => Code is null;

    public static FaceCompletionResult Refused(int status, string code) => new(null, status, code, null, null, 0, 0, 0);
}

public sealed record FaceQueryCompletionResult(int HttpStatus, string? Code, int Faces)
{
    public bool IsSuccess => Code is null;
}

/// <summary>
/// The transactional lifecycle of face analyses and transient query images (ADR-022 §3–§5). Every transaction is
/// short and takes its row lock explicitly; none is open while a worker infers or reads evidence. Nothing here
/// locks, reads for update or writes a ProcessingRun, Track, Observation or another role's unit.
/// </summary>
public interface IFaceLifecycle
{
    /// <summary>Queues the visible completed runs of opted-in cameras that have a Person Track and no unit under the identity.</summary>
    Task<int> QueueEligibleAsync(FaceReleaseDefinition definition, int batchSize, CancellationToken cancellationToken);

    Task<FaceLeaseGrant?> ClaimNextAsync(string workerId, FaceReleaseDefinition definition, FaceLeasePolicy policy, CancellationToken cancellationToken);

    Task<FaceHeartbeatOutcome> HeartbeatAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, FaceLeasePolicy policy, CancellationToken cancellationToken);

    Task<FaceFailureOutcome> FailAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable,
        string? failureMessage, FaceLeasePolicy policy, CancellationToken cancellationToken);

    Task<FaceSweepResult> SweepAsync(FaceLeasePolicy policy, int batchSize, CancellationToken cancellationToken);

    Task<FaceEvidenceAuthorization> AuthorizeEvidenceReadAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, Guid observationId, CancellationToken cancellationToken);

    Task<DateTimeOffset?> RevalidateLeaseAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken);

    Task<FaceCompletionResult> CompleteAsync(
        Guid analysisId, string leaseToken, byte[] body, FaceCompleteRequest request, FaceReleaseDefinition? preferred,
        CancellationToken cancellationToken);

    // --- Transient query images ----------------------------------------------------------------

    Task<FaceQueryLeaseGrant?> ClaimQueryAsync(string workerId, string identityFingerprint, TimeSpan leaseDuration, CancellationToken cancellationToken);

    Task<FaceQueryImage> ReadQueryImageAsync(Guid queryId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken);

    Task<FaceQueryCompletionResult> CompleteQueryAsync(
        Guid queryId, string leaseToken, byte[] body, FaceQueryCompleteRequest request, FaceReleaseDefinition definition,
        CancellationToken cancellationToken);

    Task<FaceFailureOutcome> FailQueryAsync(
        Guid queryId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable, CancellationToken cancellationToken);
}
