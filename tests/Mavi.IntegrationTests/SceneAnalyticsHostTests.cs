using Mavi.Api.SceneAnalytics;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Infrastructure;
using Mavi.Domain.SceneAnalytics;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

/// <summary>
/// The analytics host: its configuration contract, and one cycle of its loop driven
/// deliberately rather than waited for.
/// </summary>
/// <remarks>
/// <para>
/// The cycle is invoked directly instead of letting the background loop tick, because a
/// test that sleeps until a loop has probably run is a test that fails on a slow machine
/// and passes for the wrong reason on a fast one.
/// </para>
/// <para>
/// The loop is also never started. It queues and analyses on its own schedule, against
/// the same database every test in this collection shares, so a host left running in one
/// test reaches into the next one — which is how the first draft of these tests failed.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsHostTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    /// <summary>
    /// One pass queues the eligible run, claims it, executes it and commits its facts —
    /// the whole stage, wired as the application wires it.
    /// </summary>
    [Fact]
    public async Task OneCycleCarriesAnEligibleRunAllTheWayToFacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        await using var factory = CreateFactory(world);

        await RunOneCycleAsync(factory, world);

        await using var reader = world.Read();
        var unit = await reader.SceneAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(SceneAnalysisStatus.Completed, unit.Status);
        Assert.Equal(1, unit.AnalysedTrackCount);
        Assert.NotNull(unit.VisibilitySequence);
        Assert.Single(await reader.TrackAnalysisOutcomes.ToListAsync());
        Assert.NotEmpty(await reader.TrackZoneVisits.ToListAsync());
    }

    /// <summary>A second pass over a finished run must do nothing at all.</summary>
    [Fact]
    public async Task ASecondCycleIsAVisibleNoOp()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        await using var factory = CreateFactory(world);

        await RunOneCycleAsync(factory, world);
        var first = await world.Read().SceneAnalyses.AsNoTracking().SingleAsync();

        await RunOneCycleAsync(factory, world);

        await using var reader = world.Read();
        var unit = await reader.SceneAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(first.VisibilitySequence, unit.VisibilitySequence);
        Assert.Equal(first.CompletedAtUtc, unit.CompletedAtUtc);
        Assert.Equal(first.AttemptCount, unit.AttemptCount);
        Assert.Single(await reader.TrackAnalysisOutcomes.ToListAsync());
    }

    /// <summary>
    /// A camera whose active revision enables nothing is never queued, so the host has
    /// nothing to do — the disable switch reaches all the way through the stage.
    /// </summary>
    [Fact]
    public async Task ADisabledCameraGivesTheHostNothingToDo()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, analyticsEnabled: false);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        await using var factory = CreateFactory(world);

        await RunOneCycleAsync(factory, world);

        Assert.Empty(await world.Read().SceneAnalyses.ToListAsync());
        Assert.Empty(await world.Read().TrackAnalysisOutcomes.ToListAsync());
    }

    /// <summary>
    /// The host terminates a unit whose last attempt walked away, and the reclaim grace
    /// is honoured: it is not terminated a moment earlier.
    /// </summary>
    [Fact]
    public async Task TheHostTerminatesAbandonedUnitsOnlyAfterTheGrace()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (_, lifecycle, db) = world.Executor();
        await using var _db = db;
        await using var factory = CreateFactory(world);
        var options = factory.Services.GetRequiredService<IOptions<SceneAnalyticsOptions>>().Value;

        await lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion, SceneAnalyticsWorld.ParametersSha256,
            null, Now.AddDays(-1), 50, default);
        for (var attempt = 0; attempt < options.MaximumAttempts; attempt++)
        {
            await lifecycle.ClaimNextAsync(options.ToLeasePolicy(), default);
            world.Clock.Advance(TimeSpan.FromSeconds(options.LeaseSeconds + options.ReclaimGraceSeconds + 1));
        }

        var unitId = (await world.Read().SceneAnalyses.AsNoTracking().SingleAsync()).Id;

        // Past the lease, inside the grace: still the attempt's unit.
        world.Clock.Advance(TimeSpan.FromSeconds(-options.ReclaimGraceSeconds));
        await RunCycleAsync(factory, world);
        Assert.Equal(SceneAnalysisStatus.Running, (await world.UnitAsync(unitId)).Status);

        world.Clock.Advance(TimeSpan.FromSeconds(options.ReclaimGraceSeconds + 1));
        await RunCycleAsync(factory, world);

        var terminated = await world.UnitAsync(unitId);
        Assert.Equal(SceneAnalysisStatus.Failed, terminated.Status);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptsExhausted, terminated.FailureCode);
        Assert.Null(terminated.ClaimTokenHash);
    }

    // --- Configuration contract --------------------------------------------

    /// <summary>
    /// There is no heartbeat in v1, so a lease that does not comfortably exceed the
    /// execution bound would let attempts be reclaimed while still succeeding. That is
    /// refused at start-up rather than discovered under load.
    /// </summary>
    [Theory]
    [InlineData(100, 100)]
    [InlineData(199, 100)]
    public void AConfigurationWhoseLeaseCannotOutlastAUnitIsRefused(int leaseSeconds, int maxUnitSeconds)
    {
        var exception = Assert.Throws<OptionsValidationException>(() =>
            Validate(new Dictionary<string, string?>
            {
                ["SceneAnalytics:LeaseSeconds"] = leaseSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture),
                ["SceneAnalytics:MaxUnitDurationSeconds"] = maxUnitSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture),
            }));

        Assert.Contains("at least twice MaxUnitDurationSeconds", string.Join(" ", exception.Failures), StringComparison.Ordinal);
    }

    [Fact]
    public void AConfigurationWhoseLeaseOutlastsAUnitIsAccepted() =>
        Validate(new Dictionary<string, string?>
        {
            ["SceneAnalytics:LeaseSeconds"] = "200",
            ["SceneAnalytics:MaxUnitDurationSeconds"] = "100",
        });

    [Theory]
    [InlineData("SceneAnalytics:MaximumAttempts", "0")]
    [InlineData("SceneAnalytics:MaxConcurrentUnits", "0")]
    [InlineData("SceneAnalytics:ReconcileIntervalSeconds", "0")]
    [InlineData("SceneAnalytics:ReconcileBatchSize", "0")]
    [InlineData("SceneAnalytics:ReconcileLookbackDays", "-1")]
    public void EachBoundedSettingIsRefusedOutsideItsRange(string key, string value) =>
        Assert.Throws<OptionsValidationException>(() =>
            Validate(new Dictionary<string, string?> { [key] = value }));

    /// <summary>
    /// The shipped defaults must themselves satisfy the contract; a default that could
    /// not start is a trap for the first operator who leaves configuration alone.
    /// </summary>
    [Fact]
    public void TheShippedDefaultsAreValid()
    {
        var defaults = new SceneAnalyticsOptions();

        Assert.True(defaults.LeaseSeconds >= 2 * defaults.MaxUnitDurationSeconds);
        Assert.True(defaults.MaxConcurrentUnits >= 1);
        Validate([]);
    }

    /// <summary>
    /// Turning the host off must actually stop it, not merely make it idle: the service
    /// is registered, started, and returns without doing anything.
    /// </summary>
    [Fact]
    public async Task ADisabledHostNeverRunsACycle()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        await using var factory = CreateFactory(world);

        var host = factory.Services.GetServices<IHostedService>().OfType<SceneAnalyticsHostedService>().Single();
        await host.StartAsync(default);
        await host.ExecuteTask!;
        await host.StopAsync(default);

        Assert.Empty(await world.Read().SceneAnalyses.ToListAsync());
    }

    // --- Helpers -----------------------------------------------------------

    private static ApiTestFactory CreateFactory(SceneAnalyticsWorld world) => new()
    {
        Clock = world.Clock,
        // Never on: these tests drive cycles themselves, and a live loop would mutate the
        // shared database on its own schedule.
        EnableSceneAnalyticsHost = false,
        MediaRootOverride = world.MediaRoot,
        EvidenceRootOverride = world.EvidenceRoot,
    };

    private static Task RunOneCycleAsync(ApiTestFactory factory, SceneAnalyticsWorld world) =>
        RunCycleAsync(factory, world);

    private static async Task RunCycleAsync(ApiTestFactory factory, SceneAnalyticsWorld world)
    {
        // Touch the client so the host is built exactly as the application builds it.
        using var client = factory.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });
        var host = new SceneAnalyticsHostedService(
            factory.Services.GetRequiredService<IServiceScopeFactory>(),
            factory.Services.GetRequiredService<IOptions<SceneAnalyticsOptions>>(),
            world.Clock,
            NullLogger<SceneAnalyticsHostedService>.Instance);
        await host.RunCycleAsync(factory.Services.GetRequiredService<IOptions<SceneAnalyticsOptions>>().Value, default);
    }

    /// <summary>Builds the application's options exactly as start-up validation would.</summary>
    private static SceneAnalyticsOptions Validate(Dictionary<string, string?> overrides)
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(overrides)
            .Build();
        var services = new ServiceCollection();
        services.AddSingleton<IConfiguration>(configuration);
        services.AddSceneAnalyticsOptions(configuration);
        using var provider = services.BuildServiceProvider();
        return provider.GetRequiredService<IOptions<SceneAnalyticsOptions>>().Value;
    }
}
