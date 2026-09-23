using Mavi.Api.Storage;
using Mavi.Application.Abstractions.Storage;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

/// <summary>Janitor scheduling with a manual timer: no database, no real clock.</summary>
public sealed class StagingJanitorHostedServiceTests
{
    [Fact]
    public async Task EnabledHostRunsAtStartThenOnEveryTickAndSurvivesAFailedCycle()
    {
        using var janitor = new CountingJanitor { FailOnCycle = 2 };
        using var clock = new ManualTimerProvider();
        using var host = CreateHost(janitor, clock, enabled: true);

        await host.StartAsync(CancellationToken.None);
        await janitor.WaitForCyclesAsync(1);
        Assert.Equal(TimeSpan.FromMinutes(15), clock.Period);

        clock.Tick();
        await janitor.WaitForCyclesAsync(2); // this one throws; the host must keep going
        clock.Tick();
        await janitor.WaitForCyclesAsync(3);

        await host.StopAsync(CancellationToken.None);
        Assert.Equal(3, janitor.Cycles);
    }

    [Fact]
    public async Task DisabledHostNeverRunsACycle()
    {
        using var janitor = new CountingJanitor();
        using var clock = new ManualTimerProvider();
        using var host = CreateHost(janitor, clock, enabled: false);

        await host.StartAsync(CancellationToken.None);
        await host.ExecuteTask!;
        await host.StopAsync(CancellationToken.None);

        Assert.Equal(0, janitor.Cycles);
        Assert.Null(clock.Period);
    }

    private static StagingJanitorHostedService CreateHost(CountingJanitor janitor, ManualTimerProvider clock, bool enabled)
    {
        var services = new ServiceCollection();
        services.AddScoped<IStagingJanitor>(_ => janitor);
        var provider = services.BuildServiceProvider();
        return new StagingJanitorHostedService(
            provider.GetRequiredService<IServiceScopeFactory>(),
            Options.Create(new StagingJanitorOptions { Enabled = enabled }),
            clock,
            NullLogger<StagingJanitorHostedService>.Instance);
    }

    private sealed class CountingJanitor : IStagingJanitor, IDisposable
    {
        private int _cycles;
        private readonly SemaphoreSlim _signal = new(0);

        public int FailOnCycle { get; init; } = -1;
        public int Cycles => Volatile.Read(ref _cycles);

        public Task<StagingJanitorCycleResult> RunCycleAsync(CancellationToken cancellationToken)
        {
            var cycle = Interlocked.Increment(ref _cycles);
            _signal.Release();
            if (cycle == FailOnCycle)
                throw new IOException("Injected cycle failure.");
            return Task.FromResult(new StagingJanitorCycleResult(0, 0, 0, 0, 0, 0, 0, null, 0, 0, "normal"));
        }

        public void Dispose() => _signal.Dispose();

        public async Task WaitForCyclesAsync(int count)
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            while (Cycles < count)
                await _signal.WaitAsync(timeout.Token);
        }
    }

    /// <summary>A TimeProvider whose single periodic timer fires only when told to.</summary>
    private sealed class ManualTimerProvider : TimeProvider, IDisposable
    {
        private ManualTimer? _timer;

        public TimeSpan? Period => _timer?.Period;

        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        {
            _timer = new ManualTimer(callback, state, period);
            return _timer;
        }

        public void Tick() => _timer!.Fire();

        public void Dispose() => _timer?.Dispose();

        private sealed class ManualTimer(TimerCallback callback, object? state, TimeSpan period) : ITimer
        {
            public TimeSpan Period { get; private set; } = period;

            public void Fire() => callback(state);

            public bool Change(TimeSpan dueTime, TimeSpan period)
            {
                Period = period;
                return true;
            }

            public void Dispose()
            {
            }

            public ValueTask DisposeAsync() => ValueTask.CompletedTask;
        }
    }
}
