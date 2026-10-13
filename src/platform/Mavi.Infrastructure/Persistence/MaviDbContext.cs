using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Plates;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Mavi.Domain.VisualAttributes;
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
    public DbSet<VisionFinalizationPayload> VisionFinalizationPayloads => Set<VisionFinalizationPayload>();
    public DbSet<Track> Tracks => Set<Track>();
    public DbSet<Observation> Observations => Set<Observation>();
    public DbSet<Entity> Entities => Set<Entity>();
    public DbSet<SceneConfiguration> SceneConfigurations => Set<SceneConfiguration>();
    public DbSet<SceneConfigurationRevision> SceneConfigurationRevisions => Set<SceneConfigurationRevision>();
    public DbSet<SceneAnalysis> SceneAnalyses => Set<SceneAnalysis>();
    public DbSet<TrackAnalysisOutcome> TrackAnalysisOutcomes => Set<TrackAnalysisOutcome>();
    public DbSet<TrackZoneVisit> TrackZoneVisits => Set<TrackZoneVisit>();
    public DbSet<TrackZoneSummary> TrackZoneSummaries => Set<TrackZoneSummary>();
    public DbSet<TrackLineCrossing> TrackLineCrossings => Set<TrackLineCrossing>();
    public DbSet<TrackMotionSummary> TrackMotionSummaries => Set<TrackMotionSummary>();
    public DbSet<VisualAttributeAnalysis> VisualAttributeAnalyses => Set<VisualAttributeAnalysis>();
    public DbSet<VisualAttributeAttemptFailure> VisualAttributeAttemptFailures => Set<VisualAttributeAttemptFailure>();
    public DbSet<VisualAttributeIdentityActivation> VisualAttributeIdentityActivations => Set<VisualAttributeIdentityActivation>();
    public DbSet<VisualAttributeTrackOutcome> VisualAttributeTrackOutcomes => Set<VisualAttributeTrackOutcome>();
    public DbSet<VisualAttribute> VisualAttributes => Set<VisualAttribute>();
    public DbSet<PlateAnalysis> PlateAnalyses => Set<PlateAnalysis>();
    public DbSet<PlateAttemptFailure> PlateAttemptFailures => Set<PlateAttemptFailure>();
    public DbSet<PlateIdentityActivation> PlateIdentityActivations => Set<PlateIdentityActivation>();
    public DbSet<PlateTrackOutcome> PlateTrackOutcomes => Set<PlateTrackOutcome>();
    public DbSet<PlateObservation> PlateObservations => Set<PlateObservation>();
    public DbSet<PlateReading> PlateReadings => Set<PlateReading>();
    public DbSet<PlateTrackText> PlateTrackTexts => Set<PlateTrackText>();

    // Model configuration
    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.HasPostgresExtension("vector");
        // PostgreSQL contrib, shipped in the MAVI PostgreSQL runtime pack (Stage 4 PR-4): the plate
        // search's trigram index (PlateSearchIndexConfiguration).
        modelBuilder.HasPostgresExtension("pg_trgm");
        modelBuilder.HasSequence<long>(ProcessingVisibilityBarrier.SequenceName);
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(MaviDbContext).Assembly);
    }
}
