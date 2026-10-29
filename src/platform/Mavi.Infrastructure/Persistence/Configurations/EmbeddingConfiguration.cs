using Mavi.Domain.Embeddings;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.ChangeTracking;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using Pgvector;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// One Track's outcome in one embedding analysis (ADR-021 §4): <c>Embedded</c> with its 768-d (identity
/// dimension) vector and the Observations it was averaged from, or <c>Unavailable</c> with a reason. A
/// persistence row, written only by the completion and read only by similarity search; the vector column is
/// pgvector's, so the search orders by <c>&lt;=&gt;</c> (cosine distance) inside PostgreSQL.
/// </summary>
public sealed class TrackEmbeddingRow
{
    public Guid AnalysisId { get; set; }
    public Guid TrackId { get; set; }
    public Guid ProcessingRunId { get; set; }
    public string Outcome { get; set; } = string.Empty;
    public string? UnavailableReason { get; set; }
    public Vector? Embedding { get; set; }
    public Guid[] SourceObservationIds { get; set; } = [];
}

public sealed class EmbeddingAnalysisConfiguration : IEntityTypeConfiguration<EmbeddingAnalysis>
{
    public void Configure(EntityTypeBuilder<EmbeddingAnalysis> builder)
    {
        builder.ToTable("embedding_analyses", table =>
        {
            table.HasCheckConstraint("ck_embedding_analyses_status",
                "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
            table.HasCheckConstraint("ck_embedding_analyses_attempt_count", "attempt_count >= 0");
            table.HasCheckConstraint("ck_embedding_analyses_counts", "tracks_embedded >= 0 AND tracks_unavailable >= 0");
            table.HasCheckConstraint("ck_embedding_analyses_dimension", "dimension BETWEEN 1 AND 4096");
            table.HasCheckConstraint("ck_embedding_analyses_token_hashes",
                "(lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32) AND " +
                "(last_failed_token_hash IS NULL OR octet_length(last_failed_token_hash) = 32)");
            table.HasCheckConstraint("ck_embedding_analyses_sha256",
                "identity_fingerprint ~ '^[0-9a-f]{64}$' AND manifest_sha256 ~ '^[0-9a-f]{64}$' AND " +
                "pipeline_sha256 ~ '^[0-9a-f]{64}$' AND (completion_digest IS NULL OR completion_digest ~ '^[0-9a-f]{64}$')");
            table.HasCheckConstraint("ck_embedding_analyses_running_lease",
                "status <> 'Running' OR (lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND " +
                "lease_expires_at_utc IS NOT NULL AND first_claimed_at_utc IS NOT NULL AND attempt_count > 0)");
            table.HasCheckConstraint("ck_embedding_analyses_fact_bearing",
                "status NOT IN ('Completed', 'Superseded') OR (completion_digest IS NOT NULL AND " +
                "visibility_sequence IS NOT NULL AND provenance_json IS NOT NULL AND completed_at_utc IS NOT NULL)");
            table.HasCheckConstraint("ck_embedding_analyses_unpublished",
                "status IN ('Completed', 'Superseded') OR visibility_sequence IS NULL");
            table.HasCheckConstraint("ck_embedding_analyses_failed",
                "status <> 'Failed' OR (failure_code IS NOT NULL AND completed_at_utc IS NOT NULL)");
        });

        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id");
        builder.Property(x => x.IdentityFingerprint).HasColumnName("identity_fingerprint").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.ModelId).HasColumnName("model_id").HasMaxLength(128).IsRequired();
        builder.Property(x => x.ModelVersion).HasColumnName("model_version").HasMaxLength(64).IsRequired();
        builder.Property(x => x.ManifestSha256).HasColumnName("manifest_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.Dimension).HasColumnName("dimension");
        builder.Property(x => x.PipelineId).HasColumnName("pipeline_id").HasMaxLength(64).IsRequired();
        builder.Property(x => x.PipelineVersion).HasColumnName("pipeline_version").HasMaxLength(64).IsRequired();
        builder.Property(x => x.PipelineSha256).HasColumnName("pipeline_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.Status).HasColumnName("status").HasConversion<string>().HasMaxLength(16).IsRequired();
        builder.Property(x => x.AttemptCount).HasColumnName("attempt_count");
        builder.Property(x => x.LeaseOwner).HasColumnName("lease_owner").HasMaxLength(128);
        builder.Property(x => x.LeaseTokenHash).HasColumnName("lease_token_hash");
        builder.Property(x => x.LeaseExpiresAtUtc).HasColumnName("lease_expires_at_utc");
        builder.Property(x => x.LastHeartbeatUtc).HasColumnName("last_heartbeat_utc");
        builder.Property(x => x.QueuedAtUtc).HasColumnName("queued_at_utc");
        builder.Property(x => x.FirstClaimedAtUtc).HasColumnName("first_claimed_at_utc");
        builder.Property(x => x.CompletedAtUtc).HasColumnName("completed_at_utc");
        builder.Property(x => x.FailureCode).HasColumnName("failure_code").HasMaxLength(64);
        builder.Property(x => x.FailureDetails).HasColumnName("failure_details").HasMaxLength(EmbeddingAnalysis.MaximumFailureDetailsLength);
        builder.Property(x => x.LastFailedWorkerId).HasColumnName("last_failed_worker_id").HasMaxLength(128);
        builder.Property(x => x.LastFailedAttempt).HasColumnName("last_failed_attempt");
        builder.Property(x => x.LastFailedTokenHash).HasColumnName("last_failed_token_hash");
        builder.Property(x => x.LastFailedCode).HasColumnName("last_failed_code").HasMaxLength(64);
        builder.Property(x => x.LastFailedDetails).HasColumnName("last_failed_details").HasMaxLength(EmbeddingAnalysis.MaximumFailureDetailsLength);
        builder.Property(x => x.LastFailedOutcome).HasColumnName("last_failed_outcome").HasConversion<string>().HasMaxLength(16);
        builder.Property(x => x.CompletionDigest).HasColumnName("completion_digest").HasMaxLength(64).IsFixedLength();
        builder.Property(x => x.ProvenanceJson).HasColumnName("provenance_json").HasColumnType("jsonb");
        builder.Property(x => x.TracksEmbedded).HasColumnName("tracks_embedded");
        builder.Property(x => x.TracksUnavailable).HasColumnName("tracks_unavailable");
        builder.Property(x => x.VisibilitySequence).HasColumnName("visibility_sequence");
        builder.Ignore(x => x.Identity);
        builder.Ignore(x => x.IsFactBearing);

        // Derived data goes with its run (ADR-021 §5); nothing here is a run's authority.
        builder.HasOne<ProcessingRun>().WithMany().HasForeignKey(x => x.ProcessingRunId).OnDelete(DeleteBehavior.Cascade);

        builder.HasIndex(x => new { x.ProcessingRunId, x.IdentityFingerprint })
            .IsUnique()
            .HasDatabaseName("ux_embedding_analyses_identity");
        builder.HasIndex(x => new { x.IdentityFingerprint, x.Status, x.QueuedAtUtc })
            .HasDatabaseName("ix_embedding_analyses_claim")
            .HasFilter("status IN ('Queued', 'Running')");
        builder.HasIndex(x => x.VisibilitySequence)
            .IsUnique()
            .HasDatabaseName("ux_embedding_analyses_visibility_sequence")
            .HasFilter("visibility_sequence IS NOT NULL");
    }
}

public sealed class TrackEmbeddingRowConfiguration : IEntityTypeConfiguration<TrackEmbeddingRow>
{
    public void Configure(EntityTypeBuilder<TrackEmbeddingRow> builder)
    {
        builder.ToTable("track_embeddings", table =>
        {
            table.HasCheckConstraint("ck_track_embeddings_outcome",
                "(outcome = 'Embedded' AND embedding IS NOT NULL AND unavailable_reason IS NULL AND cardinality(source_observation_ids) >= 1) OR " +
                "(outcome = 'Unavailable' AND embedding IS NULL AND unavailable_reason IN ('no_evidence', 'evidence_too_small', 'evidence_unavailable') " +
                "AND cardinality(source_observation_ids) = 0)");
        });
        builder.HasKey(x => new { x.AnalysisId, x.TrackId });
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id");
        builder.Property(x => x.Outcome).HasColumnName("outcome").HasMaxLength(16).IsRequired();
        builder.Property(x => x.UnavailableReason).HasColumnName("unavailable_reason").HasMaxLength(32);
        // The column is dimension-free: one table serves every identity, each analysis records its dimension,
        // and the completion checks every vector against it. Search compares vectors of one identity only.
        builder.Property(x => x.Embedding).HasColumnName("embedding").HasColumnType("vector");
        builder.Property(x => x.SourceObservationIds).HasColumnName("source_observation_ids").IsRequired();
        builder.HasOne<EmbeddingAnalysis>().WithMany().HasForeignKey(x => x.AnalysisId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Cascade);
        builder.HasIndex(x => x.TrackId).HasDatabaseName("ix_track_embeddings_track");
    }
}

public sealed class EmbeddingIdentityActivationConfiguration : IEntityTypeConfiguration<EmbeddingIdentityActivation>
{
    public void Configure(EntityTypeBuilder<EmbeddingIdentityActivation> builder)
    {
        builder.ToTable("embedding_identity_activations", table =>
            table.HasCheckConstraint("ck_embedding_identity_activations_fingerprint", "fingerprint ~ '^[0-9a-f]{64}$'"));
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.Fingerprint).HasColumnName("fingerprint").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.CanonicalIdentity).HasColumnName("canonical_identity").HasMaxLength(2048).IsRequired();
        builder.Property(x => x.ActivatedAtUtc).HasColumnName("activated_at_utc");
        builder.HasIndex(x => x.ActivatedAtUtc).HasDatabaseName("ix_embedding_identity_activations_activated");
    }
}

public sealed class AppearanceQueryEmbeddingConfiguration : IEntityTypeConfiguration<AppearanceQueryEmbedding>
{
    public void Configure(EntityTypeBuilder<AppearanceQueryEmbedding> builder)
    {
        builder.ToTable("appearance_query_embeddings", table =>
        {
            table.HasCheckConstraint("ck_appearance_query_embeddings_status", "status IN ('Pending', 'Running', 'Completed', 'Failed')");
            table.HasCheckConstraint("ck_appearance_query_embeddings_completed",
                "(status = 'Completed') = (embedding IS NOT NULL)");
            table.HasCheckConstraint("ck_appearance_query_embeddings_text", "char_length(text) BETWEEN 1 AND 200");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.IdentityFingerprint).HasColumnName("identity_fingerprint").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.Text).HasColumnName("text").HasMaxLength(200).IsRequired();
        builder.Property(x => x.TextSha256).HasColumnName("text_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.Status).HasColumnName("status").HasConversion<string>().HasMaxLength(16).IsRequired();
        builder.Property(x => x.AttemptCount).HasColumnName("attempt_count");
        builder.Property(x => x.LeaseOwner).HasColumnName("lease_owner").HasMaxLength(128);
        builder.Property(x => x.LeaseTokenHash).HasColumnName("lease_token_hash");
        builder.Property(x => x.LeaseExpiresAtUtc).HasColumnName("lease_expires_at_utc");
        builder.Property(x => x.RequestedAtUtc).HasColumnName("requested_at_utc");
        builder.Property(x => x.CompletedAtUtc).HasColumnName("completed_at_utc");
        builder.Property(x => x.FailureCode).HasColumnName("failure_code").HasMaxLength(64);
        builder.Property(x => x.Embedding).HasColumnName("embedding").HasColumnType("vector")
            .HasConversion(new ValueConverter<float[]?, Vector?>(
                value => value == null ? null : new Vector(value),
                value => value == null ? null : value.ToArray()),
                new ValueComparer<float[]?>(
                    (left, right) => left == null ? right == null : right != null && left.SequenceEqual(right),
                    value => value == null ? 0 : value.Aggregate(0, (hash, item) => HashCode.Combine(hash, item)),
                    value => value == null ? null : value.ToArray()));
        builder.HasIndex(x => new { x.IdentityFingerprint, x.TextSha256 })
            .IsUnique()
            .HasDatabaseName("ux_appearance_query_embeddings_text");
        builder.HasIndex(x => new { x.IdentityFingerprint, x.Status, x.RequestedAtUtc })
            .HasDatabaseName("ix_appearance_query_embeddings_claim")
            .HasFilter("status IN ('Pending', 'Running')");
    }
}
