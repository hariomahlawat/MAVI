namespace Mavi.Application.Modules.VisualAttributes;

/// <summary>
/// Which attributes workers have polled recently, by identity (S2b plan §5: operator
/// diagnostics distinguish "no READY attributes worker" from ordinary pending work).
/// </summary>
/// <remarks>
/// A worker leases only while READY (plan §8), so a recent lease poll is the platform's proof
/// of a READY worker; no new lifecycle state is involved. In-process and bounded: it is a
/// diagnostic, not an authority, and forgets on restart.
/// </remarks>
public sealed class VisualAttributeWorkerPresence(TimeProvider clock)
{
    public const int MaximumTrackedWorkers = 256;
    private readonly Lock _gate = new();
    private readonly Dictionary<string, (string Fingerprint, DateTimeOffset SeenAtUtc)> _workers = new(StringComparer.Ordinal);

    public void RecordPoll(string workerId, string identityFingerprint)
    {
        lock (_gate)
        {
            if (!_workers.ContainsKey(workerId) && _workers.Count >= MaximumTrackedWorkers)
            {
                var oldest = _workers.MinBy(entry => entry.Value.SeenAtUtc).Key;
                _workers.Remove(oldest);
            }

            _workers[workerId] = (identityFingerprint, clock.GetUtcNow());
        }
    }

    /// <summary>The most recent poll for this identity within the window, if any.</summary>
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

    /// <summary>Recent workers presenting another identity: a binding mismatch an operator must see.</summary>
    public IReadOnlyList<string> RecentOtherIdentities(string identityFingerprint, TimeSpan window)
    {
        var cutoff = clock.GetUtcNow() - window;
        lock (_gate)
        {
            return _workers.Values
                .Where(entry => entry.Fingerprint != identityFingerprint && entry.SeenAtUtc >= cutoff)
                .Select(entry => entry.Fingerprint)
                .Distinct(StringComparer.Ordinal)
                .Order(StringComparer.Ordinal)
                .ToList();
        }
    }
}
