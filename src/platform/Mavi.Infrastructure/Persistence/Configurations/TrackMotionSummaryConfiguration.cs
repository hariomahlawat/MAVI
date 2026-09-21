using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.ChangeTracking;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// Per-Track motion diagnostics.
/// </summary>
/// <remarks>
/// The two jsonb columns are the only jsonb §O allows on a fact table, and both are
/// evidence-display detail: variable-length lists nothing searches by element. The
/// duration columns beside them are what predicates use, and they stay typed.
/// </remarks>
public sealed class TrackMotionSummaryConfiguration : IEntityTypeConfiguration<TrackMotionSummary>
{
    private static readonly ValueConverter<IReadOnlyList<StationaryInterval>, string> IntervalsConverter =
        new(intervals => SceneAnalyticsFactJson.WriteIntervals(intervals),
            json => SceneAnalyticsFactJson.ReadIntervals(json));

    private static readonly ValueComparer<IReadOnlyList<StationaryInterval>> IntervalsComparer =
        new(
            (left, right) => left != null && right != null && left.SequenceEqual(right),
            intervals => intervals.Aggregate(0, (hash, interval) => HashCode.Combine(hash, interval)),
            intervals => SceneAnalyticsFactJson.ReadIntervals(SceneAnalyticsFactJson.WriteIntervals(intervals)));

    private static readonly ValueConverter<IReadOnlyList<Guid>, string> ZoneIdsConverter =
        new(ids => SceneAnalyticsFactJson.WriteGuids(ids), json => SceneAnalyticsFactJson.ReadGuids(json));

    private static readonly ValueComparer<IReadOnlyList<Guid>> ZoneIdsComparer =
        new(
            (left, right) => left != null && right != null && left.SequenceEqual(right),
            ids => ids.Aggregate(0, (hash, id) => HashCode.Combine(hash, id)),
            ids => SceneAnalyticsFactJson.ReadGuids(SceneAnalyticsFactJson.WriteGuids(ids)));

    public void Configure(EntityTypeBuilder<TrackMotionSummary> builder)
    {
        builder.ToTable("track_motion_summaries", table =>
        {
            table.HasCheckConstraint(
                "ck_track_motion_summaries_durations",
                "longest_stationary_ms >= 0 AND total_stationary_ms >= 0 " +
                "AND longest_stationary_ms <= total_stationary_ms");
            table.HasCheckConstraint(
                "ck_track_motion_summaries_path",
                "path_length_normalised >= 0 AND mean_displacement_rate >= 0");
            table.HasCheckConstraint(
                "ck_track_motion_summaries_heading",
                $"heading IN ({SceneAnalyticsVocabulary.ToSqlInList(SceneAnalyticsVocabulary.Headings)})");
            table.HasCheckConstraint(
                "ck_track_motion_summaries_json_shape",
                "jsonb_typeof(stationary_intervals) = 'array' AND jsonb_typeof(stationary_zone_ids) = 'array'");
        });

        builder.HasKey(x => new { x.AnalysisId, x.TrackId });
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.Heading)
            .HasColumnName("heading").HasMaxLength(SceneAnalyticsVocabulary.MaximumLength).IsRequired();
        builder.Property(x => x.PathLengthNormalised).HasColumnName("path_length_normalised");
        builder.Property(x => x.MeanDisplacementRate).HasColumnName("mean_displacement_rate");
        builder.Property(x => x.LongestStationaryMs).HasColumnName("longest_stationary_ms");
        builder.Property(x => x.TotalStationaryMs).HasColumnName("total_stationary_ms");
        builder.Property(x => x.StationaryIntervals)
            .HasField("_stationaryIntervals")
            .UsePropertyAccessMode(PropertyAccessMode.Field)
            .HasColumnName("stationary_intervals")
            .HasColumnType("jsonb")
            .HasConversion(IntervalsConverter, IntervalsComparer)
            .IsRequired();
        builder.Property(x => x.StationaryZoneIds)
            .HasField("_stationaryZoneIds")
            .UsePropertyAccessMode(PropertyAccessMode.Field)
            .HasColumnName("stationary_zone_ids")
            .HasColumnType("jsonb")
            .HasConversion(ZoneIdsConverter, ZoneIdsComparer)
            .IsRequired();

        SceneAnalyticsFactRelationships.Configure(builder, x => x.AnalysisId, x => x.TrackId);

        builder.HasIndex(x => x.LongestStationaryMs)
            .HasDatabaseName("ix_track_motion_summaries_longest_stationary");
    }
}
