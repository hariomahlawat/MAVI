using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>One stay by one Track inside one zone.</summary>
public sealed class TrackZoneVisitConfiguration : IEntityTypeConfiguration<TrackZoneVisit>
{
    public void Configure(EntityTypeBuilder<TrackZoneVisit> builder)
    {
        builder.ToTable("track_zone_visits", table =>
        {
            table.HasCheckConstraint(
                "ck_track_zone_visits_visit_index",
                "visit_index >= 0");
            table.HasCheckConstraint(
                "ck_track_zone_visits_offsets",
                "entry_offset_ms >= 0 AND exit_offset_ms >= entry_offset_ms");
            table.HasCheckConstraint(
                "ck_track_zone_visits_dwell",
                "dwell_ms >= 0");
            table.HasCheckConstraint(
                "ck_track_zone_visits_timestamps",
                "exit_timestamp_utc >= entry_timestamp_utc");
            table.HasCheckConstraint(
                "ck_track_zone_visits_headings",
                $"entry_heading IN ({SceneAnalyticsVocabulary.ToSqlInList(SceneAnalyticsVocabulary.Headings)}) AND " +
                $"exit_heading IN ({SceneAnalyticsVocabulary.ToSqlInList(SceneAnalyticsVocabulary.Headings)})");
        });

        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.ZoneId).HasColumnName("zone_id");
        builder.Property(x => x.VisitIndex).HasColumnName("visit_index");
        builder.Property(x => x.EntryOffsetMs).HasColumnName("entry_offset_ms");
        builder.Property(x => x.ExitOffsetMs).HasColumnName("exit_offset_ms");
        builder.Property(x => x.EntryTimestampUtc).HasColumnName("entry_timestamp_utc");
        builder.Property(x => x.ExitTimestampUtc).HasColumnName("exit_timestamp_utc");
        builder.Property(x => x.DwellMs).HasColumnName("dwell_ms");
        builder.Property(x => x.BeganInside).HasColumnName("began_inside");
        builder.Property(x => x.EndedInside).HasColumnName("ended_inside");
        builder.Property(x => x.ClosedByGap).HasColumnName("closed_by_gap");
        builder.Property(x => x.EntryHeading)
            .HasColumnName("entry_heading").HasMaxLength(SceneAnalyticsVocabulary.MaximumLength).IsRequired();
        builder.Property(x => x.ExitHeading)
            .HasColumnName("exit_heading").HasMaxLength(SceneAnalyticsVocabulary.MaximumLength).IsRequired();

        SceneAnalyticsFactRelationships.Configure(builder, x => x.AnalysisId, x => x.TrackId);

        builder.HasIndex(x => new { x.AnalysisId, x.TrackId, x.ZoneId, x.VisitIndex })
            .IsUnique()
            .HasDatabaseName("ux_track_zone_visits_identity");

        // §Y initial set: the two shapes §S and §T actually query by.
        builder.HasIndex(x => new { x.ZoneId, x.EntryTimestampUtc })
            .HasDatabaseName("ix_track_zone_visits_zone_entry");
        builder.HasIndex(x => new { x.AnalysisId, x.TrackId })
            .HasDatabaseName("ix_track_zone_visits_analysis_track");
    }
}
