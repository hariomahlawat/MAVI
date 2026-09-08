using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class ProcessingRunConfiguration : IEntityTypeConfiguration<ProcessingRun>
{
    public void Configure(EntityTypeBuilder<ProcessingRun> builder)
    {
        builder.ToTable("processing_runs", t => { t.HasCheckConstraint("ck_processing_runs_frames", "frames_processed >= 0"); t.HasCheckConstraint("ck_processing_runs_tracks", "tracks_created >= 0"); }); builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id"); builder.Property(x => x.VideoAssetId).HasColumnName("video_asset_id"); builder.Property(x => x.Status).HasColumnName("status").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.PipelineVersion).HasColumnName("pipeline_version").HasMaxLength(64).IsRequired(); builder.Property(x => x.DetectorName).HasColumnName("detector_name").HasMaxLength(128); builder.Property(x => x.DetectorVersion).HasColumnName("detector_version").HasMaxLength(128); builder.Property(x => x.TrackerName).HasColumnName("tracker_name").HasMaxLength(128); builder.Property(x => x.TrackerVersion).HasColumnName("tracker_version").HasMaxLength(128); builder.Property(x => x.ConfigurationJson).HasColumnName("configuration_json").HasColumnType("jsonb").IsRequired(); builder.Property(x => x.WorkerId).HasColumnName("worker_id").HasMaxLength(128); builder.Property(x => x.QueuedAtUtc).HasColumnName("queued_at_utc"); builder.Property(x => x.StartedAtUtc).HasColumnName("started_at_utc"); builder.Property(x => x.CompletedAtUtc).HasColumnName("completed_at_utc"); builder.Property(x => x.FramesProcessed).HasColumnName("frames_processed"); builder.Property(x => x.TracksCreated).HasColumnName("tracks_created"); builder.Property(x => x.ProcessingDurationMs).HasColumnName("processing_duration_ms"); builder.Property(x => x.ErrorCode).HasColumnName("error_code").HasMaxLength(64); builder.Property(x => x.ErrorDetails).HasColumnName("error_details").HasMaxLength(4000);
        builder.HasOne<VideoAsset>().WithMany().HasForeignKey(x => x.VideoAssetId).OnDelete(DeleteBehavior.Cascade); builder.HasIndex(x => x.VideoAssetId); builder.HasIndex(x => x.Status);
    }
}
