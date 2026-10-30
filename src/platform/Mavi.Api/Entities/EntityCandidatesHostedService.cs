using Mavi.Application.Modules.Entities;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Entities;

/// <summary>Configuration of the Entity-candidate derivation sweep (ADR-023 §2).</summary>
public sealed class EntityCandidatesOptions
{
    public const string SectionName = "EntityCandidates";

    public bool Enabled { get; set; } = true;

    public int IntervalSeconds { get; set; } = 10;

    public int BatchSize { get; set; } = 20;
}

/// <summary>
/// Derives Entity candidates for completed embedding analyses that have none at the current catalogue version.
/// Bounded and sequential, like the analytic-events host it follows; it writes candidates only, never an Entity or
/// <c>Track.EntityId</c>.
/// </summary>
public sealed class EntityCandidatesHostedService(
    IServiceScopeFactory scopeFactory,
    IOptions<EntityCandidatesOptions> options,
    TimeProvider timeProvider,
    ILogger<EntityCandidatesHostedService> logger) : BackgroundService
{
    private static readonly Action<ILogger, string, Exception?> LogStarted =
        LoggerMessage.Define<string>(
            LogLevel.Information,
            new EventId(1970, "EntityCandidatesStarted"),
            "Entity candidate host started for catalogue {CatalogueVersion}.");

    private static readonly Action<ILogger, int, Exception?> LogDerived =
        LoggerMessage.Define<int>(
            LogLevel.Information,
            new EventId(1971, "EntityCandidatesDerived"),
            "Entity candidates derived for {AnalysisCount} embedding analysis(es).");

    private static readonly Action<ILogger, Exception?> LogCycleFailed =
        LoggerMessage.Define(
            LogLevel.Error,
            new EventId(1972, "EntityCandidatesCycleFailed"),
            "An Entity candidate cycle failed; the host continues with the next one.");

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var configured = options.Value;
        if (!configured.Enabled)
            return;

        LogStarted(logger, EntityCandidateCatalogue.Current.CatalogueVersion, null);
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
    public async Task<int> RunCycleAsync(EntityCandidatesOptions configured, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(configured);
        await using var scope = scopeFactory.CreateAsyncScope();
        var service = scope.ServiceProvider.GetRequiredService<EntityCandidateService>();
        var derived = await service.DeriveDueAsync(Math.Max(1, configured.BatchSize), cancellationToken);
        if (derived > 0)
            LogDerived(logger, derived, null);
        return derived;
    }
}
