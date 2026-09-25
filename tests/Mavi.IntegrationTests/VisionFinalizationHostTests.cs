using System.Text.Json;
using Mavi.Api.Finalization;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Finalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

namespace Mavi.IntegrationTests;

/// <summary>
/// The finalizer host and its health (F3 plan §6.8, §6.9, §13.3; slice 7): recovery at start,
/// the concurrency bound, shutdown, the disabled read-only loop, registration and the
/// PostgreSQL-derived counts the rollback procedure relies on.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationHostTests
{
    [Fact]
    public async Task OneCycleReconcilesCountsCleansAndPublishes()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        world.Clock.Advance(TimeSpan.FromSeconds(2));

        await world.Host().RunCycleAsync(CancellationToken.None);

        var (job, run, _) = await world.StateAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(1, await world.TrackCountAsync(run.Id));
        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1502);
        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1504);
        var health = world.Factory.Services.GetRequiredService<IVisionFinalizationMonitor>().Current;
        Assert.True(health.Enabled);
        Assert.Equal(1, health.LastCycleClaimed);
        Assert.Equal(0, health.InFlight);
        Assert.Equal(world.Clock.GetUtcNow(), health.LastCycleUtc);
        // Counted before this cycle's claim: the row was Finalizing and unclaimed.
        Assert.Equal(1, health.FinalizingJobs);
        Assert.Equal(0, health.LiveClaims);

        // The next cycle counts zero and cleans the payload row.
        await world.Host().RunCycleAsync(CancellationToken.None);
        var after = world.Factory.Services.GetRequiredService<IVisionFinalizationMonitor>().Current;
        Assert.Equal(0, after.FinalizingJobs);
        Assert.Equal(1, after.LastCyclePayloadsCleaned);
        Assert.Equal(0, await world.PayloadCountAsync());
        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1510);
    }

    [Fact]
    public async Task HostRecoversFinalizingRowsOnStartup()
    {
        // Host A hands off, claims, and dies mid-way (its claim is left to expire).
        using var first = await FinalizationWorld.CreateAsync();
        var handOff = await first.HandOffAsync();
        var abandoned = (await first.ClaimAsync())!;
        first.Clock.Advance(TimeSpan.FromMinutes(6));

        // Host B starts over the same database and roots with the loop on: its immediate
        // first cycle reclaims and finalizes with nothing but PostgreSQL to go on.
        using var second = await FinalizationWorld.CreateAsync(
            sharedWith: first,
            enableHost: true,
            options: new VisionFinalizationOptions { Enabled = true, PollIntervalSeconds = 300 });
        _ = second.Factory.CreateClient();
        await FinalizationWorld.WaitUntilAsync(async () => (await second.JobAsync(handOff.Lease.JobId)).Status == VisionJobStatus.Completed);

        var (job, run, _) = await second.StateAsync(handOff.Lease.JobId);
        Assert.Equal(2, job.FinalizationAttemptCount);
        Assert.Equal(1, await second.TrackCountAsync(run.Id));
        Assert.False(job.FinalizationOwnedBy(abandoned.ClaimToken.Span, second.Clock.GetUtcNow()));
        Assert.Contains(second.Logs.Entries, x => x.EventId.Id == 1501);
    }

    [Fact]
    public async Task HostBoundsConcurrencyAcrossCycles()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var jobs = new List<Guid>();
        for (var index = 0; index < 3; index++)
        {
            jobs.Add((await world.HandOffAsync(cameraCode: $"CAM-{index}")).Lease.JobId);
            world.Clock.Advance(TimeSpan.FromSeconds(1));
        }

        using var gate = new SemaphoreSlim(0);
        using var entered = new SemaphoreSlim(0);
        world.Sealer.BeforeSeal = async call =>
        {
            if (call == 1)
            {
                entered.Release();
                await gate.WaitAsync();
            }
        };

        var host = world.Host();
        var firstCycle = host.RunCycleAsync(CancellationToken.None);
        Assert.True(await entered.WaitAsync(TimeSpan.FromSeconds(30)), "the first execution began");
        var state = world.Factory.Services.GetRequiredService<IVisionFinalizationMonitor>().Current;
        Assert.Equal(1, state.InFlight);
        Assert.Equal(1, state.LastCycleClaimed);

        // A second cycle while the slot is taken claims nothing: the bound holds across cycles.
        await host.RunCycleAsync(CancellationToken.None);
        Assert.Equal(0, world.Factory.Services.GetRequiredService<IVisionFinalizationMonitor>().Current.LastCycleClaimed);
        Assert.Equal(1, (await world.WithLifecycleAsync(l => l.CountAsync(CancellationToken.None))).LiveClaims);

        gate.Release();
        await firstCycle;
        Assert.Equal(0, world.Factory.Services.GetRequiredService<IVisionFinalizationMonitor>().Current.InFlight);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(jobs[0])).Status);
        Assert.Equal(VisionJobStatus.Finalizing, (await world.JobAsync(jobs[1])).Status);

        await host.RunCycleAsync(CancellationToken.None);
        await host.RunCycleAsync(CancellationToken.None);
        Assert.All(jobs, async id => Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(id)).Status));
    }

    [Fact]
    public async Task HostShutdownDoesNotFailTheJob()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        using var stopping = new CancellationTokenSource();
        world.Sealer.BeforeSeal = call =>
        {
            if (call == 2)
                stopping.Cancel();
            return Task.CompletedTask;
        };

        await world.Host().RunCycleAsync(stopping.Token);

        var job = await world.JobAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Null(job.FailureCode);
        Assert.Null(job.FinalizationLastErrorCode);
        Assert.Equal(FinalizationClaimState.Live, job.FinalizationClaimStateAt(world.Clock.GetUtcNow()));
        Assert.Equal(0, await world.TrackCountAsync(handOff.Lease.ProcessingRunId));
        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1514);
        Assert.Equal(0, world.Factory.Services.GetRequiredService<IVisionFinalizationMonitor>().Current.InFlight);
    }

    [Fact]
    public async Task DisabledHostRefreshesCountsButWritesNothing()
    {
        using var enabled = await FinalizationWorld.CreateAsync();
        var handOff = await enabled.HandOffAsync();
        enabled.Clock.Advance(TimeSpan.FromHours(7)); // past the deadline: an enabled host would exhaust this

        using var disabled = await FinalizationWorld.CreateAsync(
            sharedWith: enabled,
            enableHost: true,
            options: new VisionFinalizationOptions { Enabled = false, PollIntervalSeconds = 300 });
        _ = disabled.Factory.CreateClient();
        await FinalizationWorld.WaitUntilAsync(() =>
            Task.FromResult(disabled.Factory.Services.GetRequiredService<IVisionFinalizationMonitor>().Current.CountsRefreshedAtUtc is not null));

        var health = await disabled.HealthAsync();
        Assert.False(health.GetProperty("enabled").GetBoolean());
        Assert.Equal(1, health.GetProperty("finalizingJobs").GetInt32());
        Assert.Equal(0, health.GetProperty("liveClaims").GetInt32());
        Assert.Equal(0, health.GetProperty("malformedClaims").GetInt32());
        Assert.Equal(handOff.Ack.AcceptedAtUtc, health.GetProperty("oldestFinalizingAcceptedAtUtc").GetDateTimeOffset());
        Assert.Equal(disabled.Clock.GetUtcNow(), health.GetProperty("countsRefreshedAtUtc").GetDateTimeOffset());
        Assert.Equal(JsonValueKind.Null, health.GetProperty("lastCycleUtc").ValueKind);

        var job = await disabled.JobAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal(0, job.FinalizationAttemptCount);
        Assert.Equal(1, await disabled.PayloadCountAsync());
        Assert.Equal(0, disabled.Sealer.Seals);
        Assert.Single(disabled.Logs.Entries, x => x.EventId.Id == 1500);
        Assert.DoesNotContain(disabled.Logs.Entries, x => x.EventId.Id is 1501 or 1502 or 1508 or 1510);
        Assert.DoesNotContain(disabled.Sql.Commands, x => x.Contains("FOR UPDATE", StringComparison.Ordinal));
        Assert.DoesNotContain(disabled.Sql.Commands, x => x.Contains("UPDATE vision_jobs", StringComparison.Ordinal));
        Assert.DoesNotContain(disabled.Sql.Commands, x => x.Contains("DELETE FROM", StringComparison.Ordinal));
    }

    [Fact]
    public async Task HostedServiceIsRegisteredWhenEnabledAndHealthExposesEveryField()
    {
        using var world = await FinalizationWorld.CreateAsync(enableHost: true, options: new VisionFinalizationOptions { Enabled = true, PollIntervalSeconds = 300 });
        _ = world.Factory.CreateClient();

        Assert.Contains(world.Factory.Services.GetServices<IHostedService>(), x => x is VisionFinalizationHostedService);
        // The registered loop's first cycle raced the test database reset (the application
        // migrates before its hosts start); refresh once by hand for a deterministic snapshot.
        await world.Host().RefreshCountsAsync(CancellationToken.None);

        var health = await world.HealthAsync();
        foreach (var field in new[] { "enabled", "finalizingJobs", "liveClaims", "malformedClaims", "oldestFinalizingAcceptedAtUtc", "countsRefreshedAtUtc", "inFlight", "lastCycleUtc", "lastCycleClaimed", "lastCycleExhausted", "lastCyclePayloadsCleaned" })
            Assert.True(health.TryGetProperty(field, out _), field);
        Assert.True(health.GetProperty("enabled").GetBoolean());
        Assert.Equal(0, health.GetProperty("finalizingJobs").GetInt32());
    }

    [Fact]
    public async Task HostIsAbsentWhenTheTestFactoryKeepsItOff()
    {
        using var world = await FinalizationWorld.CreateAsync();
        _ = world.Factory.CreateClient();
        Assert.DoesNotContain(world.Factory.Services.GetServices<IHostedService>(), x => x is VisionFinalizationHostedService);
    }

    // -- the counts the rollback procedure relies on (F3 plan §13.3) -----------------------

    [Fact]
    public async Task FinalizingJobsCountIncreasesAfterHandOffAndReturnsToZeroAfterPublishFailAndExhaust()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var host = world.Host();
        await host.RunCycleAsync(CancellationToken.None);
        Assert.Equal(0, Monitor(world).FinalizingJobs);

        var publish = await world.HandOffAsync(cameraCode: "CAM-1");
        var fail = await world.HandOffAsync(cameraCode: "CAM-2");
        var exhaust = await world.HandOffAsync(cameraCode: "CAM-3");
        await host.RefreshCountsAsync(CancellationToken.None);
        Assert.Equal(3, Monitor(world).FinalizingJobs);
        Assert.Equal(publish.Ack.AcceptedAtUtc, Monitor(world).OldestFinalizingAcceptedAtUtc);

        // One publishes, one fails deterministically, one is exhausted by reconciliation.
        File.Delete(Path.Combine(world.StagingAttemptPath(fail.Lease), "trajectories", "person-000001.msgpack"));
        await world.ExecuteSqlAsync("UPDATE vision_jobs SET finalization_attempt_count = 3 WHERE id = $1", exhaust.Lease.JobId);
        await host.RunCycleAsync(CancellationToken.None); // exhausts CAM-3, claims and publishes CAM-1
        await host.RunCycleAsync(CancellationToken.None); // claims and fails CAM-2
        await host.RefreshCountsAsync(CancellationToken.None);

        Assert.Equal(0, Monitor(world).FinalizingJobs);
        Assert.Null(Monitor(world).OldestFinalizingAcceptedAtUtc);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(publish.Lease.JobId)).Status);
        Assert.Equal("vision_finalization_staging_missing", (await world.JobAsync(fail.Lease.JobId)).FailureCode);
        Assert.Equal("vision_finalization_exhausted", (await world.JobAsync(exhaust.Lease.JobId)).FailureCode);
        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1508);
    }

    [Fact]
    public async Task FinalizingJobsTransitionsToZeroAfterDrain()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync(cameraCode: "CAM-1");
        await world.HandOffAsync(cameraCode: "CAM-2");
        var host = world.Host();

        // Workers were switched to 3.0 first: no new hand-offs arrive. Cycles drain the rows.
        var cycles = 0;
        do
        {
            await host.RunCycleAsync(CancellationToken.None);
            await host.RefreshCountsAsync(CancellationToken.None);
            cycles++;
        }
        while (Monitor(world).FinalizingJobs > 0 && cycles < 10);

        Assert.Equal(0, Monitor(world).FinalizingJobs);
        Assert.NotNull(Monitor(world).CountsRefreshedAtUtc);
        Assert.Equal(2, cycles); // two jobs at concurrency one; the second refresh confirms zero

        // Then the gate is switched off: a disabled host over the same database still reports zero.
        using var disabled = await FinalizationWorld.CreateAsync(sharedWith: world, options: new VisionFinalizationOptions { Enabled = false });
        await disabled.Host().RefreshCountsAsync(CancellationToken.None);
        var health = await disabled.HealthAsync();
        Assert.False(health.GetProperty("enabled").GetBoolean());
        Assert.Equal(0, health.GetProperty("finalizingJobs").GetInt32());
        Assert.NotEqual(JsonValueKind.Null, health.GetProperty("countsRefreshedAtUtc").ValueKind);
    }

    [Fact]
    public async Task MalformedClaimsAreReportedOncePerHostAndCounted()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        await world.SetClaimTripleAsync(handOff.Lease.JobId, new byte[32], null, null);
        var host = world.Host();

        await host.RunCycleAsync(CancellationToken.None);
        await host.RunCycleAsync(CancellationToken.None);

        Assert.Single(world.Logs.Entries, x => x.EventId.Id == 1512);
        Assert.Equal(1, Monitor(world).MalformedClaims);
        Assert.Equal(1, Monitor(world).FinalizingJobs);
        Assert.Equal(1, (await world.HealthAsync()).GetProperty("malformedClaims").GetInt32());
        Assert.Equal(VisionJobStatus.Finalizing, (await world.JobAsync(handOff.Lease.JobId)).Status);
    }

    private static VisionFinalizationHealth Monitor(FinalizationWorld world) =>
        world.Factory.Services.GetRequiredService<IVisionFinalizationMonitor>().Current;
}
