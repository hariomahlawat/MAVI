using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The processing status projection reads <c>FramesProcessed</c> and
/// <c>TracksCreated</c> from the persisted latest run. These tests prove the
/// values come from the database row of the correct run, not from a contract
/// stub, and that they stay at their default until a run has completed.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ProcessingStatusPersistenceTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 19, 6, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task GetStatusReturnsPersistedCountersOfTheLatestRunOnly()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-STATUS", Now.AddHours(-1));

        // An earlier completed run with different counters, then a later one.
        var earlier = await Task14TestData.AddCompletedTrackAsync(factory, video, Now.AddMinutes(-30), startOffsetMs: 1_000, localTrackNumber: 1);
        var latestRunId = await SeedCompletedRunWithJobAsync(factory, video.VideoId, queuedAtUtc: Now.AddMinutes(-5), framesProcessed: 1_500, tracksCreated: 9);
        await SeedJobForRunAsync(factory, earlier.ProcessingRunId);

        using var scope = factory.Services.CreateScope();
        var orchestrator = scope.ServiceProvider.GetRequiredService<IProcessingOrchestrator>();
        var status = await orchestrator.GetStatusAsync(video.VideoId, CancellationToken.None);

        Assert.True(status.Found);
        Assert.NotNull(status.LatestRun);
        Assert.Equal(latestRunId, status.LatestRun.ProcessingRunId);
        Assert.Equal("Completed", status.LatestRun.Status);
        Assert.Equal(1_500, status.LatestRun.FramesProcessed);
        Assert.Equal(9, status.LatestRun.TracksCreated);

        // The earlier run's counters (100 frames, 1 track from the shared seed) are not what is reported.
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var earlierRun = await db.ProcessingRuns.AsNoTracking().SingleAsync(run => run.Id == earlier.ProcessingRunId);
        Assert.Equal(100, earlierRun.FramesProcessed);
        Assert.NotEqual(earlierRun.FramesProcessed, status.LatestRun.FramesProcessed);
    }

    [Fact]
    public async Task CountersStayZeroWhileTheLatestRunIsStillRunning()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-RUNNING", Now.AddHours(-1));

        var run = ProcessingRun.Create(video.VideoId, "phase1-detection-tracking-v1", "{}", Now.AddMinutes(-2));
        run.MarkRunning("worker-07", Now.AddMinutes(-1));
        var job = VisionJob.Create(run.Id, "phase1-detection-tracking", Now.AddMinutes(-2));
        using (var seed = factory.Services.CreateScope())
        {
            var db = seed.ServiceProvider.GetRequiredService<MaviDbContext>();
            db.ProcessingRuns.Add(run);
            db.VisionJobs.Add(job);
            await db.SaveChangesAsync();
        }

        using var scope = factory.Services.CreateScope();
        var orchestrator = scope.ServiceProvider.GetRequiredService<IProcessingOrchestrator>();
        var status = await orchestrator.GetStatusAsync(video.VideoId, CancellationToken.None);

        Assert.NotNull(status.LatestRun);
        Assert.Equal("Running", status.LatestRun.Status);
        Assert.Equal(0, status.LatestRun.FramesProcessed);
        Assert.Equal(0, status.LatestRun.TracksCreated);
    }

    private static async Task<Guid> SeedCompletedRunWithJobAsync(
        ApiTestFactory factory,
        Guid videoId,
        DateTimeOffset queuedAtUtc,
        long framesProcessed,
        int tracksCreated)
    {
        var run = ProcessingRun.Create(videoId, "phase1-detection-tracking-v1", "{}", queuedAtUtc);
        run.MarkRunning("worker-08", queuedAtUtc.AddSeconds(10));
        var job = VisionJob.Create(run.Id, "phase1-detection-tracking", queuedAtUtc);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.ProcessingRuns.Add(run);
        db.VisionJobs.Add(job);
        await db.SaveChangesAsync();

        await using var transaction = await db.Database.BeginTransactionAsync();
        await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, CancellationToken.None);
        var sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, CancellationToken.None);
        run.MarkCompleted(framesProcessed, tracksCreated, durationMs: 4_000, completedAtUtc: queuedAtUtc.AddMinutes(1));
        run.AssignCompletionVisibilitySequence(sequence);
        await db.SaveChangesAsync();
        await transaction.CommitAsync();
        return run.Id;
    }

    private static async Task SeedJobForRunAsync(ApiTestFactory factory, Guid processingRunId)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.VisionJobs.Add(VisionJob.Create(processingRunId, "phase1-detection-tracking", Now.AddMinutes(-31)));
        await db.SaveChangesAsync();
    }
}
