using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class TrackConfiguration : IEntityTypeConfiguration<Track>
{
    public void Configure(EntityTypeBuilder<Track> builder)
    {
        builder.ToTable("tracks", t => { t.HasCheckConstraint("ck_tracks_offsets", "start_offset_ms >= 0 AND end_offset_ms >= start_offset_ms"); t.HasCheckConstraint("ck_tracks_duration", "duration_ms = end_offset_ms - start_offset_ms"); t.HasCheckConstraint("ck_tracks_detections", "detection_count > 0"); t.HasCheckConstraint("ck_tracks_confidence", "mean_confidence >= 0 AND mean_confidence <= 1 AND max_confidence >= 0 AND max_confidence <= 1"); }); builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id"); builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id"); builder.Property(x => x.VideoAssetId).HasColumnName("video_asset_id"); builder.Property(x => x.EntityId).HasColumnName("entity_id"); builder.Property(x => x.LocalTrackNumber).HasColumnName("local_track_number"); builder.Property(x => x.ObjectClass).HasColumnName("object_class").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.StartOffsetMs).HasColumnName("start_offset_ms"); builder.Property(x => x.EndOffsetMs).HasColumnName("end_offset_ms"); builder.Property(x => x.StartTimestampUtc).HasColumnName("start_timestamp_utc"); builder.Property(x => x.EndTimestampUtc).HasColumnName("end_timestamp_utc"); builder.Property(x => x.DurationMs).HasColumnName("duration_ms"); builder.Property(x => x.DetectionCount).HasColumnName("detection_count"); builder.Property(x => x.MeanConfidence).HasColumnName("mean_confidence"); builder.Property(x => x.MaxConfidence).HasColumnName("max_confidence"); builder.Property(x => x.RepresentativeObservationId).HasColumnName("representative_observation_id"); builder.Property(x => x.TrajectoryArtifactId).HasColumnName("trajectory_artifact_id"); builder.Property(x => x.ReviewStatus).HasColumnName("review_status").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.HasOne<ProcessingRun>().WithMany().HasForeignKey(x => x.ProcessingRunId).OnDelete(DeleteBehavior.Cascade); builder.HasOne<VideoAsset>().WithMany().HasForeignKey(x => x.VideoAssetId).OnDelete(DeleteBehavior.Restrict); builder.HasOne<Entity>().WithMany().HasForeignKey(x => x.EntityId).OnDelete(DeleteBehavior.SetNull); builder.HasOne<Artifact>().WithMany().HasForeignKey(x => x.TrajectoryArtifactId).OnDelete(DeleteBehavior.SetNull); builder.HasOne<Observation>().WithMany().HasForeignKey(x => x.RepresentativeObservationId).OnDelete(DeleteBehavior.SetNull);
        builder.HasIndex(x => new { x.ProcessingRunId, x.LocalTrackNumber }).IsUnique(); builder.HasIndex(x => new { x.VideoAssetId, x.StartTimestampUtc }); builder.HasIndex(x => new { x.ObjectClass, x.StartTimestampUtc }); builder.HasIndex(x => x.ProcessingRunId); builder.HasIndex(x => x.EntityId);
    }
}
