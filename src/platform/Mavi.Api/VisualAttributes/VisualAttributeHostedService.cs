using Mavi.Application.Modules.VisualAttributes;
using Microsoft.Extensions.Options;

namespace Mavi.Api.VisualAttributes;

/// <summary>
/// The platform's Visual Attribute authority loop (S2b plan §7, §8, §12): records the
/// preferred identity's activation, queues eligible runs, fails units past their deadline or
/// out of attempts — none of which may wait for a worker to poll — and reclaims attribute
/// staging. With the release removed it only sweeps and reclaims: existing units still end.
/// </summary>
/// <remarks>
/// Scheduling only; what is eligible, and how, belongs to <see cref="IVisualAttributeLifecycle"/>
/// and <see cref="IVisualAttributeStagingJanitor"/>. A failed cycle is logged and the next
/// runs on schedule; it never blocks leasing, serving or the vision plane.
/// </remarks>
public sealed partial class VisualAttributeHostedService(
    IServiceScopeFactory scopeFactory,
    IVisualAttributeRelease release,
    IOptions<VisualAttributeOptions> options,
    TimeProvider timeProvider,
    ILogger<VisualAttributeHostedService> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var configured = options.Value;
        if (!configured.Enabled)
        {
            LogIdle(logger, configured.Enabled, release.Resolution.NotConfiguredReason ?? "configured");
            return;
        }

        // Without a release nothing new is queued, but units already queued or running must still
        // reach an outcome and their staging must still be reclaimed.
        if (release.Resolution.Definition is null)
            LogLifecycleOnly(logger, release.Resolution.NotConfiguredReason ?? "not_configured");

        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(configured.ReconcileIntervalSeconds), timeProvider);
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
#pragma warning disable CA1031 // One failed cycle must not stop the host or the schedule.
            catch (Exception exception)
#pragma warning restore CA1031
            {
                LogCycleFailed(logger, exception);
            }
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }

    /// <summary>One cycle in its own scope; public so a test drives it without a timer.</summary>
    public async Task<VisualAttributeCycleResult> RunCycleAsync(CancellationToken cancellationToken)
    {
        var definition = release.Resolution.Definition;
        var configured = options.Value;
        await using var scope = scopeFactory.CreateAsyncScope();
        var lifecycle = scope.ServiceProvider.GetRequiredService<IVisualAttributeLifecycle>();
        var queued = 0;
        if (definition is not null)
        {
            var activatedAtUtc = await lifecycle.EnsureActivationAsync(definition, cancellationToken);
            queued = await lifecycle.QueueEligibleAsync(definition, activatedAtUtc, configured.ReconcileBatchSize, cancellationToken);
        }

        var sweep = await lifecycle.SweepAsync(configured.LeasePolicy, configured.ReconcileBatchSize, cancellationToken);
        var janitor = await scope.ServiceProvider.GetRequiredService<IVisualAttributeStagingJanitor>().RunCycleAsync(cancellationToken);
        var result = new VisualAttributeCycleResult(queued, sweep.DeadlineFailed, sweep.ExhaustedFailed, janitor);
        if (queued + sweep.DeadlineFailed + sweep.ExhaustedFailed + janitor > 0)
            LogCycle(logger, queued, sweep.DeadlineFailed, sweep.ExhaustedFailed, janitor);
        return result;
    }

    [LoggerMessage(EventId = 1970, EventName = "visual_attribute_host_idle", Level = LogLevel.Information,
        Message = "Visual attribute host is idle (enabled: {Enabled}; release: {Reason}).")]
    private static partial void LogIdle(ILogger logger, bool enabled, string reason);

    [LoggerMessage(EventId = 1973, EventName = "visual_attribute_host_lifecycle_only", Level = LogLevel.Information,
        Message = "Visual attribute release is not configured ({Reason}): nothing new is queued; existing units are still swept and their staging reclaimed.")]
    private static partial void LogLifecycleOnly(ILogger logger, string reason);

    [LoggerMessage(EventId = 1971, EventName = "visual_attribute_cycle", Level = LogLevel.Information,
        Message = "Visual attribute cycle: queued {Queued}, deadline-failed {DeadlineFailed}, exhausted {Exhausted}, staging removed {StagingRemoved}.")]
    private static partial void LogCycle(ILogger logger, int queued, int deadlineFailed, int exhausted, int stagingRemoved);

    [LoggerMessage(EventId = 1972, EventName = "visual_attribute_cycle_failed", Level = LogLevel.Error,
        Message = "Visual attribute cycle failed; the next cycle runs on schedule.")]
    private static partial void LogCycleFailed(ILogger logger, Exception exception);
}

public sealed record VisualAttributeCycleResult(int Queued, int DeadlineFailed, int ExhaustedFailed, int StagingRemoved);
