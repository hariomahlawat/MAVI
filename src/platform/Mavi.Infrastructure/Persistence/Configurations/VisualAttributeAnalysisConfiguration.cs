using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// The Visual Attribute analysis header (ADR-013 §14): identity, lifecycle and fencing,
/// provenance, counts, prediction artefact and visibility.
/// </summary>
/// <remarks>
/// <c>lease_token_hash</c> and <c>last_failed_token_hash</c> hold SHA-256 hashes of the
/// capability, never a capability. Default selection is not a column: it is derived from the
/// preferred identity (ADR-013 implementation amendment 2026-09-28, item 5), so the schema
/// cannot hold a "default" that disagrees with the binding.
/// </remarks>
public sealed class VisualAttributeAnalysisConfiguration : IEntityTypeConfiguration<VisualAttributeAnalysis>
{
    public void Configure(EntityTypeBuilder<VisualAttributeAnalysis> builder)
    {
        builder.ToTable("visual_attribute_analyses", table =>
        {
            table.HasCheckConstraint("ck_visual_attribute_analyses_status",
                "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
            table.HasCheckConstraint("ck_visual_attribute_analyses_attempt_count", "attempt_count >= 0");
            table.HasCheckConstraint("ck_visual_attribute_analyses_counts",
                "tracks_analysed >= 0 AND tracks_unavailable >= 0 AND attributes_observed >= 0 AND attributes_unknown >= 0");
            table.HasCheckConstraint("ck_visual_attribute_analyses_lease_token_hash",
                "lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32");
            table.HasCheckConstraint("ck_visual_attribute_analyses_last_failed_token_hash",
                "last_failed_token_hash IS NULL OR octet_length(last_failed_token_hash) = 32");
            table.HasCheckConstraint("ck_visual_attribute_analyses_sha256",
                "identity_fingerprint ~ '^[0-9a-f]{64}$' AND attribute_schema_sha256 ~ '^[0-9a-f]{64}$' AND " +
                "aggregation_policy_sha256 ~ '^[0-9a-f]{64}$' AND parameters_sha256 ~ '^[0-9a-f]{64}$' AND " +
                "(completion_digest IS NULL OR completion_digest ~ '^[0-9a-f]{64}$')");
            // Running always has a lease; a fact-bearing unit always has what it published.
            table.HasCheckConstraint("ck_visual_attribute_analyses_running_lease",
                "status <> 'Running' OR (lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND " +
                "lease_expires_at_utc IS NOT NULL AND first_claimed_at_utc IS NOT NULL AND attempt_count > 0)");
            table.HasCheckConstraint("ck_visual_attribute_analyses_fact_bearing",
                "status NOT IN ('Completed', 'Superseded') OR (completion_digest IS NOT NULL AND " +
                "visibility_sequence IS NOT NULL AND prediction_artifact_id IS NOT NULL AND provenance_json IS NOT NULL AND " +
                "completed_at_utc IS NOT NULL)");
            table.HasCheckConstraint("ck_visual_attribute_analyses_unpublished",
                "status IN ('Completed', 'Superseded') OR (visibility_sequence IS NULL AND prediction_artifact_id IS NULL)");
            table.HasCheckConstraint("ck_visual_attribute_analyses_failed",
                "status <> 'Failed' OR (failure_code IS NOT NULL AND completed_at_utc IS NOT NULL)");
            table.HasCheckConstraint("ck_visual_attribute_analyses_visibility_sequence",
                "visibility_sequence IS NULL OR visibility_sequence > 0");
        });

        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id");
        builder.Property(x => x.IdentityFingerprint).HasColumnName("identity_fingerprint").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.AttributeSchemaId).HasColumnName("attribute_schema_id").HasMaxLength(64).IsRequired();
        builder.Property(x => x.AttributeSchemaVersion).HasColumnName("attribute_schema_version").HasMaxLength(64).IsRequired();
        builder.Property(x => x.AttributeSchemaSha256).HasColumnName("attribute_schema_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.PipelineId).HasColumnName("pipeline_id").HasMaxLength(64).IsRequired();
        builder.Property(x => x.PipelineVersion).HasColumnName("pipeline_version").HasMaxLength(64).IsRequired();
        builder.Property(x => x.AggregationPolicyId).HasColumnName("aggregation_policy_id").HasMaxLength(64).IsRequired();
        builder.Property(x => x.AggregationPolicyVersion).HasColumnName("aggregation_policy_version").HasMaxLength(64).IsRequired();
        builder.Property(x => x.AggregationPolicySha256).HasColumnName("aggregation_policy_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.CapabilitiesCanonical).HasColumnName("capabilities_canonical").HasMaxLength(1024).IsRequired();
        builder.Property(x => x.ParametersSha256).HasColumnName("parameters_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
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
        builder.Property(x => x.FailureDetails).HasColumnName("failure_details").HasMaxLength(4000);
        builder.Property(x => x.LastFailedWorkerId).HasColumnName("last_failed_worker_id").HasMaxLength(128);
        builder.Property(x => x.LastFailedAttempt).HasColumnName("last_failed_attempt");
        builder.Property(x => x.LastFailedTokenHash).HasColumnName("last_failed_token_hash");
        builder.Property(x => x.LastFailedCode).HasColumnName("last_failed_code").HasMaxLength(64);
        builder.Property(x => x.LastFailedDetails).HasColumnName("last_failed_details").HasMaxLength(4000);
        builder.Property(x => x.LastFailedOutcome).HasColumnName("last_failed_outcome").HasConversion<string>().HasMaxLength(16);
        builder.Property(x => x.CompletionDigest).HasColumnName("completion_digest").HasMaxLength(64).IsFixedLength();
        builder.Property(x => x.PredictionArtifactId).HasColumnName("prediction_artifact_id");
        builder.Property(x => x.ProvenanceJson).HasColumnName("provenance_json").HasColumnType("jsonb");
        builder.Property(x => x.TracksAnalysed).HasColumnName("tracks_analysed");
        builder.Property(x => x.TracksUnavailable).HasColumnName("tracks_unavailable");
        builder.Property(x => x.AttributesObserved).HasColumnName("attributes_observed");
        builder.Property(x => x.AttributesUnknown).HasColumnName("attributes_unknown");
        builder.Property(x => x.VisibilitySequence).HasColumnName("visibility_sequence");
        builder.Ignore(x => x.Identity);
        builder.Ignore(x => x.IsFactBearing);

        // Restrict: facts derived from a run or sealed into an artefact must not lose either.
        builder.HasOne<ProcessingRun>().WithMany().HasForeignKey(x => x.ProcessingRunId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<Artifact>().WithMany().HasForeignKey(x => x.PredictionArtifactId).OnDelete(DeleteBehavior.Restrict);

        // The identity. Queueing inserts and relies on this constraint, never on check-then-insert.
        builder.HasIndex(x => new { x.ProcessingRunId, x.IdentityFingerprint })
            .IsUnique()
            .HasDatabaseName("ux_visual_attribute_analyses_identity");

        // The claim's and the sweep's working set only.
        builder.HasIndex(x => new { x.IdentityFingerprint, x.Status, x.QueuedAtUtc })
            .HasDatabaseName("ix_visual_attribute_analyses_claim")
            .HasFilter("status IN ('Queued', 'Running')");

        builder.HasIndex(x => x.VisibilitySequence)
            .IsUnique()
            .HasDatabaseName("ux_visual_attribute_analyses_visibility_sequence")
            .HasFilter("visibility_sequence IS NOT NULL");

        builder.HasIndex(x => x.PredictionArtifactId)
            .IsUnique()
            .HasDatabaseName("ux_visual_attribute_analyses_prediction_artifact")
            .HasFilter("prediction_artifact_id IS NOT NULL");
    }
}

public sealed class VisualAttributeAttemptFailureConfiguration : IEntityTypeConfiguration<VisualAttributeAttemptFailure>
{
    public void Configure(EntityTypeBuilder<VisualAttributeAttemptFailure> builder)
    {
        builder.ToTable("visual_attribute_attempt_failures", table =>
            table.HasCheckConstraint("ck_visual_attribute_attempt_failures_attempt", "attempt_number >= 1"));
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.AttemptNumber).HasColumnName("attempt_number");
        builder.Property(x => x.FailureCode).HasColumnName("failure_code").HasMaxLength(64).IsRequired();
        builder.Property(x => x.Retryable).HasColumnName("retryable");
        builder.Property(x => x.FailureDetails).HasColumnName("failure_details").HasMaxLength(4000);
        builder.Property(x => x.FailedAtUtc).HasColumnName("failed_at_utc");
        builder.HasOne<VisualAttributeAnalysis>().WithMany().HasForeignKey(x => x.AnalysisId).OnDelete(DeleteBehavior.Restrict);
        // One recorded failure per attempt: a replayed failure never writes a second row.
        builder.HasIndex(x => new { x.AnalysisId, x.AttemptNumber })
            .IsUnique()
            .HasDatabaseName("ux_visual_attribute_attempt_failures_attempt");
    }
}

public sealed class VisualAttributeIdentityActivationConfiguration : IEntityTypeConfiguration<VisualAttributeIdentityActivation>
{
    public void Configure(EntityTypeBuilder<VisualAttributeIdentityActivation> builder)
    {
        builder.ToTable("visual_attribute_identity_activations", table =>
            table.HasCheckConstraint("ck_visual_attribute_identity_activations_fingerprint", "fingerprint ~ '^[0-9a-f]{64}$'"));
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.Fingerprint).HasColumnName("fingerprint").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.CanonicalIdentity).HasColumnName("canonical_identity").HasMaxLength(4096).IsRequired();
        builder.Property(x => x.ActivatedAtUtc).HasColumnName("activated_at_utc");
        builder.HasIndex(x => x.ActivatedAtUtc).HasDatabaseName("ix_visual_attribute_identity_activations_activated");
    }
}
