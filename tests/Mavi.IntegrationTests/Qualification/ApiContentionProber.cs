using System.Collections.Concurrent;
using System.Diagnostics;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// API-host contention during finalization (F4 plan §20): a background client that cycles a
/// fixed set of read endpoints at a fixed rate and records each latency against the current
/// phase (<c>baseline</c> before the hand-off, <c>during</c> while Finalizing). Informational:
/// no latency threshold is invented; only a failed request during finalization is a finding.
/// </summary>
internal sealed class ApiContentionProber : IAsyncDisposable
{
    private readonly HttpClient _client;
    private readonly IReadOnlyList<string> _endpoints;
    private readonly TimeSpan _interval;
    private readonly ConcurrentQueue<(string Phase, string Endpoint, double Ms, bool Ok)> _samples = new();
    private readonly CancellationTokenSource _stop = new();
    private volatile string _phase = "baseline";
    private Task? _loop;

    public ApiContentionProber(HttpClient client, IReadOnlyList<string> endpoints, TimeSpan interval)
    {
        _client = client;
        _endpoints = endpoints;
        _interval = interval;
    }

    public void Start() => _loop = Task.Run(() => LoopAsync(_stop.Token));

    public void Phase(string phase) => _phase = phase;

    private async Task LoopAsync(CancellationToken cancellationToken)
    {
        var next = 0;
        while (!cancellationToken.IsCancellationRequested)
        {
            var endpoint = _endpoints[next++ % _endpoints.Count];
            var phase = _phase;
            var stopwatch = Stopwatch.StartNew();
            bool ok;
            try
            {
                using var response = await _client.GetAsync(endpoint, cancellationToken);
                ok = response.IsSuccessStatusCode;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                return;
            }
            catch (HttpRequestException)
            {
                ok = false;
            }

            _samples.Enqueue((phase, endpoint, stopwatch.Elapsed.TotalMilliseconds, ok));
            try
            {
                await Task.Delay(_interval, cancellationToken);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    public object Result()
    {
        var samples = _samples.ToArray();
        double? P95(string endpoint, string phase)
        {
            var values = samples.Where(s => s.Endpoint == endpoint && s.Phase == phase && s.Ok).Select(s => s.Ms).ToList();
            return values.Count == 0 ? null : S1QualificationSupport.Percentile(values, 0.95);
        }

        return new
        {
            endpoints = _endpoints.Select(endpoint => new
            {
                endpoint,
                baselineP95Ms = P95(endpoint, "baseline"),
                duringP95Ms = P95(endpoint, "during"),
                baselineN = samples.Count(s => s.Endpoint == endpoint && s.Phase == "baseline"),
                duringN = samples.Count(s => s.Endpoint == endpoint && s.Phase == "during"),
                errors = samples.Count(s => s.Endpoint == endpoint && !s.Ok),
            }).ToArray(),
            errorsDuringFinalization = samples.Count(s => s.Phase == "during" && !s.Ok),
            intervalMs = _interval.TotalMilliseconds,
        };
    }

    public async ValueTask DisposeAsync()
    {
        await _stop.CancelAsync();
        if (_loop is not null) await _loop;
        _stop.Dispose();
    }
}
