using Mavi.Application.Modules.Intelligence;
using Mavi.Infrastructure.Finalization;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Finalization;

/// <summary>
/// The platform finalizer host (F3 plan §6.8): it reconciles abandoned Finalizing jobs,
/// refreshes the health counts, cleans terminal payload rows, and executes the jobs it can
/// claim, within a bounded concurrency, in the API process.
/// </summary>
/// <remarks>
/// <para>
/// Scheduling only. What a transition means and every lock and fence it takes belongs to the
/// lifecycle; what to do with a claim belongs to the executor. This service decides <i>when</i>.
/// </para>
/// <para>
/// With <c>VisionFinalization:Enabled = false</c> it claims, reconciles, publishes and cleans
/// nothing; it only refreshes the read-only counts so that a stranded Finalizing row stays
/// visible in health (F3 plan §13.3). Nothing it holds in memory matters across a restart:
/// the first cycle after start reclaims expired claims and exhausts abandoned jobs.
/// </para>
/// </remarks>
public sealed partial class VisionFinalizationHostedService(
    IServiceScopeFactory scopeFactory,
    IOptions<VisionFinalizationOptions> options,
    VisionFinalizationExecutor executor,
    VisionFinalizationState state,
    TimeProvider timeProvider,
    ILogger<VisionFinalizationHostedService> logger) : BackgroundService
{
    private const int ReconcileBatchSize = 50;
    private const int PayloadCleanupBatchSize = 100;

    private SemaphoreSlim? _slots;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var configured = options.Value;
        using var timer = new PeriodicTimer(configured.PollInterval, timeProvider);

        if (!configured.Enabled)
        {
            LogDisabled(logger);
            do
            {
                await GuardedAsync(() => RefreshCountsAsync(stoppingToken), stoppingToken);
            }
            while (await timer.WaitForNextTickAsync(stoppingToken));
            return;
        }

        LogStarted(logger, configured.PollIntervalSeconds, configured.ClaimSeconds, configured.ClaimExtensionSeconds,
            configured.MaximumFinalizationAttempts, configured.MaximumFinalizationDurationSeconds, configured.MaxConcurrentFinalizations);
        do
        {
            await GuardedAsync(() => RunCycleAsync(stoppingToken), stoppingToken);
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }

    /// <summary>
    /// One pass: reconcile, refresh counts, clean payloads, then execute up to the concurrency
    /// bound. Public so a test drives exactly one cycle deliberately instead of waiting.
    /// </summary>
    public async Task RunCycleAsync(CancellationToken cancellationToken)
    {
        var configured = options.Value;
        var policy = configured.ToPolicy();
        _slots ??= new SemaphoreSlim(configured.MaxConcurrentFinalizations, configured.MaxConcurrentFinalizations);

        int exhausted, cleaned;
        await using (var scope = scopeFactory.CreateAsyncScope())
        {
            var lifecycle = scope.ServiceProvider.GetRequiredService<IVisionFinalizationLifecycle>();

            var reconciliation = await lifecycle.ExhaustAbandonedAsync(policy, ReconcileBatchSize, cancellationToken);
            exhausted = reconciliation.Exhausted;
            if (exhausted > 0)
                LogExhausted(logger, exhausted);
            foreach (var jobId in reconciliation.MalformedJobIds)
            {
                if (state.FirstReport(jobId))
                    LogMalformed(logger, jobId);
            }

            foreach (var jobId in reconciliation.InvariantJobIds)
            {
                if (state.FirstReport(jobId))
                    LogInvariant(logger, jobId);
            }

            state.RecordCounts(await lifecycle.CountAsync(cancellationToken), timeProvider.GetUtcNow());

            cleaned = await lifecycle.CleanUpPayloadsAsync(
                PayloadCleanupBatchSize, TimeSpan.FromSeconds(configured.PayloadCleanupGraceSeconds), cancellationToken);
            if (cleaned > 0)
                LogPayloadsCleaned(logger, cleaned);
        }

        // Up to the bound, concurrently; a slot taken by a long finalization in an earlier
        // cycle stays taken, so the bound holds across cycles, not just within one.
        var executions = new List<Task>();
        var claimed = 0;
        for (var slot = 0; slot < configured.MaxConcurrentFinalizations; slot++)
        {
            if (!await _slots.WaitAsync(0, cancellationToken))
                break;

            VisionFinalizationClaim? claim;
            try
            {
                await using var scope = scopeFactory.CreateAsyncScope();
                claim = await scope.ServiceProvider.GetRequiredService<IVisionFinalizationLifecycle>().ClaimNextAsync(policy, cancellationToken);
            }
            catch
            {
                _slots.Release();
                throw;
            }

            if (claim is null)
            {
                _slots.Release();
                break;
            }

            claimed++;
            LogClaimed(logger, claim.JobId, claim.AttemptCount, claim.FinalizationAttemptCount, claim.ClaimExpiresAtUtc);
            executions.Add(ExecuteAsync(claim, policy, cancellationToken));
        }

        state.RecordCycle(timeProvider.GetUtcNow(), claimed, exhausted, cleaned);
        await Task.WhenAll(executions);
    }

    /// <summary>The read-only refresh a disabled host performs; public for the same reason.</summary>
    public async Task RefreshCountsAsync(CancellationToken cancellationToken)
    {
        await using var scope = scopeFactory.CreateAsyncScope();
        var counts = await scope.ServiceProvider.GetRequiredService<IVisionFinalizationLifecycle>().CountAsync(cancellationToken);
        state.RecordCounts(counts, timeProvider.GetUtcNow());
    }

    private async Task ExecuteAsync(VisionFinalizationClaim claim, VisionFinalizationPolicy policy, CancellationToken cancellationToken)
    {
        state.BeginExecution();
        try
        {
            await executor.ExecuteAsync(claim, policy, cancellationToken);
        }
        finally
        {
            state.EndExecution();
            _slots!.Release();
        }
    }

    private async Task GuardedAsync(Func<Task> cycle, CancellationToken stoppingToken)
    {
        try
        {
            await cycle();
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            throw;
        }
#pragma warning disable CA1031 // One bad cycle must not take the host down with it.
        catch (Exception exception)
#pragma warning restore CA1031
        {
            LogCycleFailed(logger, exception.GetType().Name);
        }
    }

    public override void Dispose()
    {
        _slots?.Dispose();
        base.Dispose();
    }

    [LoggerMessage(EventId = 1500, EventName = "vision_finalization_disabled", Level = LogLevel.Information,
        Message = "Asynchronous finalization is disabled; the host only refreshes the Finalizing counts for health.")]
    private static partial void LogDisabled(ILogger logger);

    [LoggerMessage(EventId = 1501, EventName = "vision_finalization_started", Level = LogLevel.Information,
        Message = "Finalizer started: poll {PollSeconds}s, claim {ClaimSeconds}s, extension {ExtensionSeconds}s, {MaximumAttempts} attempts, deadline {MaximumDurationSeconds}s after hand-off, concurrency {Concurrency}.")]
    private static partial void LogStarted(ILogger logger, int pollSeconds, int claimSeconds, int extensionSeconds, int maximumAttempts, int maximumDurationSeconds, int concurrency);

    [LoggerMessage(EventId = 1502, EventName = "vision_finalization_claimed", Level = LogLevel.Information,
        Message = "Finalizer claimed job {JobId} (worker attempt {AttemptCount}, claim {FinalizationAttempt}); claim expires {ExpiresAtUtc}.")]
    private static partial void LogClaimed(ILogger logger, Guid jobId, int attemptCount, int finalizationAttempt, DateTimeOffset expiresAtUtc);

    [LoggerMessage(EventId = 1508, EventName = "vision_finalization_exhausted", Level = LogLevel.Error,
        Message = "Finalizer reconciliation exhausted {Count} abandoned Finalizing job(s): no live claim remained and no further claim was permitted.")]
    private static partial void LogExhausted(ILogger logger, int count);

    [LoggerMessage(EventId = 1510, EventName = "vision_finalization_payloads_cleaned", Level = LogLevel.Information,
        Message = "Finalizer deleted {Count} retained payload row(s) of terminal jobs.")]
    private static partial void LogPayloadsCleaned(ILogger logger, int count);

    [LoggerMessage(EventId = 1511, EventName = "vision_finalization_cycle_failed", Level = LogLevel.Error,
        Message = "A finalizer cycle failed ({ExceptionType}); the host continues with the next one.")]
    private static partial void LogCycleFailed(ILogger logger, string exceptionType);

    [LoggerMessage(EventId = 1512, EventName = "vision_finalization_malformed_claim", Level = LogLevel.Error,
        Message = "Finalizing job {JobId} has malformed claim metadata; it is never claimed, exhausted or modified and needs an operator.")]
    private static partial void LogMalformed(ILogger logger, Guid jobId);

    [LoggerMessage(EventId = 1512, EventName = "vision_finalization_invariant", Level = LogLevel.Error,
        Message = "Finalizing job {JobId} could not be exhausted because its run or video refused the failed transition; it is left untouched for an operator.")]
    private static partial void LogInvariant(ILogger logger, Guid jobId);
}
