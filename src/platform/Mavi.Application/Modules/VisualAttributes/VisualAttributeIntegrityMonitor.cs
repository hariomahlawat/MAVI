namespace Mavi.Application.Modules.VisualAttributes;

public sealed record VisualAttributeIntegrityHealth(
    long EvidenceReadIncidents,
    long CompletionIncidents,
    DateTimeOffset? LastIncidentUtc,
    Guid? LastIncidentAnalysisId);

/// <summary>
/// The operator-visible integrity signal (S2b plan §10): accepted evidence that is missing or
/// whose bytes disagree with its record. Every incident is also an Error log with a stable
/// event id; this holds the counts <c>/api/health</c> reports.
/// </summary>
/// <remarks>
/// A completion incident is one accepted crop a worker reported missing or corrupt, counted
/// once: the same crop reported again — by the retry of an ambiguous commit, or by a later
/// attempt that reads it again — is the same incident. The remembered crops are bounded; past
/// the bound the oldest is forgotten, at worst counting a long-past crop twice.
/// </remarks>
public sealed class VisualAttributeIntegrityMonitor
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

    public VisualAttributeIntegrityHealth Current
    {
        get
        {
            lock (_gate) return new VisualAttributeIntegrityHealth(_reads, _completions, _lastUtc, _lastAnalysisId);
        }
    }
}
