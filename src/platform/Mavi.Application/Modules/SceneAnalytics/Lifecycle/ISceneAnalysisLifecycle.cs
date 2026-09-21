using Mavi.Domain.SceneAnalytics;

namespace Mavi.Application.Modules.SceneAnalytics.Lifecycle;

/// <summary>
/// The identity of one analysis unit: one processing run, evaluated against one scene
/// revision, by one algorithm version.
/// </summary>
/// <remarks>
/// Unique by construction, which is what lets every creation path insert and let the
/// constraint arbitrate rather than read first and then write.
/// </remarks>
public sealed record SceneAnalysisIdentity(
    Guid ProcessingRunId,
    Guid RevisionId,
    string AlgorithmVersion,
    string ParametersSha256,
    string? SourceCommit);

/// <summary>
/// The analytics identity a host is able to execute: the engine it compiled against and
/// the exact parameter set that engine will use.
/// </summary>
/// <remarks>
/// <para>
/// This is the fence that keeps <c>AlgorithmVersion</c> and <c>ParametersSha256</c>
/// meaningful. A unit records the identity its facts were computed under, and that record
/// is only worth anything if no host can compute under a different one. The platform runs
/// multiple hosts by design — <c>FOR UPDATE SKIP LOCKED</c> exists for exactly that — so
/// a deployment boundary genuinely puts a v1 unit and a v2 host in the same database.
/// </para>
/// <para>
/// Without the fence, either direction corrupts history: a v2 host claiming a queued v1
/// unit would commit v2 facts beneath a row that says v1, and during a rolling upgrade a
/// surviving v1 host would commit v1 facts beneath a row that says v2. Neither is
/// detectable afterwards, and both destroy the reproducibility the identity exists for.
/// </para>
/// </remarks>
public sealed record SceneAnalysisExecutionIdentity
{
    public SceneAnalysisExecutionIdentity(string algorithmVersion, string parametersSha256)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(algorithmVersion);
        ArgumentException.ThrowIfNullOrWhiteSpace(parametersSha256);

        AlgorithmVersion = algorithmVersion;
        ParametersSha256 = parametersSha256;
    }

    public string AlgorithmVersion { get; }

    public string ParametersSha256 { get; }

    /// <summary>What this binary can execute, read from the compiled engine.</summary>
    public static SceneAnalysisExecutionIdentity Current { get; } = new(
        Engine.SceneAnalyticsAlgorithm.Version,
        Engine.SceneAnalyticsParameters.Default.ParametersSha256());

    /// <summary>Whether a claimed unit's persisted identity is one this host may execute.</summary>
    public bool Matches(SceneAnalysisIdentity identity)
    {
        ArgumentNullException.ThrowIfNull(identity);
        return string.Equals(identity.AlgorithmVersion, AlgorithmVersion, StringComparison.Ordinal)
            && string.Equals(identity.ParametersSha256, ParametersSha256, StringComparison.Ordinal);
    }
}

/// <summary>
/// The lease and attempt policy a lifecycle transition is taken under.
/// </summary>
/// <remarks>
/// Passed in rather than read from configuration here: binding and start-up validation
/// belong to the host that runs the loops, and keeping the policy a parameter is what
/// lets a test drive reclaim and exhaustion deterministically through
/// <see cref="TimeProvider"/> instead of by waiting.
/// </remarks>
public sealed record SceneAnalysisLeasePolicy
{
    public SceneAnalysisLeasePolicy(TimeSpan leaseDuration, TimeSpan reclaimGrace, int maximumAttempts)
    {
        ArgumentOutOfRangeException.ThrowIfLessThanOrEqual(leaseDuration, TimeSpan.Zero);
        ArgumentOutOfRangeException.ThrowIfLessThan(reclaimGrace, TimeSpan.Zero);
        ArgumentOutOfRangeException.ThrowIfLessThan(maximumAttempts, 1);

        LeaseDuration = leaseDuration;
        ReclaimGrace = reclaimGrace;
        MaximumAttempts = maximumAttempts;
    }

    public TimeSpan LeaseDuration { get; }
    public TimeSpan ReclaimGrace { get; }
    public int MaximumAttempts { get; }
}

/// <summary>
/// Proof that the holder owns one attempt on one unit, valid only in the memory of the
/// host that claimed it.
/// </summary>
/// <remarks>
/// <para>
/// The claim token is the unforgeable half of ownership. It exists as bytes here and as
/// a SHA-256 hash on the row, and nowhere else: it is never returned from an API, never
/// written to a log, never placed in an exception and never stored in a fact. Holding it
/// as <see cref="ReadOnlyMemory{T}"/> rather than a string is part of that — there is no
/// natural way for it to be concatenated into a message — and
/// <see cref="ToString"/> is overridden so that an interpolated log line cannot leak it
/// by accident.
/// </para>
/// <para>
/// <see cref="AttemptCount"/> travels with it because ownership is the <i>pair</i>. A
/// retry resets the attempt counter, so a stale attempt from an earlier cycle can hold a
/// number that collides with the current one; only the token separates them.
/// </para>
/// </remarks>
public sealed class SceneAnalysisClaim(
    Guid analysisId,
    SceneAnalysisIdentity identity,
    int attemptCount,
    ReadOnlyMemory<byte> claimToken,
    DateTimeOffset leaseExpiresAtUtc)
{
    public Guid AnalysisId { get; } = analysisId;
    public SceneAnalysisIdentity Identity { get; } = identity;
    public int AttemptCount { get; } = attemptCount;
    public ReadOnlyMemory<byte> ClaimToken { get; } = claimToken;
    public DateTimeOffset LeaseExpiresAtUtc { get; } = leaseExpiresAtUtc;

    /// <summary>Deliberately says nothing about the token.</summary>
    public override string ToString() =>
        $"SceneAnalysisClaim(unit {AnalysisId:D}, attempt {AttemptCount})";
}

/// <summary>Everything one successful attempt computed, ready to replace the unit's facts.</summary>
/// <remarks>
/// Every Track of the run has exactly one entry in <see cref="Outcomes"/>, including the
/// Tracks whose evidence could not be used; the other collections carry facts only for
/// the Tracks that were analysed.
/// </remarks>
public sealed record SceneAnalysisFacts(
    IReadOnlyList<TrackAnalysisOutcome> Outcomes,
    IReadOnlyList<TrackZoneVisit> ZoneVisits,
    IReadOnlyList<TrackZoneSummary> ZoneSummaries,
    IReadOnlyList<TrackLineCrossing> LineCrossings,
    IReadOnlyList<TrackMotionSummary> MotionSummaries)
{
    public static SceneAnalysisFacts Empty { get; } = new([], [], [], [], []);
}

/// <summary>What a creation request did, or found already done.</summary>
public enum SceneAnalysisQueueOutcome
{
    /// <summary>A new unit was queued.</summary>
    Created,

    /// <summary>A unit for this identity was already waiting.</summary>
    AlreadyQueued,

    /// <summary>A unit for this identity is being analysed now.</summary>
    AlreadyRunning,

    /// <summary>This identity has already been analysed successfully.</summary>
    AlreadyAnalysed,

    /// <summary>A unit exists but failed; it needs an explicit retry, not a second unit.</summary>
    FailedRequiresRetry,

    /// <summary>
    /// A unit exists in a historical state. Reported rather than acted on: a superseded
    /// unit is fact-bearing and immutable, so re-queueing it is never the answer.
    /// </summary>
    AlreadySuperseded
}

public sealed record SceneAnalysisQueueResult(SceneAnalysisQueueOutcome Outcome, Guid AnalysisId);

/// <summary>The result of a transition the owning attempt asked for.</summary>
public sealed record SceneAnalysisTransitionResult(bool IsSuccess, string? ErrorCode)
{
    public static SceneAnalysisTransitionResult Success { get; } = new(true, null);

    /// <summary>
    /// The caller's ownership no longer holds, so nothing at all was written. This is a
    /// normal outcome for an attempt that was reclaimed, not an error to retry.
    /// </summary>
    public static SceneAnalysisTransitionResult Stale { get; } =
        new(false, SceneAnalyticsErrorCodes.AttemptStale);

    public static SceneAnalysisTransitionResult Failure(string code) => new(false, code);
}

/// <summary>
/// The transactional lifecycle of an analysis unit.
/// </summary>
/// <remarks>
/// <para>
/// One rule governs every method here: <b>no transaction is open while analytics
/// compute.</b> A claim commits before the engine starts, and the facts arrive in a
/// second, short transaction that revalidates ownership before its first write. Nothing
/// on this interface runs the engine, and nothing schedules; the loops that call these
/// transitions are the host's concern.
/// </para>
/// <para>
/// Expiry of a lease is <i>not</i> loss of ownership. A unit whose lease passed is merely
/// reclaimable, and it changes hands only in <see cref="ClaimNextAsync"/> (reclaim) or
/// <see cref="ExhaustAbandonedUnitsAsync"/> (terminal exhaustion), both taken under a row
/// lock. An attempt that overruns its lease but has not been reclaimed still completes
/// normally: correct work is never discarded for a clock margin.
/// </para>
/// </remarks>
public interface ISceneAnalysisLifecycle
{
    /// <summary>
    /// Queues units for every run that is eligible and has none, for the cameras whose
    /// active revision enables analytics.
    /// </summary>
    /// <remarks>
    /// A camera that was never configured, or whose active revision is empty, matches
    /// nothing and so is never queued — that is the disable switch, not a special case in
    /// code. Runs completed before <paramref name="earliestRunCompletedAtUtc"/> are left
    /// to explicit re-analysis.
    /// </remarks>
    Task<int> QueueEligibleUnitsAsync(
        string algorithmVersion,
        string parametersSha256,
        string? sourceCommit,
        DateTimeOffset earliestRunCompletedAtUtc,
        int batchSize,
        CancellationToken cancellationToken);

    /// <summary>Creates one unit for an identity, or reports the unit already there.</summary>
    /// <remarks>
    /// The unique index is the arbiter, not a check-then-insert, so two concurrent
    /// requests for the same identity create exactly one unit and the loser classifies
    /// the row that won.
    /// </remarks>
    Task<SceneAnalysisQueueResult> RequestAnalysisAsync(
        SceneAnalysisIdentity identity,
        CancellationToken cancellationToken);

    /// <summary>
    /// Takes ownership of one claimable unit and commits before returning, so the engine
    /// never runs inside a transaction.
    /// </summary>
    /// <remarks>
    /// Claimable is <c>Queued</c>, or <c>Running</c> past its lease plus the reclaim
    /// grace. Both are one transition: a reclaim is a claim of a running unit, with a new
    /// attempt number and a new token, and the previous pair can never validate again.
    /// <c>SKIP LOCKED</c> is what makes two hosts safe — they cannot select the same row,
    /// so they cannot both claim it.
    /// </remarks>
    /// <remarks>
    /// <paramref name="executionIdentity"/> is part of the selection predicate, not a
    /// check applied afterwards: a host must never take ownership of a unit it cannot
    /// legitimately execute, because taking it consumes an attempt and blocks the host
    /// that could.
    /// </remarks>
    Task<SceneAnalysisClaim?> ClaimNextAsync(
        SceneAnalysisExecutionIdentity executionIdentity,
        SceneAnalysisLeasePolicy policy,
        CancellationToken cancellationToken);

    /// <summary>
    /// Fails the units whose last permitted attempt abandoned them, clearing the claim
    /// token so the overrunning attempt becomes stale.
    /// </summary>
    /// <returns>How many units were exhausted.</returns>
    /// <remarks>
    /// Only units past the lease <i>and</i> the grace are considered, and each is re-read
    /// under its own row lock: an attempt that committed its success first is no longer
    /// <c>Running</c> at that attempt, and this does nothing to it. Completion wins.
    /// </remarks>
    Task<int> ExhaustAbandonedUnitsAsync(
        SceneAnalysisLeasePolicy policy,
        CancellationToken cancellationToken);

    /// <summary>
    /// Commits one attempt's facts and marks the unit successful, in a single
    /// transaction, after revalidating ownership.
    /// </summary>
    /// <remarks>
    /// The unit's existing facts are deleted first, scoped to this unit id alone, which
    /// makes a repeated attempt idempotent without touching another revision's or
    /// algorithm's facts. The visibility sequence is allocated inside the same
    /// transaction under the existing completion barrier, so no search snapshot can see
    /// the facts without the unit or the unit without its facts. Units of the same run
    /// that were current become <c>Superseded</c>, with their own facts, counts,
    /// timestamps and sequences untouched.
    /// </remarks>
    Task<SceneAnalysisTransitionResult> CommitFactsAsync(
        SceneAnalysisClaim claim,
        SceneAnalysisFacts facts,
        CancellationToken cancellationToken);

    /// <summary>
    /// Records an attempt failure reported by the owning attempt.
    /// </summary>
    /// <remarks>
    /// Returns the unit to the queue while automatic attempts remain, and fails it
    /// otherwise. A stale attempt is rejected and writes nothing — in particular it
    /// cannot mark the current owner failed.
    /// </remarks>
    Task<SceneAnalysisTransitionResult> ReportFailureAsync(
        SceneAnalysisClaim claim,
        string failureCode,
        string? failureDetails,
        int maximumAttempts,
        CancellationToken cancellationToken);

    /// <summary>
    /// Explicit operator retry: a new retry cycle on the same unit.
    /// </summary>
    /// <remarks>
    /// Legal only from <c>Failed</c>. No facts are deleted here; a unit's facts are
    /// replaced only inside a later successful commit, after ownership is revalidated.
    /// </remarks>
    Task<SceneAnalysisTransitionResult> RetryAsync(Guid analysisId, CancellationToken cancellationToken);

    /// <summary>Reads one unit, or <see langword="null"/> if there is none.</summary>
    Task<SceneAnalysis?> GetAsync(Guid analysisId, CancellationToken cancellationToken);
}
