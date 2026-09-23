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
/// <param name="Failed">Eligible job directories attempted this cycle and still present because reclamation failed.</param>
/// <param name="DeferredByCap">Eligible job directories not attempted this cycle because of <c>MaxDirectoriesPerCycle</c>.</param>
/// <param name="OldestEligibleAgeMinutes">
/// Age of the oldest eligible directory still outstanding after this cycle, whether deferred by the cap or
/// attempted and failed; <see langword="null"/> when nothing eligible is outstanding.
/// </param>
/// <param name="BacklogDepth">
/// Eligible reclaimable work still outstanding after this cycle: <c>DeferredByCap + Failed</c>.
/// </param>
/// <param name="EstimatedCyclesToDrain">
/// ⌈BacklogDepth / MaxDirectoriesPerCycle⌉: the cycles needed if every later attempt succeeds. It does not
/// predict repeated failures; zero only when no eligible work is outstanding.
/// </param>
/// <param name="BacklogState"><c>normal</c>, <c>warning</c> or <c>critical</c>, from <paramref name="OldestEligibleAgeMinutes"/>.</param>
/// <param name="ScanFailed">
/// Job directories that could not be read, so their eligibility was never established. They are not
/// backlog (no deletion authority exists for them) and nothing in them is deleted, but they are reported
/// here and escalate like reclamation failures (1403/1404).
/// </param>
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
    string BacklogState,
    int ScanFailed = 0);

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
    string BacklogState,
    int ScanFailed = 0);
