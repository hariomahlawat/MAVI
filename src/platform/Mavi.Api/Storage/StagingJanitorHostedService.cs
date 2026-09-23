using Mavi.Application.Abstractions.Storage;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Storage;

/// <summary>
/// Schedules the staging janitor: one cycle at host start (after database migration) and
/// one every <c>StagingJanitor:IntervalMinutes</c>.
/// </summary>
/// <remarks>
/// Scheduling only, following the <c>SceneAnalyticsHostedService</c> / lifecycle split: what
/// is deletable, and how it is deleted, belongs to <see cref="IStagingJanitor"/>. A failing
/// or lagging janitor never blocks completion, leasing or serving; a failed cycle is logged
/// and the next one runs on schedule.
/// </remarks>
public sealed partial class StagingJanitorHostedService(
    IServiceScopeFactory scopeFactory,
    IOptions<StagingJanitorOptions> options,
    TimeProvider timeProvider,
    ILogger<StagingJanitorHostedService> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var configured = options.Value;
        if (!configured.Enabled)
        {
            LogDisabled(logger);
            return;
        }

        if (!StagingJanitor.IsPlatformSupported)
        {
            // Fail closed: without a verified handle-relative implementation nothing is deleted.
            LogUnsupported(logger);
            return;
        }

        LogStarted(logger, configured.IntervalMinutes, configured.GraceMinutes, configured.MaxDirectoriesPerCycle);
        using var timer = new PeriodicTimer(configured.Interval, timeProvider);
        do
        {
            try
            {
                await RunCycleAsync(stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
#pragma warning disable CA1031 // One failed cycle (database or media root unavailable) must not stop the host or the schedule.
            catch (Exception exception)
#pragma warning restore CA1031
            {
                LogCycleFailed(logger, exception);
            }
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }

    /// <summary>One cycle in its own scope; public so a test drives it without waiting on a timer.</summary>
    public async Task<StagingJanitorCycleResult> RunCycleAsync(CancellationToken cancellationToken)
    {
        await using var scope = scopeFactory.CreateAsyncScope();
        return await scope.ServiceProvider.GetRequiredService<IStagingJanitor>().RunCycleAsync(cancellationToken);
    }

    [LoggerMessage(EventId = 1410, EventName = "staging_janitor_disabled", Level = LogLevel.Warning,
        Message = "Staging janitor is disabled; worker staging is not reclaimed until it is re-enabled.")]
    private static partial void LogDisabled(ILogger logger);

    [LoggerMessage(EventId = 1411, EventName = "staging_janitor_unsupported", Level = LogLevel.Error,
        Message = "Staging janitor has no handle-relative implementation for this platform and will not delete anything.")]
    private static partial void LogUnsupported(ILogger logger);

    [LoggerMessage(EventId = 1412, EventName = "staging_janitor_started", Level = LogLevel.Information,
        Message = "Staging janitor started: every {IntervalMinutes} min, grace {GraceMinutes} min, at most {MaxDirectories} directories per cycle.")]
    private static partial void LogStarted(ILogger logger, int intervalMinutes, int graceMinutes, int maxDirectories);

    [LoggerMessage(EventId = 1413, EventName = "staging_janitor_cycle_failed", Level = LogLevel.Error,
        Message = "A staging janitor cycle failed; the next cycle runs on schedule.")]
    private static partial void LogCycleFailed(ILogger logger, Exception exception);
}
