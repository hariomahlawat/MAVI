using Mavi.Domain.Plates;
using Microsoft.Extensions.Options;

namespace Mavi.Application.Modules.Plates;

/// <summary>
/// Which plates workers have polled recently, by identity: operator diagnostics distinguish "no READY
/// plates worker" from ordinary pending work. A worker leases only while READY, so a recent lease poll is
/// the proof. In-process and bounded: a diagnostic, not an authority.
/// </summary>
public sealed class PlateWorkerPresence(TimeProvider clock)
{
    public const int MaximumTrackedWorkers = 256;
    private readonly Lock _gate = new();
    private readonly Dictionary<string, (string Fingerprint, DateTimeOffset SeenAtUtc)> _workers = new(StringComparer.Ordinal);

    public void RecordPoll(string workerId, string identityFingerprint)
    {
        lock (_gate)
        {
            if (!_workers.ContainsKey(workerId) && _workers.Count >= MaximumTrackedWorkers)
                _workers.Remove(_workers.MinBy(entry => entry.Value.SeenAtUtc).Key);
            _workers[workerId] = (identityFingerprint, clock.GetUtcNow());
        }
    }

    public DateTimeOffset? LastReadyPoll(string identityFingerprint, TimeSpan window)
    {
        var cutoff = clock.GetUtcNow() - window;
        lock (_gate)
        {
            DateTimeOffset? latest = null;
            foreach (var (fingerprint, seenAtUtc) in _workers.Values)
            {
                if (fingerprint == identityFingerprint && seenAtUtc >= cutoff && (latest is null || seenAtUtc > latest))
                    latest = seenAtUtc;
            }

            return latest;
        }
    }
}

public sealed record PlateIntegrityHealth(
    long EvidenceReadIncidents,
    long CompletionIncidents,
    DateTimeOffset? LastIncidentUtc,
    Guid? LastIncidentAnalysisId);

/// <summary>
/// The operator-visible plate integrity signal (ADR-013 item 3): accepted evidence that is missing or
/// whose bytes disagree with its record. A completion incident is one crop a worker reported missing or
/// corrupt, counted once however often it is reported again.
/// </summary>
public sealed class PlateIntegrityMonitor
{
    public const int MaximumRememberedCrops = 65_536;

    private readonly Lock _gate = new();
    private readonly HashSet<Guid> _reportedCrops = [];
    private readonly Queue<Guid> _reportedOrder = new();
    private long _reads;
    private long _completions;
    private DateTimeOffset? _lastUtc;
    private Guid? _lastAnalysisId;

    public void RecordEvidenceReadIncident(Guid analysisId, DateTimeOffset nowUtc)
    {
        lock (_gate)
        {
            _reads++;
            _lastUtc = nowUtc;
            _lastAnalysisId = analysisId;
        }
    }

    /// <returns>How many of the crops were not already counted.</returns>
    public int RecordCompletionIncidents(Guid analysisId, IReadOnlyCollection<Guid> observationIds, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(observationIds);
        lock (_gate)
        {
            var added = 0;
            foreach (var observationId in observationIds)
            {
                if (!_reportedCrops.Add(observationId)) continue;
                _reportedOrder.Enqueue(observationId);
                if (_reportedOrder.Count > MaximumRememberedCrops) _reportedCrops.Remove(_reportedOrder.Dequeue());
                added++;
            }

            if (added == 0) return 0;
            _completions += added;
            _lastUtc = nowUtc;
            _lastAnalysisId = analysisId;
            return added;
        }
    }

    public PlateIntegrityHealth Current
    {
        get
        {
            lock (_gate) return new PlateIntegrityHealth(_reads, _completions, _lastUtc, _lastAnalysisId);
        }
    }
}

public interface IPlateReadinessReader
{
    /// <summary>The run's facts, or <see langword="null"/> when no such run exists.</summary>
    Task<PlateRunFacts?> ReadAsync(Guid processingRunId, string? preferredFingerprint, CancellationToken cancellationToken);
}

/// <summary>Run-level plate readiness (<c>GET /api/processing/runs/{id}/plates</c>), by <see cref="PlateReadinessRule"/>.</summary>
public sealed class PlateReadinessService(
    IPlateRelease release,
    IPlateReadinessReader reader,
    PlateWorkerPresence presence,
    IOptions<PlateOptions> options)
{
    public async Task<PlateReadiness?> GetAsync(Guid processingRunId, CancellationToken cancellationToken)
    {
        var fingerprint = release.Resolution.Definition?.Identity.Fingerprint;
        var facts = await reader.ReadAsync(processingRunId, fingerprint, cancellationToken);
        if (facts is null) return null;
        var lastPoll = fingerprint is null
            ? null
            : presence.LastReadyPoll(fingerprint, TimeSpan.FromSeconds(options.Value.WorkerPresenceSeconds));
        return PlateReadinessRule.Evaluate(processingRunId, fingerprint, release.Resolution.NotConfiguredReason, facts, lastPoll);
    }
}
