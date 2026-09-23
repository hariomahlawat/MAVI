using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class ObservationConfiguration : IEntityTypeConfiguration<Observation>
{
    public void Configure(EntityTypeBuilder<Observation> builder)
    {
        builder.ToTable("observations", t => { t.HasCheckConstraint("ck_observations_box", "bounding_box_x >= 0 AND bounding_box_y >= 0 AND bounding_box_width >= 0 AND bounding_box_height >= 0 AND bounding_box_x + bounding_box_width <= 1 AND bounding_box_y + bounding_box_height <= 1"); t.HasCheckConstraint("ck_observations_scores", "confidence >= 0 AND confidence <= 1 AND quality_score >= 0 AND quality_score <= 1"); t.HasCheckConstraint("ck_observations_type", "observation_type IN ('Representative', 'NearView', 'EarlyDiverse', 'LateDiverse')"); t.HasCheckConstraint("ck_observations_rank", "evidence_rank >= 0 AND evidence_rank <= 3"); t.HasCheckConstraint("ck_observations_role_rank", "(observation_type = 'Representative') = (evidence_rank = 0)"); t.HasCheckConstraint("ck_observations_selection_score", "selection_score >= 0 AND selection_score <= 1"); }); builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id"); builder.Property(x => x.TrackId).HasColumnName("track_id"); builder.Property(x => x.ObservationType).HasColumnName("observation_type").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.SourceFrameNumber).HasColumnName("source_frame_number"); builder.Property(x => x.VideoOffsetMs).HasColumnName("video_offset_ms"); builder.Property(x => x.TimestampUtc).HasColumnName("timestamp_utc"); builder.Property(x => x.BoundingBoxX).HasColumnName("bounding_box_x"); builder.Property(x => x.BoundingBoxY).HasColumnName("bounding_box_y"); builder.Property(x => x.BoundingBoxWidth).HasColumnName("bounding_box_width"); builder.Property(x => x.BoundingBoxHeight).HasColumnName("bounding_box_height"); builder.Property(x => x.Confidence).HasColumnName("confidence"); builder.Property(x => x.QualityScore).HasColumnName("quality_score"); builder.Property(x => x.EvidenceRank).HasColumnName("evidence_rank").HasDefaultValue(0); builder.Property(x => x.SelectionScore).HasColumnName("selection_score"); builder.Property(x => x.ThumbnailArtifactId).HasColumnName("thumbnail_artifact_id"); builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Cascade); builder.HasOne<Artifact>().WithMany().HasForeignKey(x => x.ThumbnailArtifactId).OnDelete(DeleteBehavior.Restrict); builder.HasIndex(x => x.TrackId);
        builder.HasIndex(x => new { x.TrackId, x.EvidenceRank }).IsUnique().HasDatabaseName("ux_observations_track_rank");
        builder.HasIndex(x => new { x.TrackId, x.ObservationType }).IsUnique().HasDatabaseName("ux_observations_track_role");
        builder.HasIndex(x => new { x.TrackId, x.SourceFrameNumber }).IsUnique().HasDatabaseName("ux_observations_track_frame");
    }
}
