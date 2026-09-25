namespace Mavi.Application.Modules.Intelligence;

/// <summary>Read-only finalizer status for the platform health details (F3 plan §6.9).</summary>
public interface IVisionFinalizationMonitor
{
    VisionFinalizationHealth Current { get; }
}

/// <summary>
/// The finalizer as <c>/api/health</c> reports it. The counts are PostgreSQL's answer about
/// Finalizing rows across every host, refreshed by this host on every cycle (and, read-only,
/// while the gate is off); the in-flight and last-cycle facts are this host's own.
/// </summary>
/// <param name="FinalizingJobs">Rows with <c>status = 'Finalizing'</c>; the value the rollback procedure waits on.</param>
/// <param name="LiveClaims">Of those, canonical claims whose expiry is in the future at count time.</param>
/// <param name="MalformedClaims">Of those, rows whose claim metadata is non-canonical; they never drain on their own.</param>
/// <param name="CountsRefreshedAtUtc"><see langword="null"/> until the first successful count; a stale value is recognisable by it.</param>
public sealed record VisionFinalizationHealth(
    bool Enabled,
    int FinalizingJobs,
    int LiveClaims,
    int MalformedClaims,
    DateTimeOffset? OldestFinalizingAcceptedAtUtc,
    DateTimeOffset? CountsRefreshedAtUtc,
    int InFlight,
    DateTimeOffset? LastCycleUtc,
    int LastCycleClaimed,
    int LastCycleExhausted,
    int LastCyclePayloadsCleaned);
