using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Plates;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// One Track-level outcome per Vehicle Track of a completed plate analysis (ADR-013 §12; implementation
/// amendment 2026-10-13, item 15).
/// </summary>
public sealed class PlateTrackOutcomeConfiguration : IEntityTypeConfiguration<PlateTrackOutcome>
{
    public void Configure(EntityTypeBuilder<PlateTrackOutcome> builder)
    {
        var reasons = string.Join(", ", PlateContractRules.TrackUnavailableReasonsBySeverity.Order(StringComparer.Ordinal).Select(reason => $"'{reason}'"));
        builder.ToTable("plate_track_outcomes", table =>
        {
            table.HasCheckConstraint("ck_plate_track_outcomes_outcome", "outcome IN ('Analysed', 'Unavailable')");
            // Unavailable always explains itself and asserts no plate; Analysed never needs a reason.
            table.HasCheckConstraint("ck_plate_track_outcomes_shape",
                "(outcome = 'Analysed' AND reason IS NULL) OR " +
                $"(outcome = 'Unavailable' AND reason IS NOT NULL AND reason IN ({reasons}) AND " +
                "plate_observation_count = 0 AND distinct_text_count = 0)");
            table.HasCheckConstraint("ck_plate_track_outcomes_counts",
                $"plate_observation_count BETWEEN 0 AND {PlateTrackOutcome.MaximumPlateObservations} AND " +
                "distinct_text_count BETWEEN 0 AND plate_observation_count");
        });
        builder.HasKey(x => new { x.AnalysisId, x.TrackId });
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.Outcome).HasColumnName("outcome").HasConversion<string>().HasMaxLength(16).IsRequired();
        builder.Property(x => x.Reason).HasColumnName("reason").HasMaxLength(PlateTrackOutcome.MaximumReasonLength);
        builder.Property(x => x.PlateObservationCount).HasColumnName("plate_observation_count");
        builder.Property(x => x.DistinctTextCount).HasColumnName("distinct_text_count");
        builder.HasOne<PlateAnalysis>().WithMany().HasForeignKey(x => x.AnalysisId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => x.TrackId).HasDatabaseName("ix_plate_track_outcomes_track");
    }
}

/// <summary>
/// One selected plate of one leased evidence crop, held by reference to its sealed source crop (ADR-013
/// implementation amendment 2026-10-13, item 12). Search indexes are PR-4's to add from measured plans;
/// only integrity indexes live here.
/// </summary>
public sealed class PlateObservationConfiguration : IEntityTypeConfiguration<PlateObservation>
{
    public void Configure(EntityTypeBuilder<PlateObservation> builder)
    {
        builder.ToTable("plate_observations", table =>
        {
            table.HasCheckConstraint("ck_plate_observations_outcome", "outcome IN ('Read', 'Unreadable')");
            table.HasCheckConstraint("ck_plate_observations_plate_index",
                $"plate_index BETWEEN 0 AND {PlateObservation.MaximumPlateIndex}");
            // The plate region is a deterministic function of the sealed crop: the box lies inside it.
            table.HasCheckConstraint("ck_plate_observations_box_inside_crop",
                $"crop_width BETWEEN 1 AND {PlateObservation.MaximumCropDimension} AND " +
                $"crop_height BETWEEN 1 AND {PlateObservation.MaximumCropDimension} AND " +
                "box_x >= 0 AND box_y >= 0 AND box_width >= 1 AND box_height >= 1 AND " +
                "box_x + box_width <= crop_width AND box_y + box_height <= crop_height");
            table.HasCheckConstraint("ck_plate_observations_detector_confidence",
                "detector_confidence >= 0 AND detector_confidence <= 1");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.SourceObservationId).HasColumnName("source_observation_id");
        builder.Property(x => x.PlateIndex).HasColumnName("plate_index");
        builder.Property(x => x.BoxX).HasColumnName("box_x");
        builder.Property(x => x.BoxY).HasColumnName("box_y");
        builder.Property(x => x.BoxWidth).HasColumnName("box_width");
        builder.Property(x => x.BoxHeight).HasColumnName("box_height");
        builder.Property(x => x.CropWidth).HasColumnName("crop_width");
        builder.Property(x => x.CropHeight).HasColumnName("crop_height");
        builder.Property(x => x.DetectorConfidence).HasColumnName("detector_confidence");
        builder.Property(x => x.Outcome).HasColumnName("outcome").HasConversion<string>().HasMaxLength(16).IsRequired();

        builder.HasOne<PlateAnalysis>().WithMany().HasForeignKey(x => x.AnalysisId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Restrict);
        // The sealed source crop cannot disappear beneath a plate observation.
        builder.HasOne<Observation>().WithMany().HasForeignKey(x => x.SourceObservationId).OnDelete(DeleteBehavior.Restrict);
        // Every plate observation sits under its Track's outcome for the same analysis.
        builder.HasOne<PlateTrackOutcome>().WithMany()
            .HasForeignKey(x => new { x.AnalysisId, x.TrackId })
            .HasPrincipalKey(x => new { x.AnalysisId, x.TrackId })
            .OnDelete(DeleteBehavior.Restrict);
        builder.HasMany(x => x.Readings).WithOne()
            .HasForeignKey(x => x.PlateObservationId)
            .OnDelete(DeleteBehavior.Restrict);
        builder.Navigation(x => x.Readings).HasField("_readings").UsePropertyAccessMode(PropertyAccessMode.Field);

        builder.HasIndex(x => new { x.AnalysisId, x.SourceObservationId, x.PlateIndex })
            .IsUnique()
            .HasDatabaseName("ux_plate_observations_analysis_source_plate");
        builder.HasIndex(x => new { x.AnalysisId, x.TrackId }).HasDatabaseName("ix_plate_observations_analysis_track");
        builder.HasIndex(x => x.TrackId).HasDatabaseName("ix_plate_observations_track");
        builder.HasIndex(x => x.SourceObservationId).HasDatabaseName("ix_plate_observations_source_observation");
    }
}

/// <summary>
/// One kept reading (ADR-013 implementation amendment 2026-10-13, item 13): raw text verbatim, and the
/// platform's <c>mavi-plate-normalisation-v1</c> derivation beside it.
/// </summary>
public sealed class PlateReadingConfiguration : IEntityTypeConfiguration<PlateReading>
{
    public void Configure(EntityTypeBuilder<PlateReading> builder)
    {
        builder.ToTable("plate_readings", table =>
        {
            table.HasCheckConstraint("ck_plate_readings_rank", $"rank BETWEEN 0 AND {PlateObservation.MaximumReadings - 1}");
            table.HasCheckConstraint("ck_plate_readings_raw_text",
                $"char_length(raw_text) BETWEEN 1 AND {PlateReading.MaximumRawTextLength} AND raw_line_count IN (1, 2)");
            table.HasCheckConstraint("ck_plate_readings_confidence", "confidence >= 0 AND confidence <= 1");
            // ok carries a normalised [A-Z0-9] text and its advisory class; rejected carries neither.
            table.HasCheckConstraint("ck_plate_readings_normalisation",
                "(normalisation_outcome = 'Ok' AND normalised_text IS NOT NULL AND normalised_text ~ '^[A-Z0-9]+$' AND " +
                "normalisation_reason IS NULL AND format_class IN ('in-standard', 'in-bh', 'other')) OR " +
                "(normalisation_outcome = 'Rejected' AND normalised_text IS NULL AND format_class IS NULL AND " +
                "normalisation_reason IN ('empty', 'non-alphanumeric'))");
        });
        builder.HasKey(x => new { x.PlateObservationId, x.Rank });
        builder.Property(x => x.PlateObservationId).HasColumnName("plate_observation_id");
        builder.Property(x => x.Rank).HasColumnName("rank");
        // Bounded in characters by the check above; the column bound is UTF-16 code units' worst case.
        builder.Property(x => x.RawText).HasColumnName("raw_text").HasMaxLength(PlateReading.MaximumRawTextLength).IsRequired();
        builder.Property(x => x.RawLineCount).HasColumnName("raw_line_count");
        builder.Property(x => x.Confidence).HasColumnName("confidence");
        builder.Property(x => x.NormalisedText).HasColumnName("normalised_text").HasMaxLength(PlateReading.MaximumNormalisedTextLength);
        builder.Property(x => x.NormalisationOutcome).HasColumnName("normalisation_outcome").HasConversion<string>().HasMaxLength(16).IsRequired();
        builder.Property(x => x.NormalisationReason).HasColumnName("normalisation_reason").HasMaxLength(32);
        builder.Property(x => x.FormatClass).HasColumnName("format_class").HasMaxLength(16);
    }
}

/// <summary>
/// The search-acceleration Track texts (plan §2.7; §5.1): one row per distinct normalised rank-0 text of a
/// Track's Read plates. PR-4 adds the measured search indexes on <c>normalised_text</c>.
/// </summary>
public sealed class PlateTrackTextConfiguration : IEntityTypeConfiguration<PlateTrackText>
{
    public void Configure(EntityTypeBuilder<PlateTrackText> builder)
    {
        builder.ToTable("plate_track_texts", table =>
        {
            table.HasCheckConstraint("ck_plate_track_texts_text", "normalised_text ~ '^[A-Z0-9]+$'");
            table.HasCheckConstraint("ck_plate_track_texts_support",
                $"support_count BETWEEN 1 AND {PlateTrackOutcome.MaximumPlateObservations}");
            table.HasCheckConstraint("ck_plate_track_texts_confidence", "max_confidence >= 0 AND max_confidence <= 1");
        });
        builder.HasKey(x => new { x.AnalysisId, x.TrackId, x.NormalisedText });
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.NormalisedText).HasColumnName("normalised_text").HasMaxLength(PlateReading.MaximumNormalisedTextLength);
        builder.Property(x => x.SupportCount).HasColumnName("support_count");
        builder.Property(x => x.MaxConfidence).HasColumnName("max_confidence");
        builder.Property(x => x.BestPlateObservationId).HasColumnName("best_plate_observation_id");
        builder.HasOne<PlateTrackOutcome>().WithMany()
            .HasForeignKey(x => new { x.AnalysisId, x.TrackId })
            .HasPrincipalKey(x => new { x.AnalysisId, x.TrackId })
            .OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<PlateObservation>().WithMany().HasForeignKey(x => x.BestPlateObservationId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => x.BestPlateObservationId).HasDatabaseName("ix_plate_track_texts_best_plate_observation");
    }
}
