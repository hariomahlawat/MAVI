using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class VideoAssetConfiguration : IEntityTypeConfiguration<VideoAsset>
{
    public void Configure(EntityTypeBuilder<VideoAsset> builder)
    {
        builder.ToTable("video_assets", table =>
        {
            table.HasCheckConstraint("ck_video_assets_duration", "duration_ms > 0");
            table.HasCheckConstraint("ck_video_assets_recording_end", "recording_end_utc = recording_start_utc + duration_ms * INTERVAL '1 millisecond'");
            table.HasCheckConstraint("ck_video_assets_dimensions", "width > 0 AND height > 0");
            table.HasCheckConstraint("ck_video_assets_frame_rate", "frame_rate_numerator > 0 AND frame_rate_denominator > 0");
            table.HasCheckConstraint("ck_video_assets_timestamp_confidence", "timestamp_confidence >= 0 AND timestamp_confidence <= 1");
        });
        builder.HasKey(x => x.Id); builder.Property(x => x.Id).HasColumnName("id"); builder.Property(x => x.CameraId).HasColumnName("camera_id"); builder.Property(x => x.SourceArtifactId).HasColumnName("source_artifact_id");
        builder.Property(x => x.OriginalFileName).HasColumnName("original_file_name").HasMaxLength(255).IsRequired(); builder.Property(x => x.SourceType).HasColumnName("source_type").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.SourceReference).HasColumnName("source_reference").HasMaxLength(512);
        builder.Property(x => x.RecordingStartUtc).HasColumnName("recording_start_utc"); builder.Property(x => x.RecordingEndUtc).HasColumnName("recording_end_utc"); builder.Property(x => x.DurationMs).HasColumnName("duration_ms"); builder.Property(x => x.FrameRateNumerator).HasColumnName("frame_rate_numerator"); builder.Property(x => x.FrameRateDenominator).HasColumnName("frame_rate_denominator"); builder.Property(x => x.Width).HasColumnName("width"); builder.Property(x => x.Height).HasColumnName("height"); builder.Property(x => x.Codec).HasColumnName("codec").HasMaxLength(64);
        builder.Property(x => x.TimestampSource).HasColumnName("timestamp_source").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.TimestampConfidence).HasColumnName("timestamp_confidence"); builder.Property(x => x.ProcessingStatus).HasColumnName("processing_status").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.ImportedAtUtc).HasColumnName("imported_at_utc");
        builder.HasOne<Camera>().WithMany().HasForeignKey(x => x.CameraId).OnDelete(DeleteBehavior.Restrict); builder.HasOne<Artifact>().WithMany().HasForeignKey(x => x.SourceArtifactId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => new { x.CameraId, x.RecordingStartUtc }); builder.HasIndex(x => x.ProcessingStatus); builder.HasIndex(x => x.ImportedAtUtc);
    }
}
