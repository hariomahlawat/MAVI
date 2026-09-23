using Mavi.Application.Abstractions.Storage;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Storage;

/// <summary>
/// Process-wide janitor state: the overlap gate, per-directory failure streaks, the
/// once-only log memory and the last cycle's health.
/// </summary>
/// <remarks>
/// Every collection is rebuilt from the entries seen in the latest cycle, so its size is
/// bounded by what is currently under <c>staging/</c> and nothing is remembered for a
/// directory that no longer exists.
/// </remarks>
public sealed class StagingJanitorState(IOptions<StagingJanitorOptions> options) : IStagingJanitorMonitor
{
    private readonly Lock _sync = new();
    private Dictionary<string, int> _failureStreaks = new(StringComparer.Ordinal);
    private HashSet<string> _reported = new(StringComparer.Ordinal);
    private StagingJanitorHealth? _health;

    /// <summary>One cycle at a time per host.</summary>
    internal SemaphoreSlim Gate { get; } = new(1, 1);

    public StagingJanitorHealth Current
    {
        get
        {
            lock (_sync)
            {
                return (_health ?? new StagingJanitorHealth(options.Value.Enabled, null, 0, 0, 0, 0, null, 0, "normal"))
                    with { Enabled = options.Value.Enabled };
            }
        }
    }

    /// <summary>Returns the new consecutive-failure count for <paramref name="key"/>.</summary>
    internal int RecordFailure(string key)
    {
        lock (_sync)
        {
            var streak = _failureStreaks.GetValueOrDefault(key) + 1;
            _failureStreaks[key] = streak;
            return streak;
        }
    }

    internal void RecordSuccess(string key)
    {
        lock (_sync)
            _failureStreaks.Remove(key);
    }

    /// <summary>True the first time <paramref name="key"/> is reported while it stays present.</summary>
    internal bool FirstReport(string key)
    {
        lock (_sync)
            return _reported.Add(key);
    }

    internal void CompleteCycle(
        StagingJanitorCycleResult result,
        DateTimeOffset nowUtc,
        IReadOnlySet<string> presentKeys)
    {
        lock (_sync)
        {
            _failureStreaks = _failureStreaks
                .Where(item => presentKeys.Contains(item.Key))
                .ToDictionary(item => item.Key, item => item.Value, StringComparer.Ordinal);
            _reported = new HashSet<string>(_reported.Where(item => presentKeys.Contains(item)), StringComparer.Ordinal);
            _health = new StagingJanitorHealth(
                options.Value.Enabled,
                nowUtc,
                result.Removed,
                result.Failed,
                result.DeferredByCap,
                result.BacklogDepth,
                result.OldestEligibleAgeMinutes,
                _failureStreaks.Count == 0 ? 0 : _failureStreaks.Values.Max(),
                result.BacklogState);
        }
    }
}
