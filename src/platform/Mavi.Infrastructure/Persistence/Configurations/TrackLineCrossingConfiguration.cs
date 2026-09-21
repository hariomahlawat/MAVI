using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>One confirmed crossing of one trip line.</summary>
public sealed class TrackLineCrossingConfiguration : IEntityTypeConfiguration<TrackLineCrossing>
{
    public void Configure(EntityTypeBuilder<TrackLineCrossing> builder)
    {
        builder.ToTable("track_line_crossings", table =>
        {
            table.HasCheckConstraint(
                "ck_track_line_crossings_indexes",
                "crossing_index >= 0 AND offset_ms >= 0");
            table.HasCheckConstraint(
                "ck_track_line_crossings_direction",
                $"direction IN ({SceneAnalyticsVocabulary.ToSqlInList(SceneAnalyticsVocabulary.CrossingDirections)})");
            // The crossing point is normalised image space, like every other
            // coordinate the platform stores.
            table.HasCheckConstraint(
                "ck_track_line_crossings_point",
                "point_x >= 0 AND point_x <= 1 AND point_y >= 0 AND point_y <= 1");
        });

        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.LineId).HasColumnName("line_id");
        builder.Property(x => x.CrossingIndex).HasColumnName("crossing_index");
        builder.Property(x => x.OffsetMs).HasColumnName("offset_ms");
        builder.Property(x => x.TimestampUtc).HasColumnName("timestamp_utc");
        builder.Property(x => x.Direction)
            .HasColumnName("direction").HasMaxLength(SceneAnalyticsVocabulary.MaximumLength).IsRequired();
        builder.Property(x => x.PointX).HasColumnName("point_x");
        builder.Property(x => x.PointY).HasColumnName("point_y");

        SceneAnalyticsFactRelationships.Configure(builder, x => x.AnalysisId, x => x.TrackId);

        builder.HasIndex(x => new { x.AnalysisId, x.TrackId, x.LineId, x.CrossingIndex })
            .IsUnique()
            .HasDatabaseName("ux_track_line_crossings_identity");

        builder.HasIndex(x => new { x.LineId, x.TimestampUtc, x.Direction })
            .HasDatabaseName("ix_track_line_crossings_line_time_direction");
    }
}
