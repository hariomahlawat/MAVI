namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// The activation gate and tuning surface of asynchronous finalization (S1.4 B3 asynchronous
/// finalization plan §15.2; F3 plan §6.1). It is one release decision that switches the whole
/// externally visible boundary together: which completion versions <c>GET /api/vision/contract</c>
/// advertises, which <c>POST …/complete</c> accepts, whether a job can enter <c>Finalizing</c>
/// at all, and whether the hosted finalizer claims and publishes.
/// </summary>
/// <remarks>
/// <para>
/// <see cref="Enabled"/> = <c>false</c> (the production default until the controlled activation
/// after F3 review): the platform advertises and accepts completion 2.0 and 3.0, both
/// synchronous, and refuses 3.1. No job can become Finalizing. The finalizer host only
/// refreshes its read-only health counts, so a stranded Finalizing row stays visible.
/// </para>
/// <para>
/// <see cref="Enabled"/> = <c>true</c> (set together with the worker's
/// <c>MAVI_COMPLETION_SCHEMA_VERSION=3.1</c>): the platform advertises and accepts 2.0 and
/// 3.1, 3.0 is retired, and 3.1 is the durable hand-off consumed by the hosted finalizer.
/// There is no fallback in either direction: a worker whose version the platform does not
/// advertise fails closed at its capability probe and leases nothing.
/// </para>
/// <para>
/// The timing values below are development defaults. The production values are frozen by
/// the F4 requalification from product requirements plus measurement. The effective bound
/// on a finalization is <b>not</b> <see cref="MaximumFinalizationDurationSeconds"/> alone:
/// the deadline stops new claims and extensions, but a claim that is live at the deadline
/// runs to its granted expiry, so a job is Completed or Failed no later than
/// <c>FinalizationAcceptedAtUtc + MaximumFinalizationDurationSeconds + ClaimSeconds</c>
/// (plus one poll interval for reconciliation to observe it).
/// </para>
/// </remarks>
public sealed class VisionFinalizationOptions
{
    public const string SectionName = "VisionFinalization";

    public bool Enabled { get; init; }

    /// <summary>How many finalizations this host executes at once. One: the host shares the API process.</summary>
    public int MaxConcurrentFinalizations { get; init; } = 1;

    /// <summary>How often the host reconciles, refreshes health and looks for a claimable job.</summary>
    public int PollIntervalSeconds { get; init; } = 5;

    /// <summary>The initial ownership window of a claim.</summary>
    public int ClaimSeconds { get; init; } = 300;

    /// <summary>The renewal granted after each sealing batch; never longer than <see cref="ClaimSeconds"/>.</summary>
    public int ClaimExtensionSeconds { get; init; } = 300;

    /// <summary>Automatic claims (first plus reclaims) before reconciliation exhausts the job.</summary>
    public int MaximumFinalizationAttempts { get; init; } = 3;

    /// <summary>
    /// The absolute deadline after the hand-off: past <c>FinalizationAcceptedAtUtc</c> plus this,
    /// no claim is created or extended. Development default; F4 freezes the production value.
    /// </summary>
    public int MaximumFinalizationDurationSeconds { get; init; } = 21_600;

    /// <summary>Objects sealed between two ownership revalidations (claim extensions).</summary>
    public int SealingBatchSize { get; init; } = 200;

    /// <summary>Delay after a job's terminal transition before its retained payload row is deleted.</summary>
    public int PayloadCleanupGraceSeconds { get; init; }

    public TimeSpan PollInterval => TimeSpan.FromSeconds(PollIntervalSeconds);

    /// <summary>
    /// The upper bound on how long a job can remain Finalizing after its hand-off, as enforced:
    /// the deadline plus the one claim lifetime that may still be live at the deadline.
    /// </summary>
    public TimeSpan EffectiveMaximumFinalizationBound =>
        TimeSpan.FromSeconds(MaximumFinalizationDurationSeconds + ClaimSeconds);

    public VisionFinalizationPolicy ToPolicy() => new(
        TimeSpan.FromSeconds(ClaimSeconds),
        TimeSpan.FromSeconds(ClaimExtensionSeconds),
        MaximumFinalizationAttempts,
        TimeSpan.FromSeconds(MaximumFinalizationDurationSeconds),
        SealingBatchSize);

    /// <summary>Every range and cross-field rule, as one message per violation (empty when valid).</summary>
    public IReadOnlyList<string> Validate()
    {
        var problems = new List<string>();
        if (MaxConcurrentFinalizations is < 1 or > 8)
            problems.Add("VisionFinalization:MaxConcurrentFinalizations must be between 1 and 8.");
        if (PollIntervalSeconds is < 1 or > 300)
            problems.Add("VisionFinalization:PollIntervalSeconds must be between 1 and 300.");
        if (ClaimSeconds is < 30 or > 86_400)
            problems.Add("VisionFinalization:ClaimSeconds must be between 30 and 86400.");
        if (ClaimExtensionSeconds is < 30 or > 86_400)
            problems.Add("VisionFinalization:ClaimExtensionSeconds must be between 30 and 86400.");
        if (ClaimExtensionSeconds > ClaimSeconds)
            problems.Add("VisionFinalization:ClaimExtensionSeconds must not exceed ClaimSeconds: an extension renews for at most one claim duration.");
        if (MaximumFinalizationAttempts is < 1 or > 20)
            problems.Add("VisionFinalization:MaximumFinalizationAttempts must be between 1 and 20.");
        if (MaximumFinalizationDurationSeconds is < 1 or > 604_800)
            problems.Add("VisionFinalization:MaximumFinalizationDurationSeconds must be between 1 and 604800.");
        if (MaximumFinalizationDurationSeconds < ClaimSeconds)
            problems.Add("VisionFinalization:MaximumFinalizationDurationSeconds must be at least ClaimSeconds, or no claim could ever be legal.");
        if (SealingBatchSize is < 1 or > 5000)
            problems.Add("VisionFinalization:SealingBatchSize must be between 1 and 5000.");
        if (PayloadCleanupGraceSeconds is < 0 or > 86_400)
            problems.Add("VisionFinalization:PayloadCleanupGraceSeconds must be between 0 and 86400.");
        return problems;
    }
}
