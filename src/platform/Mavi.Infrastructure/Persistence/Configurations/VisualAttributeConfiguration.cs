using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.Intelligence;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// One Track-level outcome per applicable Track of a completed analysis (ADR-013 §12, §14).
/// </summary>
public sealed class VisualAttributeTrackOutcomeConfiguration : IEntityTypeConfiguration<VisualAttributeTrackOutcome>
{
    public void Configure(EntityTypeBuilder<VisualAttributeTrackOutcome> builder)
    {
        var reasons = string.Join(", ", VisualAttributeContractRules.UnavailableReasons.Order(StringComparer.Ordinal).Select(reason => $"'{reason}'"));
        builder.ToTable("visual_attribute_track_outcomes", table =>
        {
            table.HasCheckConstraint("ck_visual_attribute_track_outcomes_outcome", "outcome IN ('Analysed', 'Unavailable')");
            // Unavailable always explains itself; Analysed never needs to.
            table.HasCheckConstraint("ck_visual_attribute_track_outcomes_shape",
                "(outcome = 'Analysed' AND reason IS NULL) OR " +
                $"(outcome = 'Unavailable' AND reason IS NOT NULL AND reason IN ({reasons}))");
        });
        builder.HasKey(x => new { x.AnalysisId, x.TrackId });
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.Outcome).HasColumnName("outcome").HasConversion<string>().HasMaxLength(16).IsRequired();
        builder.Property(x => x.Reason).HasColumnName("reason").HasMaxLength(64);
        builder.HasOne<VisualAttributeAnalysis>().WithMany().HasForeignKey(x => x.AnalysisId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => x.TrackId).HasDatabaseName("ix_visual_attribute_track_outcomes_track");
    }
}

/// <summary>
/// The final Track-level attribute fact (ADR-013 §14), replacing the Stage-1 placeholder
/// shape (per-row model name/version, SetNull evidence, no analysis). Search indexes are S3's
/// to add from measured plans; only integrity indexes live here.
/// </summary>
public sealed class VisualAttributeConfiguration : IEntityTypeConfiguration<VisualAttribute>
{
    public void Configure(EntityTypeBuilder<VisualAttribute> builder)
    {
        builder.ToTable("visual_attributes", table =>
        {
            table.HasCheckConstraint("ck_visual_attributes_outcome", "outcome IN ('Observed', 'Unknown')");
            // Observed asserts a value with its confidence and evidence; Unknown asserts nothing.
            table.HasCheckConstraint("ck_visual_attributes_shape",
                "(outcome = 'Observed' AND value IS NOT NULL AND confidence IS NOT NULL AND " +
                "confidence >= 0 AND confidence <= 1 AND supporting_observation_id IS NOT NULL) OR " +
                "(outcome = 'Unknown' AND value IS NULL AND confidence IS NULL AND supporting_observation_id IS NULL)");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.AttributeType).HasColumnName("attribute_type").HasMaxLength(64).IsRequired();
        builder.Property(x => x.Outcome).HasColumnName("outcome").HasConversion<string>().HasMaxLength(16).IsRequired();
        builder.Property(x => x.Value).HasColumnName("value").HasMaxLength(64);
        builder.Property(x => x.Confidence).HasColumnName("confidence");
        builder.Property(x => x.SupportingObservationId).HasColumnName("supporting_observation_id");
        builder.HasOne<VisualAttributeAnalysis>().WithMany().HasForeignKey(x => x.AnalysisId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<Observation>().WithMany().HasForeignKey(x => x.SupportingObservationId).OnDelete(DeleteBehavior.Restrict);
        // Every fact sits under its Track's outcome for the same analysis.
        builder.HasOne<VisualAttributeTrackOutcome>().WithMany()
            .HasForeignKey(x => new { x.AnalysisId, x.TrackId })
            .HasPrincipalKey(x => new { x.AnalysisId, x.TrackId })
            .OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => new { x.AnalysisId, x.TrackId, x.AttributeType })
            .IsUnique()
            .HasDatabaseName("ux_visual_attributes_analysis_track_type");
        builder.HasIndex(x => x.TrackId).HasDatabaseName("ix_visual_attributes_track");
        builder.HasIndex(x => x.SupportingObservationId).HasDatabaseName("ix_visual_attributes_supporting_observation");
    }
}
