using System.Net;
using Mavi.Application.Modules.Plates;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// Plate staging (<c>staging-plates/</c>) and its janitor, whose only authority is the plate analysis row:
/// the running attempt's bytes are never removed, a requeued attempt's are, a terminal unit's only after
/// the grace — and the attribute janitor has no authority over plate staging, nor the reverse.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlateStagingTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 13, 12, 0, 0, TimeSpan.Zero);

    private static async Task<(PlateApiHost Host, LeasedPlateUnit Unit)> HostWithLeaseAsync(PostgresFixture fixture)
    {
        var host = await PlateApiHost.CreateAsync(fixture, T0);
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        await host.World.SeedRunAsync(0, 1, 1, completedAtUtc: host.World.Clock.GetUtcNow());
        await host.RunCycleAsync();
        return (host, await host.LeaseAsync());
    }

    private static async Task<int> JanitorAsync(PlateApiHost host)
    {
        await using var scope = host.Factory.Services.CreateAsyncScope();
        return await scope.ServiceProvider.GetRequiredService<IPlateStagingJanitor>().RunCycleAsync(CancellationToken.None);
    }

    private static string AttemptDirectory(PlateApiHost host, Guid analysisId, int attempt) =>
        Path.Combine(host.World.MediaRoot, PlateStagingLayout.RootDirectoryName, analysisId.ToString("D"), PlateStagingLayout.AttemptDirectoryName(attempt));

    [Fact]
    public async Task TheJanitorNeverRemovesTheRunningAttemptsStaging()
    {
        var (host, first) = await HostWithLeaseAsync(fixture);
        await using var owned = host;
        using (var uploaded = await host.UploadAsync(first, PlateCompletionBuilder.Build(first.Lease).Predictions))
            Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);

        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        var second = await host.LeaseAsync("plates-02");
        var retry = PlateCompletionBuilder.Build(second.Lease, workerId: "plates-02");
        using (await host.UploadAsync(second, retry.Predictions)) { }

        Assert.Equal(1, await JanitorAsync(host));
        Assert.False(Directory.Exists(AttemptDirectory(host, first.AnalysisId, 1)));
        Assert.True(File.Exists(Path.Combine(AttemptDirectory(host, second.AnalysisId, 2), PlateStagingLayout.PredictionsFileName)));

        using var completed = await host.CompleteAsync(second, retry.Request);
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
    }

    [Fact]
    public async Task ARequeuedUnitsStagingIsReclaimableAndATerminalUnitsOnlyAfterGrace()
    {
        var (host, unit) = await HostWithLeaseAsync(fixture);
        await using var owned = host;
        using (await host.UploadAsync(unit, PlateCompletionBuilder.Build(unit.Lease).Predictions)) { }
        using (await host.FailAsync(unit, "plate_inference_failed", "retry")) { }
        Assert.Equal(1, await JanitorAsync(host));
        Assert.False(Directory.Exists(AttemptDirectory(host, unit.AnalysisId, 1)));

        var second = await host.LeaseAsync();
        using (await host.UploadAsync(second, PlateCompletionBuilder.Build(second.Lease).Predictions)) { }
        using (await host.FailAsync(second, "plate_output_invalid", "terminal")) { }
        Assert.Equal(0, await JanitorAsync(host));
        Assert.True(Directory.Exists(AttemptDirectory(host, second.AnalysisId, 2)));

        host.World.Clock.Advance(TimeSpan.FromMinutes(16));
        Assert.Equal(1, await JanitorAsync(host));
        Assert.False(Directory.Exists(Path.Combine(host.World.MediaRoot, PlateStagingLayout.RootDirectoryName, unit.AnalysisId.ToString("D"))));
    }

    [Fact]
    public async Task TheAttributeJanitorHasNoAuthorityOverPlateStaging()
    {
        var (host, unit) = await HostWithLeaseAsync(fixture);
        await using var owned = host;
        using (await host.UploadAsync(unit, PlateCompletionBuilder.Build(unit.Lease).Predictions)) { }
        using (await host.FailAsync(unit, "plate_inference_failed", "retry")) { }
        await using (var scope = host.Factory.Services.CreateAsyncScope())
        {
            var attributeJanitor = scope.ServiceProvider.GetRequiredService<Mavi.Application.Modules.VisualAttributes.IVisualAttributeStagingJanitor>();
            Assert.Equal(0, await attributeJanitor.RunCycleAsync(CancellationToken.None));
        }

        Assert.True(Directory.Exists(AttemptDirectory(host, unit.AnalysisId, 1)));
    }
}
