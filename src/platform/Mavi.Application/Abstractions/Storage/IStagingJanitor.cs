namespace Mavi.Application.Abstractions.Storage;

/// <summary>
/// Platform-owned reclamation of worker attempt staging, with the VisionJob row as the
/// sole authority on which attempt directories are dead (S1.2 plan §6.5).
/// </summary>
public interface IStagingJanitor
{
    /// <summary>Runs one complete, idempotent reclamation cycle.</summary>
    Task<StagingJanitorCycleResult> RunCycleAsync(CancellationToken cancellationToken);
}

/// <summary>The EventId 1400 cycle summary.</summary>
/// <param name="Scanned">Job directories seen under <c>staging/</c>.</param>
/// <param name="Eligible">Job directories reclaimable now.</param>
/// <param name="Processed">Eligible job directories this cycle attempted (at most the per-cycle cap).</param>
/// <param name="Removed">Processed job directories fully reclaimed.</param>
/// <param name="FreedBytes">Regular-file bytes removed.</param>
/// <param name="Failed">Processed job directories left in place by a failure.</param>
/// <param name="DeferredByCap">Eligible job directories left for a later cycle by the cap.</param>
/// <param name="OldestEligibleAgeMinutes">Age of the oldest eligible directory still present after this cycle.</param>
/// <param name="BacklogDepth">Equal to <paramref name="DeferredByCap"/>.</param>
/// <param name="EstimatedCyclesToDrain">⌈BacklogDepth / MaxDirectoriesPerCycle⌉.</param>
/// <param name="BacklogState"><c>normal</c>, <c>warning</c> or <c>critical</c>.</param>
public sealed record StagingJanitorCycleResult(
    int Scanned,
    int Eligible,
    int Processed,
    int Removed,
    long FreedBytes,
    int Failed,
    int DeferredByCap,
    double? OldestEligibleAgeMinutes,
    int BacklogDepth,
    int EstimatedCyclesToDrain,
    string BacklogState);

/// <summary>Read-only janitor status for the platform health details.</summary>
public interface IStagingJanitorMonitor
{
    StagingJanitorHealth Current { get; }
}

public sealed record StagingJanitorHealth(
    bool Enabled,
    DateTimeOffset? LastRunUtc,
    int LastCycleRemoved,
    int Failed,
    int DeferredByCap,
    int BacklogDepth,
    double? OldestEligibleAgeMinutes,
    int ConsecutiveFailures,
    string BacklogState);
