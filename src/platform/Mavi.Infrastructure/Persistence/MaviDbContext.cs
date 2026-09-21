using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence;

public sealed class MaviDbContext(DbContextOptions<MaviDbContext> options) : DbContext(options)
{
    // Entity sets
    public DbSet<Camera> Cameras => Set<Camera>();
    public DbSet<Artifact> Artifacts => Set<Artifact>();
    public DbSet<VideoAsset> VideoAssets => Set<VideoAsset>();
    public DbSet<ProcessingRun> ProcessingRuns => Set<ProcessingRun>();
    public DbSet<VisionJob> VisionJobs => Set<VisionJob>();
    public DbSet<Track> Tracks => Set<Track>();
    public DbSet<Observation> Observations => Set<Observation>();
    public DbSet<VisualAttribute> VisualAttributes => Set<VisualAttribute>();
    public DbSet<Entity> Entities => Set<Entity>();
    public DbSet<SceneConfiguration> SceneConfigurations => Set<SceneConfiguration>();
    public DbSet<SceneConfigurationRevision> SceneConfigurationRevisions => Set<SceneConfigurationRevision>();
    public DbSet<SceneAnalysis> SceneAnalyses => Set<SceneAnalysis>();
    public DbSet<TrackAnalysisOutcome> TrackAnalysisOutcomes => Set<TrackAnalysisOutcome>();
    public DbSet<TrackZoneVisit> TrackZoneVisits => Set<TrackZoneVisit>();
    public DbSet<TrackZoneSummary> TrackZoneSummaries => Set<TrackZoneSummary>();
    public DbSet<TrackLineCrossing> TrackLineCrossings => Set<TrackLineCrossing>();
    public DbSet<TrackMotionSummary> TrackMotionSummaries => Set<TrackMotionSummary>();

    // Model configuration
    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.HasPostgresExtension("vector");
        modelBuilder.HasSequence<long>(ProcessingVisibilityBarrier.SequenceName);
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(MaviDbContext).Assembly);
    }
}
