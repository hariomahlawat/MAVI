using Mavi.Domain.Intelligence;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// One row per Track per analysis unit, always — including Tracks whose evidence
/// could not be used.
/// </summary>
public sealed class TrackAnalysisOutcomeConfiguration : IEntityTypeConfiguration<TrackAnalysisOutcome>
{
    public void Configure(EntityTypeBuilder<TrackAnalysisOutcome> builder)
    {
        builder.ToTable("track_analysis_outcomes", table =>
        {
            table.HasCheckConstraint(
                "ck_track_analysis_outcomes_outcome",
                $"outcome IN ({SceneAnalyticsVocabulary.ToSqlInList(Enum.GetNames<TrackAnalysisOutcomeKind>())})");
            table.HasCheckConstraint(
                "ck_track_analysis_outcomes_counts",
                "sample_count >= 0 AND gap_count >= 0 AND gap_total_ms >= 0");
            // The two outcomes carry different evidence, and the row must say which it
            // is: an analysed Track has a reference point and no reason; an unavailable
            // one has a reason and derived nothing.
            table.HasCheckConstraint(
                "ck_track_analysis_outcomes_shape",
                "(outcome = 'Analysed' AND reason IS NULL AND reference_point IS NOT NULL) OR " +
                "(outcome = 'Unavailable' AND reason IS NOT NULL AND reference_point IS NULL " +
                "AND sample_count = 0 AND gap_count = 0 AND gap_total_ms = 0)");
            table.HasCheckConstraint(
                "ck_track_analysis_outcomes_reason",
                "reason IS NULL OR reason IN " +
                $"({SceneAnalyticsVocabulary.ToSqlInList(SceneAnalyticsErrorCodes.TrackUnavailableReasons)})");
            table.HasCheckConstraint(
                "ck_track_analysis_outcomes_reference_point",
                "reference_point IS NULL OR reference_point IN " +
                $"({SceneAnalyticsVocabulary.ToSqlInList(SceneAnalyticsVocabulary.ReferencePoints)})");
        });

        // Composite key: one outcome per Track per unit is the identity, not a
        // constraint bolted onto a surrogate.
        builder.HasKey(x => new { x.AnalysisId, x.TrackId });
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.Outcome).HasColumnName("outcome").HasConversion<string>().HasMaxLength(32).IsRequired();
        builder.Property(x => x.Reason).HasColumnName("reason").HasMaxLength(64);
        builder.Property(x => x.ReferencePoint).HasColumnName("reference_point").HasMaxLength(SceneAnalyticsVocabulary.MaximumLength);
        builder.Property(x => x.SampleCount).HasColumnName("sample_count");
        builder.Property(x => x.GapCount).HasColumnName("gap_count");
        builder.Property(x => x.GapTotalMs).HasColumnName("gap_total_ms");

        SceneAnalyticsFactRelationships.Configure(builder, x => x.AnalysisId, x => x.TrackId);
    }
}
