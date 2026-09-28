using System.Net;
using System.Security.Cryptography;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Mavi.Infrastructure.Storage;

namespace Mavi.IntegrationTests;

/// <summary>
/// Attribute staging (S2b plan §12): the streaming, capped, create-once store and the janitor
/// keyed on the analysis row — never on the VisionJob janitor's authority.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributeStagingTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);

    private async Task<(VisualAttributeApiHost Host, LeasedUnit Unit)> HostWithLeaseAsync()
    {
        var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        await host.World.SeedRunAsync(1, 1, 1, completedAtUtc: host.World.Clock.GetUtcNow());
        await host.RunCycleAsync();
        return (host, await host.LeaseAsync());
    }

    private static string AttemptDirectory(VisualAttributeApiHost host, Guid analysisId, int attempt) =>
        Path.Combine(host.World.MediaRoot, AttributeStagingLayout.RootDirectoryName, analysisId.ToString("D"),
            AttributeStagingLayout.AttemptDirectoryName(attempt));

    private static async Task<int> JanitorAsync(VisualAttributeApiHost host)
    {
        await using var scope = host.Factory.Services.CreateAsyncScope();
        return await scope.ServiceProvider.GetRequiredService<IVisualAttributeStagingJanitor>().RunCycleAsync(CancellationToken.None);
    }

    // --- Store ------------------------------------------------------------------------------

    [Fact]
    public async Task AShortOrLongBodyIsNeverStaged()
    {
        var (host, unit) = await HostWithLeaseAsync();
        await using var owned = host;
        var store = host.Factory.Services.GetRequiredService<IAttributeStagingStore>();
        var bytes = "{\"a\":1}\n"u8.ToArray();
        var sha = VisualAttributeApiHost.Sha256(bytes);

        var truncated = await store.WriteAsync(unit.AnalysisId, unit.Attempt, new MemoryStream(bytes), bytes.Length + 1, sha, CancellationToken.None);
        var tooLarge = await store.WriteAsync(unit.AnalysisId, unit.Attempt, new MemoryStream(bytes), bytes.Length - 1, sha, CancellationToken.None);

        Assert.Equal(AttributeUploadStatus.Truncated, truncated.Status);
        Assert.Equal(AttributeUploadStatus.TooLarge, tooLarge.Status);
        Assert.Null(store.Describe(unit.AnalysisId, unit.Attempt));
        // No temporary residue survives a refused write.
        Assert.Empty(Directory.GetFiles(AttemptDirectory(host, unit.AnalysisId, unit.Attempt)));

        var stored = await store.WriteAsync(unit.AnalysisId, unit.Attempt, new MemoryStream(bytes), bytes.Length, sha, CancellationToken.None);
        Assert.Equal(AttributeUploadStatus.Stored, stored.Status);
        Assert.Equal(bytes.Length, store.Describe(unit.AnalysisId, unit.Attempt)!.SizeBytes);
    }

    [Fact]
    public async Task ConcurrentUploadsOfTheSameBytesStageOnce()
    {
        var (host, unit) = await HostWithLeaseAsync();
        await using var owned = host;
        var bytes = RandomNumberGenerator.GetBytes(256 * 1024);

        var responses = await Task.WhenAll(Enumerable.Range(0, 6).Select(_ => host.UploadAsync(unit, bytes)));

        Assert.All(responses, response => Assert.Equal(HttpStatusCode.OK, response.StatusCode));
        var bodies = await Task.WhenAll(responses.Select(response => response.Content.ReadAsStringAsync()));
        Assert.Single(bodies, body => body.Contains("\"stored\"", StringComparison.Ordinal));
        foreach (var response in responses) response.Dispose();
        var directory = AttemptDirectory(host, unit.AnalysisId, unit.Attempt);
        Assert.Equal([AttributeStagingLayout.PredictionsFileName], Directory.GetFiles(directory).Select(Path.GetFileName));
        Assert.Equal(bytes, await File.ReadAllBytesAsync(Path.Combine(directory, AttributeStagingLayout.PredictionsFileName)));
    }

    // --- Janitor ------------------------------------------------------------------------------

    [Fact]
    public async Task TheJanitorNeverRemovesTheRunningAttemptsStaging()
    {
        var (host, first) = await HostWithLeaseAsync();
        await using var owned = host;
        var completion = AttributeCompletionBuilder.Build(first);
        using (await host.UploadAsync(first, completion.Predictions)) { }

        // Attempt 1 expires and is reclaimed as attempt 2; attempt 2 stages its own bytes.
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        var second = await host.LeaseAsync("attributes-02");
        var retry = AttributeCompletionBuilder.Build(second);
        using (await host.UploadAsync(second, retry.Predictions)) { }

        Assert.Equal(1, await JanitorAsync(host));
        Assert.False(Directory.Exists(AttemptDirectory(host, first.AnalysisId, 1)));
        Assert.True(File.Exists(Path.Combine(AttemptDirectory(host, second.AnalysisId, 2), AttributeStagingLayout.PredictionsFileName)));

        // The current attempt still publishes after the janitor ran.
        using var completed = await host.CompleteAsync(second, retry.Request);
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
    }

    [Fact]
    public async Task ARequeuedUnitsStagingIsReclaimableAndATerminalUnitsOnlyAfterGrace()
    {
        var (host, unit) = await HostWithLeaseAsync();
        await using var owned = host;
        using (await host.UploadAsync(unit, AttributeCompletionBuilder.Build(unit).Predictions)) { }
        using (await host.FailAsync(unit, "visual_attribute_inference_failed", "retry")) { }

        // Queued at attempt 1: attempt 1 can never publish again.
        Assert.Equal(1, await JanitorAsync(host));
        Assert.False(Directory.Exists(AttemptDirectory(host, unit.AnalysisId, 1)));

        var second = await host.LeaseAsync();
        using (await host.UploadAsync(second, AttributeCompletionBuilder.Build(second).Predictions)) { }
        using (await host.FailAsync(second, "visual_attribute_output_invalid", "terminal")) { }
        Assert.Equal(0, await JanitorAsync(host));
        Assert.True(Directory.Exists(AttemptDirectory(host, second.AnalysisId, 2)));

        host.World.Clock.Advance(TimeSpan.FromMinutes(16));
        Assert.Equal(1, await JanitorAsync(host));
        Assert.False(Directory.Exists(Path.Combine(host.World.MediaRoot, AttributeStagingLayout.RootDirectoryName, unit.AnalysisId.ToString("D"))));
    }

    [Fact]
    public async Task AnUnknownAnalysisDirectoryIsRemovedOnlyAfterTheUnknownGrace()
    {
        await using var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        var unknown = Path.Combine(host.World.MediaRoot, AttributeStagingLayout.RootDirectoryName, Guid.CreateVersion7().ToString("D"));
        Directory.CreateDirectory(Path.Combine(unknown, "attempt-0001"));
        Directory.SetLastWriteTimeUtc(unknown, Now.UtcDateTime.AddHours(-1));
        var foreign = Path.Combine(host.World.MediaRoot, AttributeStagingLayout.RootDirectoryName, "not-an-analysis");
        Directory.CreateDirectory(foreign);
        Directory.SetLastWriteTimeUtc(foreign, Now.UtcDateTime.AddDays(-3));

        Assert.Equal(0, await JanitorAsync(host));
        Directory.SetLastWriteTimeUtc(unknown, Now.UtcDateTime.AddHours(-25));
        Assert.Equal(1, await JanitorAsync(host));
        Assert.False(Directory.Exists(unknown));
        Assert.True(Directory.Exists(foreign));
    }

    private static string StagingRoot(VisualAttributeApiHost host) =>
        Path.Combine(host.World.MediaRoot, AttributeStagingLayout.RootDirectoryName);

    private static void CreateOrphans(VisualAttributeApiHost host, int count, TimeSpan age)
    {
        for (var index = 0; index < count; index++)
        {
            var directory = Path.Combine(StagingRoot(host), Guid.CreateVersion7().ToString("D"));
            Directory.CreateDirectory(Path.Combine(directory, "attempt-0001"));
            Directory.SetLastWriteTimeUtc(directory, (Now - age).UtcDateTime);
        }
    }

    [Fact]
    public async Task AReclaimableDirectoryListedAfterTheFirstThousandIsStillReclaimed()
    {
        await using var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        // More directories than one cycle's cap, none of them removable yet.
        CreateOrphans(host, AttributeStagingJanitor.MaximumDirectoriesPerCycle + 100, TimeSpan.FromHours(1));
        // The directory the listing yields last becomes the one removable entry.
        var listed = Directory.EnumerateDirectories(StagingRoot(host)).ToList();
        var last = listed[^1];
        Directory.SetLastWriteTimeUtc(last, Now.UtcDateTime.AddHours(-25));
        Assert.True(listed.Count > AttributeStagingJanitor.MaximumDirectoriesPerCycle);

        Assert.Equal(1, await JanitorAsync(host));
        Assert.False(Directory.Exists(last));
        Assert.Equal(listed.Count - 1, Directory.EnumerateDirectories(StagingRoot(host)).Count());
    }

    [Fact]
    public async Task TheCycleCapBoundsRemovalsAndTheNextCycleTakesTheRest()
    {
        await using var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        CreateOrphans(host, AttributeStagingJanitor.MaximumDirectoriesPerCycle + 5, TimeSpan.FromHours(25));

        Assert.Equal(AttributeStagingJanitor.MaximumDirectoriesPerCycle, await JanitorAsync(host));
        Assert.Equal(5, await JanitorAsync(host));
        Assert.Empty(Directory.EnumerateDirectories(StagingRoot(host)));
    }

    [Fact]
    public async Task TheVisionJobJanitorHasNoAuthorityOverAttributeStaging()
    {
        var (host, unit) = await HostWithLeaseAsync();
        await using var owned = host;
        using (await host.UploadAsync(unit, AttributeCompletionBuilder.Build(unit).Predictions)) { }
        using (await host.FailAsync(unit, "visual_attribute_output_invalid", "terminal")) { }
        host.World.Clock.Advance(TimeSpan.FromDays(3));
        Directory.SetLastWriteTimeUtc(Path.Combine(host.World.MediaRoot, AttributeStagingLayout.RootDirectoryName), Now.UtcDateTime.AddDays(-3));

        await using (var scope = host.Factory.Services.CreateAsyncScope())
            await scope.ServiceProvider.GetRequiredService<IStagingJanitor>().RunCycleAsync(CancellationToken.None);

        Assert.True(Directory.Exists(AttemptDirectory(host, unit.AnalysisId, 1)));
        await using var db = host.World.Read();
        Assert.Equal(VisualAttributeAnalysisStatus.Failed, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);
    }
}
