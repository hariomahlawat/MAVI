using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Api.SceneAnalytics;

/// <summary>
/// The platform's analytics host: it queues the units that are due, terminates the ones
/// that were abandoned, and executes the ones it can claim.
/// </summary>
/// <remarks>
/// <para>
/// It lives in the API host, as ADR-011 decision 1 and plan section G place it: the
/// platform's first <c>BackgroundService</c>, in the process ADR-008 already puts on the
/// operational plane. Keeping it here also keeps <c>Mavi.Infrastructure</c> free of a
/// hosting dependency it otherwise has no use for.
/// </para>
/// <para>
/// Both loops live in one background service and run in sequence, because the work is
/// small, bounded and deliberately unhurried. <c>MaxConcurrentUnits</c> defaults to one:
/// this service shares the API process, and analytics must never compete with serving an
/// operator's request.
/// </para>
/// <para>
/// The service owns scheduling and nothing else. It decides <i>when</i> a transition is
/// attempted; what a transition means, and every lock and fence it takes, belongs to
/// <see cref="ISceneAnalysisLifecycle"/>. That separation is what lets the lifecycle be
/// tested for concurrency without a host, and the host be tested for scheduling without
/// racing a real clock.
/// </para>
/// </remarks>
public sealed class SceneAnalyticsHostedService(
    IServiceScopeFactory scopeFactory,
    IOptions<SceneAnalyticsOptions> options,
    TimeProvider timeProvider,
    ILogger<SceneAnalyticsHostedService> logger) : BackgroundService
{
    private static readonly Action<ILogger, Exception?> LogDisabled =
        LoggerMessage.Define(
            LogLevel.Information,
            new EventId(1910, "SceneAnalyticsDisabled"),
            "Scene analytics is disabled; the host will not queue or execute units.");

    private static readonly Action<ILogger, int, Exception?> LogStarted =
        LoggerMessage.Define<int>(
            LogLevel.Information,
            new EventId(1911, "SceneAnalyticsStarted"),
            "Scene analytics host started; reconciling every {IntervalSeconds}s.");

    private static readonly Action<ILogger, int, Exception?> LogQueued =
        LoggerMessage.Define<int>(
            LogLevel.Information,
            new EventId(1912, "SceneAnalyticsUnitsQueued"),
            "Scene analytics queued {QueuedCount} unit(s).");

    private static readonly Action<ILogger, int, Exception?> LogExhausted =
        LoggerMessage.Define<int>(
            LogLevel.Warning,
            new EventId(1913, "SceneAnalyticsUnitsExhausted"),
            "Scene analytics terminated {ExhaustedCount} abandoned unit(s).");

    private static readonly Action<ILogger, Exception?> LogCycleFailed =
        LoggerMessage.Define(
            LogLevel.Error,
            new EventId(1914, "SceneAnalyticsCycleFailed"),
            "A scene analytics cycle failed; the host continues with the next one.");

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var configured = options.Value;
        if (!configured.Enabled)
        {
            LogDisabled(logger, null);
            return;
        }

        LogStarted(logger, configured.ReconcileIntervalSeconds, null);
        using var timer = new PeriodicTimer(
            TimeSpan.FromSeconds(configured.ReconcileIntervalSeconds),
            timeProvider);

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

    /// <summary>
    /// One pass: queue what is due, terminate what was abandoned, then execute what can
    /// be claimed.
    /// </summary>
    /// <remarks>
    /// Public so that a test can drive exactly one cycle deliberately. A background loop
    /// that can only be observed by waiting is a background loop that ends up tested by
    /// sleeping — which fails on a slow machine and passes for the wrong reason on a fast
    /// one. The seam costs one public method and buys a deterministic test.
    /// </remarks>
    public async Task RunCycleAsync(SceneAnalyticsOptions configured, CancellationToken cancellationToken)
    {
        var policy = configured.ToLeasePolicy();

        await using (var scope = scopeFactory.CreateAsyncScope())
        {
            var lifecycle = scope.ServiceProvider.GetRequiredService<ISceneAnalysisLifecycle>();

            var queued = await lifecycle.QueueEligibleUnitsAsync(
                SceneAnalyticsAlgorithm.Version,
                SceneAnalyticsParameters.Default.ParametersSha256(),
                sourceCommit: null,
                timeProvider.GetUtcNow().AddDays(-configured.ReconcileLookbackDays),
                configured.ReconcileBatchSize,
                cancellationToken);
            if (queued > 0)
            {
                LogQueued(logger, queued, null);
            }

            var exhausted = await lifecycle.ExhaustAbandonedUnitsAsync(policy, cancellationToken);
            if (exhausted > 0)
            {
                LogExhausted(logger, exhausted, null);
            }
        }

        for (var executed = 0; executed < configured.MaxConcurrentUnits; executed++)
        {
            // A scope per unit: the claim, the computation and the commit each want a
            // clean context, and the claim has already committed before the engine runs.
            await using var scope = scopeFactory.CreateAsyncScope();
            var lifecycle = scope.ServiceProvider.GetRequiredService<ISceneAnalysisLifecycle>();
            var claim = await lifecycle.ClaimNextAsync(policy, cancellationToken);
            if (claim is null)
            {
                return;
            }

            var executor = scope.ServiceProvider.GetRequiredService<SceneAnalysisExecutor>();
            await executor.ExecuteAsync(claim, configured, cancellationToken);
        }
    }
}
