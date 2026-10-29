using Mavi.Contracts.Worker.Embeddings;
using Mavi.Domain.Embeddings;

namespace Mavi.Application.Modules.Embeddings;

public sealed record EmbeddingLeaseObservation(Guid ObservationId, string Role, int EvidenceRank, long SizeBytes, string Sha256);

public sealed record EmbeddingLeaseTrack(Guid TrackId, string ObjectClass, IReadOnlyList<EmbeddingLeaseObservation> Observations);

/// <summary>A successful claim: the new capability exists here and in the response header only.</summary>
public sealed record EmbeddingLeaseGrant(
    Guid AnalysisId,
    Guid ProcessingRunId,
    string WorkerId,
    string LeaseToken,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    DateTimeOffset DeadlineAtUtc,
    EmbeddingIdentityFields Identity,
    IReadOnlyList<EmbeddingLeaseTrack> Tracks);

public sealed record EmbeddingRefusal(string Code);

public sealed record EmbeddingHeartbeatOutcome(DateTimeOffset? LeaseExpiresAtUtc, EmbeddingRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;
}

public sealed record EmbeddingFailureOutcome(EmbeddingFailOutcome? Outcome, EmbeddingRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;
}

public sealed record EmbeddingSweepResult(int DeadlineFailed, int ExhaustedFailed, int TextQueriesExhausted);

public sealed record EmbeddingEvidenceGrant(string StorageKey, string MimeType, long SizeBytes, DateTimeOffset LeaseExpiresAtUtc);

public sealed record EmbeddingEvidenceAuthorization(EmbeddingEvidenceGrant? Grant, EmbeddingRefusal? Refusal)
{
    public bool IsAuthorised => Refusal is null;
}

public sealed record EmbeddingTextLeaseGrant(
    Guid QueryId, string WorkerId, string LeaseToken, int AttemptCount, DateTimeOffset LeaseExpiresAtUtc, string IdentityFingerprint, string Text);

public sealed record EmbeddingReanalysisRequest(IReadOnlyList<Guid> ProcessingRunIds);

public sealed record EmbeddingReanalysisResult(int RunsMatched, int Queued, int AlreadyQueued, int NotEligible, EmbeddingRefusal? Refusal)
{
    public bool IsSuccess => Refusal is null;

    public static EmbeddingReanalysisResult Refused(string code) => new(0, 0, 0, 0, new EmbeddingRefusal(code));
}

/// <summary>The completion of one analysis: published, an idempotent replay, or refused with an HTTP status.</summary>
public sealed record EmbeddingCompletionResult(
    string? Status,
    int HttpStatus,
    string? Code,
    Guid? ProcessingRunId,
    DateTimeOffset? CompletedAtUtc,
    int TracksEmbedded,
    int TracksUnavailable)
{
    public bool IsSuccess => Code is null;

    public static EmbeddingCompletionResult Refused(int status, string code) => new(null, status, code, null, null, 0, 0);
}

/// <summary>
/// The transactional lifecycle of embedding analyses and appearance text queries (ADR-021 §3–§4). Every
/// transaction is short and takes its row lock explicitly; none is open while a worker infers or reads evidence.
/// </summary>
public interface IEmbeddingLifecycle
{
    Task<DateTimeOffset> EnsureActivationAsync(EmbeddingReleaseDefinition definition, CancellationToken cancellationToken);

    Task<int> QueueEligibleAsync(EmbeddingReleaseDefinition definition, DateTimeOffset activatedAtUtc, int batchSize, CancellationToken cancellationToken);

    Task<EmbeddingReanalysisResult> RequestReanalysisAsync(
        EmbeddingReleaseDefinition definition, EmbeddingReanalysisRequest request, int maximumRuns, CancellationToken cancellationToken);

    Task<EmbeddingLeaseGrant?> ClaimNextAsync(
        string workerId, EmbeddingReleaseDefinition definition, EmbeddingLeasePolicy policy, CancellationToken cancellationToken);

    Task<EmbeddingHeartbeatOutcome> HeartbeatAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, EmbeddingLeasePolicy policy, CancellationToken cancellationToken);

    Task<EmbeddingFailureOutcome> FailAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable,
        string? failureMessage, EmbeddingLeasePolicy policy, CancellationToken cancellationToken);

    Task<EmbeddingSweepResult> SweepAsync(EmbeddingLeasePolicy policy, int batchSize, CancellationToken cancellationToken);

    Task<EmbeddingEvidenceAuthorization> AuthorizeEvidenceReadAsync(
        Guid analysisId, string workerId, string leaseToken, int attemptCount, Guid observationId, CancellationToken cancellationToken);

    Task<DateTimeOffset?> RevalidateLeaseAsync(Guid analysisId, string workerId, string leaseToken, int attemptCount, CancellationToken cancellationToken);

    Task<EmbeddingCompletionResult> CompleteAsync(
        Guid analysisId, string leaseToken, byte[] body, EmbeddingCompleteRequest request, EmbeddingReleaseDefinition? preferred,
        CancellationToken cancellationToken);

    // --- Appearance text queries ---------------------------------------------------------------

    /// <summary>The query's state, inserting a Pending request when the text has none under the identity.</summary>
    Task<AppearanceQueryEmbedding> RequestTextAsync(string identityFingerprint, string normalisedText, CancellationToken cancellationToken);

    Task<AppearanceQueryEmbedding?> GetTextAsync(Guid queryId, CancellationToken cancellationToken);

    Task<EmbeddingTextLeaseGrant?> ClaimTextAsync(string workerId, string identityFingerprint, TimeSpan leaseDuration, CancellationToken cancellationToken);

    Task<EmbeddingRefusal?> CompleteTextAsync(
        Guid queryId, string workerId, string leaseToken, int attemptCount, float[] embedding, int dimension, CancellationToken cancellationToken);

    Task<EmbeddingFailureOutcome> FailTextAsync(
        Guid queryId, string workerId, string leaseToken, int attemptCount, string failureCode, bool retryable, CancellationToken cancellationToken);
}
