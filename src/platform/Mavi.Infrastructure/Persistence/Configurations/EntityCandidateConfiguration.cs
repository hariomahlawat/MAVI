using Mavi.Domain.Embeddings;
using Mavi.Domain.Intelligence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>One catalogue version's derivation of one completed embedding analysis (ADR-023 §2).</summary>
public sealed class EntityCandidateDerivationConfiguration : IEntityTypeConfiguration<EntityCandidateDerivation>
{
    public void Configure(EntityTypeBuilder<EntityCandidateDerivation> builder)
    {
        builder.ToTable("entity_candidate_derivations", table =>
        {
            table.HasCheckConstraint("ck_entity_candidate_derivations_count", "candidate_count >= 0");
            table.HasCheckConstraint("ck_entity_candidate_derivations_outcome", "outcome IN ('derived', 'not_visible')");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.EmbeddingAnalysisId).HasColumnName("embedding_analysis_id");
        builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id");
        builder.Property(x => x.CatalogueVersion).HasColumnName("catalogue_version").HasMaxLength(EntityCandidate.MaximumTokenLength).IsRequired();
        builder.Property(x => x.CatalogueSha256).HasColumnName("catalogue_sha256").HasMaxLength(64).IsRequired();
        builder.Property(x => x.IdentityFingerprint).HasColumnName("identity_fingerprint").HasMaxLength(64).IsRequired();
        builder.Property(x => x.Outcome).HasColumnName("outcome").HasMaxLength(32).IsRequired();
        builder.Property(x => x.CandidateCount).HasColumnName("candidate_count");
        builder.Property(x => x.DerivedAtUtc).HasColumnName("derived_at_utc");

        // The backstop against a second writer: one derivation per analysis and catalogue version.
        builder.HasIndex(x => new { x.EmbeddingAnalysisId, x.CatalogueVersion })
            .IsUnique()
            .HasDatabaseName("ux_entity_candidate_derivations_analysis_catalogue");
        builder.HasOne<EmbeddingAnalysis>().WithMany().HasForeignKey(x => x.EmbeddingAnalysisId).OnDelete(DeleteBehavior.Cascade);
    }
}

/// <summary>
/// One Entity candidate (ADR-023 §2, §8): the pair, its separate factors and its one decision. Candidates go with
/// either of their Tracks (cascade), so deleting a run removes them; the decision's audit row stays.
/// </summary>
public sealed class EntityCandidateConfiguration : IEntityTypeConfiguration<EntityCandidate>
{
    public void Configure(EntityTypeBuilder<EntityCandidate> builder)
    {
        builder.ToTable("entity_candidates", table =>
        {
            table.HasCheckConstraint("ck_entity_candidates_pair_order", "lower_track_id < higher_track_id");
            table.HasCheckConstraint("ck_entity_candidates_score", "appearance_score >= -1 AND appearance_score <= 1");
            table.HasCheckConstraint("ck_entity_candidates_class", "object_class IN ('Person', 'Vehicle')");
            table.HasCheckConstraint(
                "ck_entity_candidates_decision",
                "(status = 'Open' AND decided_at_utc IS NULL AND entity_id IS NULL AND decision_audit_entry_id IS NULL) OR " +
                "(status = 'Dismissed' AND decided_at_utc IS NOT NULL AND entity_id IS NULL AND decision_audit_entry_id IS NOT NULL) OR " +
                "(status = 'Confirmed' AND decided_at_utc IS NOT NULL AND entity_id IS NOT NULL AND decision_audit_entry_id IS NOT NULL)");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.DerivationId).HasColumnName("derivation_id");
        builder.Property(x => x.CatalogueVersion).HasColumnName("catalogue_version").HasMaxLength(EntityCandidate.MaximumTokenLength).IsRequired();
        builder.Property(x => x.IdentityFingerprint).HasColumnName("identity_fingerprint").HasMaxLength(64).IsRequired();
        builder.Property(x => x.LowerTrackId).HasColumnName("lower_track_id");
        builder.Property(x => x.HigherTrackId).HasColumnName("higher_track_id");
        builder.Property(x => x.ObjectClass).HasColumnName("object_class").HasConversion<string>().HasMaxLength(32);
        builder.Property(x => x.AppearanceScore).HasColumnName("appearance_score");
        builder.Property(x => x.SameCamera).HasColumnName("same_camera");
        builder.Property(x => x.GapMs).HasColumnName("gap_ms");
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.Property(x => x.Status).HasColumnName("status").HasConversion<string>().HasMaxLength(16);
        builder.Property(x => x.DecidedAtUtc).HasColumnName("decided_at_utc");
        builder.Property(x => x.DecidedByOperatorId).HasColumnName("decided_by_operator_id").HasMaxLength(256);
        builder.Property(x => x.DecidedByDisplayName).HasColumnName("decided_by_display_name").HasMaxLength(256);
        builder.Property(x => x.DecidedByIdentitySource).HasColumnName("decided_by_identity_source").HasMaxLength(64);
        builder.Property(x => x.DecisionNote).HasColumnName("decision_note").HasMaxLength(EntityCandidate.MaximumNoteLength);
        builder.Property(x => x.DecisionAuditEntryId).HasColumnName("decision_audit_entry_id");
        builder.Property(x => x.EntityId).HasColumnName("entity_id");

        builder.HasIndex(x => new { x.CatalogueVersion, x.IdentityFingerprint, x.LowerTrackId, x.HigherTrackId })
            .IsUnique()
            .HasDatabaseName("ux_entity_candidates_pair");
        builder.HasIndex(x => x.HigherTrackId).HasDatabaseName("ix_entity_candidates_higher_track");
        builder.HasIndex(x => new { x.Status, x.AppearanceScore }).HasDatabaseName("ix_entity_candidates_status_score");
        builder.HasOne<EntityCandidateDerivation>().WithMany().HasForeignKey(x => x.DerivationId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.LowerTrackId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.HigherTrackId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Entity>().WithMany().HasForeignKey(x => x.EntityId).OnDelete(DeleteBehavior.Restrict);
    }
}
