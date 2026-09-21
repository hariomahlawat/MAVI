using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>Everything one Track did in one zone: the row zone predicates hit.</summary>
public sealed class TrackZoneSummaryConfiguration : IEntityTypeConfiguration<TrackZoneSummary>
{
    public void Configure(EntityTypeBuilder<TrackZoneSummary> builder)
    {
        builder.ToTable("track_zone_summaries", table =>
        {
            table.HasCheckConstraint(
                "ck_track_zone_summaries_counts",
                "visit_count >= 0 AND total_dwell_ms >= 0 AND loitering_dwell_ms >= 0");
            table.HasCheckConstraint(
                "ck_track_zone_summaries_loitering_threshold",
                "loitering_threshold_seconds > 0");
            table.HasCheckConstraint(
                "ck_track_zone_summaries_timestamps",
                "(first_entry_timestamp_utc IS NULL AND last_exit_timestamp_utc IS NULL) OR " +
                "(first_entry_timestamp_utc IS NOT NULL AND last_exit_timestamp_utc IS NOT NULL " +
                "AND last_exit_timestamp_utc >= first_entry_timestamp_utc)");
            // A zone the Track never entered still gets a row, and that row must not
            // claim a window it does not have.
            table.HasCheckConstraint(
                "ck_track_zone_summaries_visitless",
                "visit_count > 0 OR (first_entry_timestamp_utc IS NULL AND total_dwell_ms = 0)");
        });

        builder.HasKey(x => new { x.AnalysisId, x.TrackId, x.ZoneId });
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.ZoneId).HasColumnName("zone_id");
        builder.Property(x => x.VisitCount).HasColumnName("visit_count");
        builder.Property(x => x.TotalDwellMs).HasColumnName("total_dwell_ms");
        builder.Property(x => x.FirstEntryTimestampUtc).HasColumnName("first_entry_timestamp_utc");
        builder.Property(x => x.LastExitTimestampUtc).HasColumnName("last_exit_timestamp_utc");
        builder.Property(x => x.Loitering).HasColumnName("loitering");
        builder.Property(x => x.LoiteringThresholdSeconds).HasColumnName("loitering_threshold_seconds");
        builder.Property(x => x.LoiteringDwellMs).HasColumnName("loitering_dwell_ms");

        SceneAnalyticsFactRelationships.Configure(builder, x => x.AnalysisId, x => x.TrackId);

        builder.HasIndex(x => new { x.ZoneId, x.TotalDwellMs })
            .HasDatabaseName("ix_track_zone_summaries_zone_dwell");
        // Partial: loitering is the rare case, so the index stays small.
        builder.HasIndex(x => new { x.ZoneId, x.Loitering })
            .HasDatabaseName("ix_track_zone_summaries_zone_loitering")
            .HasFilter("loitering");
    }
}
