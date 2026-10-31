using Mavi.Domain.Intelligence;
using Mavi.Domain.Review;

namespace Mavi.Application.Modules.Review;

/// <summary>An operator's request to decide on a Track's detection (ADR-027 §1). The operator and time are not part of it.</summary>
public sealed record TrackReviewRequest(Guid DecisionId, Guid TrackId, TrackReviewDecisionKind Decision, ReviewStatus ExpectedReviewStatus,
    string? Note);

/// <summary>A recorded decision as the operator routes show it.</summary>
public sealed record TrackReviewDecisionView(Guid DecisionId, Guid TrackId, TrackReviewDecisionKind Decision, ReviewStatus PreviousStatus,
    ReviewStatus ResultingStatus, string? Note, string OperatorId, string OperatorDisplayName, string IdentitySource,
    DateTimeOffset DecidedAtUtc, Guid AuditEntryId, long Sequence);

public enum TrackReviewOutcomeKind
{
    /// <summary>The decision was recorded with its audit row.</summary>
    Recorded,

    /// <summary>An identical request with the same <c>decisionId</c> was recorded before; nothing was written.</summary>
    Replayed,

    TrackNotFound,

    /// <summary>The Track's status is not the one the operator saw.</summary>
    StatusConflict,

    /// <summary>The <c>decisionId</c> was used before for a different request.</summary>
    DecisionIdConflict,

    NothingToClear,
}

/// <summary>
/// <paramref name="Decision"/> is the decision the request recorded or replayed (or, on a conflict, the one in the way);
/// <paramref name="Latest"/> is the Track's latest decision now, which a replay after later decisions differs from.
/// </summary>
public sealed record TrackReviewOutcome(TrackReviewOutcomeKind Kind, ReviewStatus? CurrentStatus, TrackReviewDecisionView? Decision,
    TrackReviewDecisionView? Latest = null);

/// <summary>For a Track of one run: another completed run of the same video, and how many of its Tracks carry a decision (ADR-027 §5).</summary>
public sealed record EarlierRunDecisions(Guid ProcessingRunId, DateTimeOffset? CompletedAtUtc, int ReviewedTrackCount);

public sealed record TrackReviewState(Guid TrackId, Guid ProcessingRunId, ReviewStatus ReviewStatus, TrackReviewDecisionView? LatestDecision,
    IReadOnlyList<EarlierRunDecisions> OtherRuns);

public sealed record TrackReviewHistoryPage(IReadOnlyList<TrackReviewDecisionView> Items, long? NextBeforeSequence);

public interface ITrackReviewRepository
{
    /// <summary>
    /// Locks the Track, checks replay and expectation, records the decision, updates the projection and writes the audit
    /// row, all in one transaction; a refusal writes nothing.
    /// </summary>
    Task<TrackReviewOutcome> DecideAsync(TrackReviewRequest request, string requestSha256, CancellationToken cancellationToken);

    Task<TrackReviewState?> GetStateAsync(Guid trackId, CancellationToken cancellationToken);

    /// <summary>Newest first; <paramref name="beforeSequence"/> continues a page. Null when the Track does not exist.</summary>
    Task<TrackReviewHistoryPage?> GetHistoryAsync(Guid trackId, long? beforeSequence, int limit, CancellationToken cancellationToken);
}
