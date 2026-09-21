using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// The analysis unit: one processing run evaluated against one scene revision by one
/// algorithm version.
/// </summary>
/// <remarks>
/// <para>
/// <b>Nothing here encodes lease expiry as ownership loss.</b> There is no query
/// filter hiding an expired unit, no check constraint treating expiry as failure and
/// no trigger. <c>lease_expires_at_utc</c> is plain data; ADR-011 decision 4 makes an
/// expired unit *reclaimable*, and ownership changes only in the reclaim or exhaustion
/// transaction that a later phase writes. Copying <c>VisionJob</c>'s clock-based rule
/// into the schema would silently reintroduce exactly the defect the ADR forbids.
/// </para>
/// <para>
/// <c>claim_token_hash</c> stores the SHA-256 of the opaque token, never the token.
/// </para>
/// </remarks>
public sealed class SceneAnalysisConfiguration : IEntityTypeConfiguration<SceneAnalysis>
{
    public void Configure(EntityTypeBuilder<SceneAnalysis> builder)
    {
        builder.ToTable("scene_analyses", table =>
        {
            table.HasCheckConstraint(
                "ck_scene_analyses_attempt_count",
                "attempt_count >= 0");
            table.HasCheckConstraint(
                "ck_scene_analyses_track_counts",
                "analysed_track_count >= 0 AND unavailable_track_count >= 0");
            table.HasCheckConstraint(
                "ck_scene_analyses_visibility_sequence",
                "visibility_sequence IS NULL OR visibility_sequence > 0");
            // 32 bytes or absent: a hash of the wrong length is not a hash.
            table.HasCheckConstraint(
                "ck_scene_analyses_claim_token_hash",
                "claim_token_hash IS NULL OR octet_length(claim_token_hash) = 32");
            table.HasCheckConstraint(
                "ck_scene_analyses_status",
                "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
            table.HasCheckConstraint(
                "ck_scene_analyses_parameters_sha256",
                "parameters_sha256 ~ '^[0-9a-f]{64}$'");
        });

        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id");
        builder.Property(x => x.RevisionId).HasColumnName("revision_id");
        builder.Property(x => x.AlgorithmVersion).HasColumnName("algorithm_version").HasMaxLength(64).IsRequired();
        builder.Property(x => x.ParametersSha256).HasColumnName("parameters_sha256").HasMaxLength(64).IsRequired();
        // Forensics only (§R): recorded on the unit, never part of identity or staleness.
        builder.Property(x => x.SourceCommit).HasColumnName("source_commit").HasMaxLength(64);
        builder.Property(x => x.Status).HasColumnName("status").HasConversion<string>().HasMaxLength(32).IsRequired();
        builder.Property(x => x.AttemptCount).HasColumnName("attempt_count");
        builder.Property(x => x.ClaimTokenHash).HasColumnName("claim_token_hash");
        builder.Property(x => x.LeaseExpiresAtUtc).HasColumnName("lease_expires_at_utc");
        builder.Property(x => x.QueuedAtUtc).HasColumnName("queued_at_utc");
        builder.Property(x => x.StartedAtUtc).HasColumnName("started_at_utc");
        builder.Property(x => x.CompletedAtUtc).HasColumnName("completed_at_utc");
        builder.Property(x => x.VisibilitySequence).HasColumnName("visibility_sequence");
        builder.Property(x => x.AnalysedTrackCount).HasColumnName("analysed_track_count");
        builder.Property(x => x.UnavailableTrackCount).HasColumnName("unavailable_track_count");
        builder.Property(x => x.FailureCode).HasColumnName("failure_code").HasMaxLength(64);
        builder.Property(x => x.FailureDetails).HasColumnName("failure_details").HasMaxLength(4000);

        // Restrict on both: a run or a revision that facts were computed from must not
        // disappear underneath them.
        builder.HasOne<ProcessingRun>()
            .WithMany()
            .HasForeignKey(x => x.ProcessingRunId)
            .OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<SceneConfigurationRevision>()
            .WithMany()
            .HasForeignKey(x => x.RevisionId)
            .OnDelete(DeleteBehavior.Restrict);

        // The identity. Re-analysis and explicit retry both rely on this constraint
        // rather than on a read-then-write, so it is the arbiter under concurrency.
        builder.HasIndex(x => new { x.ProcessingRunId, x.RevisionId, x.AlgorithmVersion })
            .IsUnique()
            .HasDatabaseName("ux_scene_analyses_identity");

        builder.HasIndex(x => x.ProcessingRunId)
            .HasDatabaseName("ix_scene_analyses_run");

        // The reconciler's and claimer's working set only: partial, so the index stays
        // the size of the queue rather than the size of history.
        builder.HasIndex(x => new { x.Status, x.QueuedAtUtc })
            .HasDatabaseName("ix_scene_analyses_pending")
            .HasFilter("status IN ('Queued', 'Running')");

        // One unit per allocated sequence; many units have none yet, and PostgreSQL
        // treats NULLs as distinct so the partial filter is what keeps them legal.
        builder.HasIndex(x => x.VisibilitySequence)
            .IsUnique()
            .HasDatabaseName("ux_scene_analyses_visibility_sequence")
            .HasFilter("visibility_sequence IS NOT NULL");
    }
}
