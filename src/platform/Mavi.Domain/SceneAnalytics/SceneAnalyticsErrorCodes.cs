namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// Stable failure codes for the analytics lifecycle, surfaced unchanged as the
/// <c>code</c> member of an RFC 7807 problem response and as
/// <c>scene_analyses.failure_code</c>.
/// </summary>
public static class SceneAnalyticsErrorCodes
{
    // --- Unit-attempt failures (retryable while attempts remain, §AE) -------

    /// <summary>The trajectory artefact could not be read (I/O).</summary>
    public const string TrajectoryReadFailed = "trajectory_read_failed";

    /// <summary>The analysis engine threw; a bug rather than bad evidence.</summary>
    public const string EngineFailed = "analytics_engine_failed";

    /// <summary>The final fact commit failed; the transaction rolled back.</summary>
    public const string PersistenceFailed = "analytics_persistence_failed";

    /// <summary>The attempt exceeded <c>MaxUnitDurationSeconds</c> and was cancelled.</summary>
    public const string UnitTimeout = "analytics_unit_timeout";

    // --- Terminal ----------------------------------------------------------

    /// <summary>
    /// No automatic attempts remain in this retry cycle. Set by the reconciler
    /// after the reclaim grace, which also clears the claim-token hash so any
    /// overrunning attempt becomes stale. Recoverable by explicit operator retry,
    /// which starts a new cycle on the same unit.
    /// </summary>
    public const string AttemptsExhausted = "analytics_attempts_exhausted";

    /// <summary>The pinned revision is missing; the foreign key should prevent it.</summary>
    public const string RevisionMissing = "analytics_revision_missing";

    // --- Fencing -----------------------------------------------------------

    /// <summary>
    /// The caller's ownership no longer holds. A stale attempt writes nothing:
    /// no facts, no completion, no failure, no supersede, no visibility sequence.
    /// </summary>
    public const string AttemptStale = "analytics_attempt_stale";

    /// <summary>A lifecycle transition was attempted from a state that forbids it.</summary>
    public const string TransitionInvalid = "analytics_transition_invalid";

    // --- Per-Track outcome reasons (never fail the unit, §31) ---------------

    /// <summary>No trajectory artefact exists for the Track.</summary>
    public const string TrajectoryMissing = "trajectory_missing";

    /// <summary>The artefact's stored digest does not match its bytes.</summary>
    public const string TrajectoryIntegrityFailed = "trajectory_integrity_failed";

    /// <summary>The artefact decoded but is not a usable trajectory.</summary>
    public const string TrajectoryInvalid = "trajectory_invalid";

    /// <summary>The trajectory has too few samples to evaluate.</summary>
    public const string TrajectoryTooShort = "trajectory_too_short";

    /// <summary>
    /// The reasons that mark a Track <see cref="TrackAnalysisOutcomeKind.Unavailable"/>
    /// rather than failing the attempt. All are permanent for this evidence: retrying
    /// the unit would read the same bytes and reach the same conclusion.
    /// </summary>
    public static readonly IReadOnlyList<string> TrackUnavailableReasons =
    [
        TrajectoryMissing,
        TrajectoryIntegrityFailed,
        TrajectoryInvalid,
        TrajectoryTooShort
    ];

    public static bool IsTrackUnavailableReason(string? value)
    {
        if (value is null)
        {
            return false;
        }

        for (var index = 0; index < TrackUnavailableReasons.Count; index++)
        {
            if (string.Equals(TrackUnavailableReasons[index], value, StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }
}
