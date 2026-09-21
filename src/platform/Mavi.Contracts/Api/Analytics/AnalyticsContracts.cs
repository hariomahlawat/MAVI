using System.Text.Json.Serialization;

namespace Mavi.Contracts.Api.Analytics;

// Scene-analytics status and coverage projections (ADR-011).
//
// A running attempt is fenced by an opaque claim token whose hash alone is
// persisted. Neither the token nor its hash is ever projected here; that is the
// secret. The attempt number and the lease expiry are not secrets and are
// projected deliberately, because an operator looking at a Running unit needs to
// know whether it is progressing or has been abandoned.

/// <summary>One analysis unit: a run analysed against one scene revision by one algorithm version.</summary>
public sealed record SceneAnalysisStatusResponse(
    Guid AnalysisId,
    Guid ProcessingRunId,
    Guid SceneRevisionId,
    int SceneRevisionNumber,
    string AlgorithmVersion,
    string Status,
    int AttemptCount,
    DateTimeOffset QueuedAtUtc,
    DateTimeOffset? StartedAtUtc,
    DateTimeOffset? CompletedAtUtc,
    DateTimeOffset? LeaseExpiresAtUtc,
    int AnalysedTrackCount,
    int UnavailableTrackCount,
    string? FailureCode);

/// <summary>Analytics readiness for one processing run, plus the units behind it.</summary>
/// <remarks>
/// <paramref name="Readiness"/> is derived, not stored; see
/// <see cref="SceneAnalyticsContractRules.ReadinessValues"/>. It distinguishes a
/// camera that was never configured from one whose active revision disables
/// analytics, so neither is reported as an absence of matches.
/// </remarks>
public sealed record ProcessingRunAnalyticsResponse(
    Guid ProcessingRunId,
    string Readiness,
    Guid? ActiveSceneRevisionId,
    string AlgorithmVersion,
    IReadOnlyList<SceneAnalysisStatusResponse> Analyses);

/// <summary>
/// How much of an analytic query's scope was actually evaluated. Returned with
/// every response to a query that used an analytic predicate, and with every
/// aggregate response.
/// </summary>
/// <remarks>
/// <paramref name="SceneRevisionId"/> is null when no revision could be
/// resolved for the query's scope, which happens when the camera has never been
/// configured; every run in scope then falls into
/// <paramref name="NotConfiguredRuns"/> and the answer is not complete.
/// A camera that was never configured and one whose active revision disables
/// analytics are counted separately, because an operator is owed the difference
/// between a gap and a deliberate switch-off, and the UI names each non-zero
/// bucket. Neither was evaluated, so either makes the answer incomplete.
/// </remarks>
public sealed record AnalyticsCoverageResponse(
    Guid? SceneRevisionId,
    string AlgorithmVersion,
    int EvaluatedRuns,
    int PendingRuns,
    int FailedRuns,
    int NotConfiguredRuns,
    int DisabledRuns,
    int StaleRuns)
{
    /// <summary>
    /// True only when every run in scope was evaluable. Computed rather than
    /// supplied, so a coverage block can never claim completeness while
    /// reporting runs it did not evaluate.
    /// </summary>
    public bool Complete =>
        PendingRuns == 0 &&
        FailedRuns == 0 &&
        NotConfiguredRuns == 0 &&
        DisabledRuns == 0 &&
        StaleRuns == 0;
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record SceneReanalysisRequest(string? Scope);

/// <summary>
/// How a re-analysis request landed, per run in its scope.
/// </summary>
/// <remarks>
/// The breakdown is required rather than decorative (plan §X). Re-analysis is idempotent
/// per identity, so a second request usually creates nothing; reporting one total would
/// make a repeated click look identical to the first one and appear to have done work.
/// Every run in scope lands in exactly one bucket, so the counts sum to the scope size.
/// <paramref name="AlreadySuperseded"/> is reported separately rather than counted as
/// ready: finding the <i>requested</i> identity already historical is a consistency
/// condition to investigate, not a successful analysis (plan §P).
/// </remarks>
public sealed record SceneReanalysisAcceptedResponse(
    Guid CameraId,
    Guid SceneRevisionId,
    string AlgorithmVersion,
    string Scope,
    int Created,
    int AlreadyQueued,
    int AlreadyRunning,
    int AlreadyReady,
    int FailedRequiresRetry,
    int AlreadySuperseded)
{
    /// <summary>Runs in scope, which is the sum of the buckets.</summary>
    public int RunsInScope =>
        Created + AlreadyQueued + AlreadyRunning + AlreadyReady + FailedRequiresRetry + AlreadySuperseded;
}
