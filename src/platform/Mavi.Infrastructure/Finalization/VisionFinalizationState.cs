using Mavi.Application.Modules.Intelligence;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Finalization;

/// <summary>
/// Process-wide finalizer state: the last counts PostgreSQL gave, this host's in-flight
/// executions and last-cycle facts, and the once-per-host-lifetime memory for malformed-row
/// reports. Nothing here is authority; it is what health shows.
/// </summary>
public sealed class VisionFinalizationState(IOptions<VisionFinalizationOptions> options) : IVisionFinalizationMonitor
{
    private readonly Lock _sync = new();
    private readonly HashSet<Guid> _reported = [];
    private VisionFinalizationCounts _counts = new(0, 0, 0, null);
    private DateTimeOffset? _countsRefreshedAtUtc;
    private int _inFlight;
    private DateTimeOffset? _lastCycleUtc;
    private int _lastCycleClaimed;
    private int _lastCycleExhausted;
    private int _lastCyclePayloadsCleaned;

    public VisionFinalizationHealth Current
    {
        get
        {
            lock (_sync)
            {
                return new VisionFinalizationHealth(
                    options.Value.Enabled,
                    _counts.FinalizingJobs,
                    _counts.LiveClaims,
                    _counts.MalformedClaims,
                    _counts.OldestFinalizingAcceptedAtUtc,
                    _countsRefreshedAtUtc,
                    _inFlight,
                    _lastCycleUtc,
                    _lastCycleClaimed,
                    _lastCycleExhausted,
                    _lastCyclePayloadsCleaned);
            }
        }
    }

    public void RecordCounts(VisionFinalizationCounts counts, DateTimeOffset nowUtc)
    {
        lock (_sync)
        {
            _counts = counts;
            _countsRefreshedAtUtc = nowUtc;
        }
    }

    public void RecordCycle(DateTimeOffset nowUtc, int claimed, int exhausted, int payloadsCleaned)
    {
        lock (_sync)
        {
            _lastCycleUtc = nowUtc;
            _lastCycleClaimed = claimed;
            _lastCycleExhausted = exhausted;
            _lastCyclePayloadsCleaned = payloadsCleaned;
        }
    }

    public int BeginExecution()
    {
        lock (_sync)
            return ++_inFlight;
    }

    public void EndExecution()
    {
        lock (_sync)
            _inFlight--;
    }

    /// <summary>True the first time <paramref name="jobId"/> is reported in this host's lifetime.</summary>
    public bool FirstReport(Guid jobId)
    {
        lock (_sync)
            return _reported.Add(jobId);
    }
}
