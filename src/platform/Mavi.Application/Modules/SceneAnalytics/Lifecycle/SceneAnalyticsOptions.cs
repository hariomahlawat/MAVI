namespace Mavi.Application.Modules.SceneAnalytics.Lifecycle;

/// <summary>
/// How the analytics host schedules and bounds its work.
/// </summary>
/// <remarks>
/// <para>
/// The relationship that matters is between <see cref="LeaseSeconds"/> and
/// <see cref="MaxUnitDurationSeconds"/>. There is no heartbeat in v1, so the lease is
/// the only thing standing between a slow attempt and being reclaimed underneath itself;
/// it must exceed the longest execution the host will permit, with margin. Start-up
/// validation refuses a configuration where it does not, because the failure it would
/// otherwise cause — attempts reclaimed while still succeeding — looks like a bug in the
/// fencing rather than a misconfiguration.
/// </para>
/// <para>
/// Every duration is seconds, as the platform's other options are.
/// </para>
/// </remarks>
public sealed class SceneAnalyticsOptions
{
    public const string SectionName = "SceneAnalytics";

    /// <summary>Whether the host runs its loops at all.</summary>
    public bool Enabled { get; init; } = true;

    /// <summary>How often to look for runs that need a unit, and for units to terminate.</summary>
    public int ReconcileIntervalSeconds { get; init; } = 5;

    /// <summary>How long a claim owns its unit before the unit becomes reclaimable.</summary>
    public int LeaseSeconds { get; init; } = 900;

    /// <summary>The cancellation bound on one unit's execution.</summary>
    public int MaxUnitDurationSeconds { get; init; } = 300;

    /// <summary>
    /// How long past its lease a unit is left alone before it is reclaimed or terminated.
    /// </summary>
    /// <remarks>
    /// Without it, the last permitted attempt could be marked exhausted in the instant it
    /// was succeeding.
    /// </remarks>
    public int ReclaimGraceSeconds { get; init; } = 60;

    /// <summary>Automatic attempts within one retry cycle.</summary>
    public int MaximumAttempts { get; init; } = 3;

    /// <summary>
    /// How many units the host executes at once. One in Development: the host shares the
    /// API process, and analytics must not compete with serving requests.
    /// </summary>
    public int MaxConcurrentUnits { get; init; } = 1;

    /// <summary>How many units one reconcile pass may queue.</summary>
    public int ReconcileBatchSize { get; init; } = 50;

    /// <summary>
    /// How far back automatic reconciliation reaches for runs that completed before the
    /// host started.
    /// </summary>
    /// <remarks>
    /// Older runs are analysed only on explicit request. A deployment that suddenly
    /// queued every historical run would be a surprise, not a feature.
    /// </remarks>
    public int ReconcileLookbackDays { get; init; } = 7;

    /// <summary>
    /// The fixed cutoff for automatic reconciliation, derived from when the host started.
    /// </summary>
    /// <remarks>
    /// Deliberately a function of host start and nothing else. Deriving it from the
    /// current time would make it crawl forward on every cycle, so a lookback of zero —
    /// meaning "do not backfill history" — would also stop new work being analysed once
    /// it was a cycle old. The lookback bounds how far back a starting host reaches.
    /// </remarks>
    public DateTimeOffset ReconcileFloor(DateTimeOffset hostStartedAtUtc) =>
        hostStartedAtUtc.AddDays(-ReconcileLookbackDays);

    public SceneAnalysisLeasePolicy ToLeasePolicy() => new(
        TimeSpan.FromSeconds(LeaseSeconds),
        TimeSpan.FromSeconds(ReclaimGraceSeconds),
        MaximumAttempts);
}
