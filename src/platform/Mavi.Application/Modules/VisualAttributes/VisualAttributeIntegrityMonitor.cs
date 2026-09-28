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
public sealed class VisualAttributeIntegrityMonitor
{
    private readonly Lock _gate = new();
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

    public void RecordCompletionIncidents(Guid analysisId, int count, DateTimeOffset nowUtc)
    {
        lock (_gate)
        {
            _completions += count;
            _lastUtc = nowUtc;
            _lastAnalysisId = analysisId;
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
