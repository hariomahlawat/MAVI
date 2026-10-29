using Mavi.Domain.Events;
using Mavi.Domain.Intelligence;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>One catalogue version's evaluation of one fact-bearing unit (ADR-025 §3).</summary>
public sealed class AnalyticEventDerivationConfiguration : IEntityTypeConfiguration<AnalyticEventDerivation>
{
    public void Configure(EntityTypeBuilder<AnalyticEventDerivation> builder)
    {
        builder.ToTable("analytic_event_derivations", table =>
        {
            table.HasCheckConstraint("ck_analytic_event_derivations_count", "event_count >= 0");
            table.HasCheckConstraint("ck_analytic_event_derivations_rule_states", "jsonb_typeof(rule_states) = 'array'");
        });

        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.SceneAnalysisId).HasColumnName("scene_analysis_id");
        builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id");
        builder.Property(x => x.CameraId).HasColumnName("camera_id");
        builder.Property(x => x.SceneRevisionId).HasColumnName("scene_revision_id");
        builder.Property(x => x.AnalyticsAlgorithmVersion)
            .HasColumnName("analytics_algorithm_version").HasMaxLength(AnalyticEvent.MaximumVersionLength).IsRequired();
        builder.Property(x => x.CatalogueVersion)
            .HasColumnName("catalogue_version").HasMaxLength(AnalyticEvent.MaximumVersionLength).IsRequired();
        builder.Property(x => x.CatalogueSha256).HasColumnName("catalogue_sha256").HasMaxLength(64).IsRequired();
        builder.Property(x => x.InputsSha256).HasColumnName("inputs_sha256").HasMaxLength(64).IsRequired();
        builder.Property(x => x.EventCount).HasColumnName("event_count");
        builder.Property(x => x.RuleStatesJson).HasColumnName("rule_states").HasColumnType("jsonb").IsRequired();
        builder.Property(x => x.DerivedAtUtc).HasColumnName("derived_at_utc");

        // The backstop against a second writer: one derivation per unit and catalogue version.
        builder.HasIndex(x => new { x.SceneAnalysisId, x.CatalogueVersion })
            .IsUnique()
            .HasDatabaseName("ux_analytic_event_derivations_unit_catalogue");

        builder.HasOne<SceneAnalysis>()
            .WithMany()
            .HasForeignKey(x => x.SceneAnalysisId)
            .OnDelete(DeleteBehavior.Cascade);
    }
}

/// <summary>One derived event: typed columns for queries, provenance for evidence (ADR-025 §4).</summary>
public sealed class AnalyticEventConfiguration : IEntityTypeConfiguration<AnalyticEvent>
{
    public void Configure(EntityTypeBuilder<AnalyticEvent> builder)
    {
        builder.ToTable("analytic_events", table =>
        {
            table.HasCheckConstraint(
                "ck_analytic_events_span",
                "start_offset_ms >= 0 AND end_offset_ms >= start_offset_ms AND end_utc >= start_utc");
            table.HasCheckConstraint("ck_analytic_events_rule_version", "rule_version >= 1");
            table.HasCheckConstraint("ck_analytic_events_participants", "participant_count >= 0");
            table.HasCheckConstraint(
                "ck_analytic_events_direction",
                $"direction IS NULL OR direction IN ({SceneAnalyticsVocabulary.ToSqlInList(SceneAnalyticsVocabulary.CrossingDirections)})");
            table.HasCheckConstraint("ck_analytic_events_provenance", "jsonb_typeof(provenance) = 'object'");
        });

        // Supplied, deterministic identity (EventDeriver.EventId), never generated here.
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(x => x.DerivationId).HasColumnName("derivation_id");
        builder.Property(x => x.SceneAnalysisId).HasColumnName("scene_analysis_id");
        builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id");
        builder.Property(x => x.VideoAssetId).HasColumnName("video_asset_id");
        builder.Property(x => x.CameraId).HasColumnName("camera_id");
        builder.Property(x => x.SceneRevisionId).HasColumnName("scene_revision_id");
        builder.Property(x => x.AnalyticsAlgorithmVersion)
            .HasColumnName("analytics_algorithm_version").HasMaxLength(AnalyticEvent.MaximumVersionLength).IsRequired();
        builder.Property(x => x.CatalogueVersion)
            .HasColumnName("catalogue_version").HasMaxLength(AnalyticEvent.MaximumVersionLength).IsRequired();
        builder.Property(x => x.RuleId).HasColumnName("rule_id").HasMaxLength(AnalyticEvent.MaximumRuleIdLength).IsRequired();
        builder.Property(x => x.RuleVersion).HasColumnName("rule_version");
        builder.Property(x => x.PrimaryTrackId).HasColumnName("primary_track_id");
        builder.Property(x => x.ObjectClass).HasColumnName("object_class").HasMaxLength(16);
        builder.Property(x => x.ZoneId).HasColumnName("zone_id");
        builder.Property(x => x.LineId).HasColumnName("line_id");
        builder.Property(x => x.Direction).HasColumnName("direction").HasMaxLength(SceneAnalyticsVocabulary.MaximumLength);
        builder.Property(x => x.StartOffsetMs).HasColumnName("start_offset_ms");
        builder.Property(x => x.EndOffsetMs).HasColumnName("end_offset_ms");
        builder.Property(x => x.StartUtc).HasColumnName("start_utc");
        builder.Property(x => x.EndUtc).HasColumnName("end_utc");
        builder.Property(x => x.ParticipantCount).HasColumnName("participant_count");
        builder.Property(x => x.ProvenanceJson).HasColumnName("provenance").HasColumnType("jsonb").IsRequired();
        builder.Property(x => x.InputSha256).HasColumnName("input_sha256").HasMaxLength(64).IsRequired();

        // The timeline reads one camera's window for one catalogue version.
        builder.HasIndex(x => new { x.CameraId, x.CatalogueVersion, x.StartUtc })
            .HasDatabaseName("ix_analytic_events_camera_catalogue_start");
        builder.HasIndex(x => x.SceneAnalysisId).HasDatabaseName("ix_analytic_events_scene_analysis");
        builder.HasIndex(x => x.DerivationId).HasDatabaseName("ix_analytic_events_derivation");
        builder.HasIndex(x => x.PrimaryTrackId).HasDatabaseName("ix_analytic_events_primary_track");

        builder.HasOne<AnalyticEventDerivation>()
            .WithMany()
            .HasForeignKey(x => x.DerivationId)
            .OnDelete(DeleteBehavior.Cascade);

        // As for scene-analytics facts: an event never holds a Track hostage.
        builder.HasOne<Track>()
            .WithMany()
            .HasForeignKey(x => x.PrimaryTrackId)
            .OnDelete(DeleteBehavior.Restrict);
    }
}
