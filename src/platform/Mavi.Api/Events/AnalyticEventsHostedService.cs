using Mavi.Application.Modules.Events;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Events;

/// <summary>Configuration of the analytic-event derivation sweep (ADR-025 §3).</summary>
public sealed class AnalyticEventsOptions
{
    public const string SectionName = "AnalyticEvents";

    public bool Enabled { get; set; } = true;

    public int IntervalSeconds { get; set; } = 10;

    public int BatchSize { get; set; } = 20;
}

/// <summary>
/// Derives events for fact-bearing analysis units that have none at the current
/// catalogue version. Bounded and sequential, like the scene-analytics host it follows:
/// it shares the API process and must never compete with serving a request.
/// </summary>
public sealed class AnalyticEventsHostedService(
    IServiceScopeFactory scopeFactory,
    IOptions<AnalyticEventsOptions> options,
    TimeProvider timeProvider,
    ILogger<AnalyticEventsHostedService> logger) : BackgroundService
{
    private static readonly Action<ILogger, string, Exception?> LogStarted =
        LoggerMessage.Define<string>(
            LogLevel.Information,
            new EventId(1960, "AnalyticEventsStarted"),
            "Analytic events host started for catalogue {CatalogueVersion}.");

    private static readonly Action<ILogger, int, Exception?> LogDerived =
        LoggerMessage.Define<int>(
            LogLevel.Information,
            new EventId(1961, "AnalyticEventsDerived"),
            "Analytic events derived for {UnitCount} analysis unit(s).");

    private static readonly Action<ILogger, Exception?> LogCycleFailed =
        LoggerMessage.Define(
            LogLevel.Error,
            new EventId(1962, "AnalyticEventsCycleFailed"),
            "An analytic events cycle failed; the host continues with the next one.");

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var configured = options.Value;
        if (!configured.Enabled)
            return;

        LogStarted(logger, RuleCatalogue.Current.CatalogueVersion, null);
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(1, configured.IntervalSeconds)), timeProvider);
        do
        {
            try
            {
                await RunCycleAsync(configured, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
#pragma warning disable CA1031 // One bad cycle must not take the host down with it.
            catch (Exception exception)
#pragma warning restore CA1031
            {
                LogCycleFailed(logger, exception);
            }
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }

    /// <summary>One pass. Public so a test drives exactly one cycle rather than sleeping.</summary>
    public async Task<int> RunCycleAsync(AnalyticEventsOptions configured, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(configured);
        await using var scope = scopeFactory.CreateAsyncScope();
        var service = scope.ServiceProvider.GetRequiredService<AnalyticEventService>();
        var derived = await service.DeriveDueAsync(Math.Max(1, configured.BatchSize), cancellationToken);
        if (derived > 0)
            LogDerived(logger, derived, null);
        return derived;
    }
}
