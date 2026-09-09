using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class VisionJobConfiguration : IEntityTypeConfiguration<VisionJob>
{
    public void Configure(EntityTypeBuilder<VisionJob> builder)
    {
        builder.ToTable("vision_jobs", t =>
        {
            t.HasCheckConstraint("ck_vision_jobs_attempts", "attempt_count >= 0");
            t.HasCheckConstraint("ck_vision_jobs_progress", "progress_percent >= 0 AND progress_percent <= 100");
            t.HasCheckConstraint("ck_vision_jobs_lease_token_hash", "lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32");
        }); builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id"); builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id"); builder.Property(x => x.Pipeline).HasColumnName("pipeline").HasMaxLength(64).IsRequired(); builder.Property(x => x.Status).HasColumnName("status").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc"); builder.Property(x => x.AvailableAtUtc).HasColumnName("available_at_utc"); builder.Property(x => x.LeaseOwner).HasColumnName("lease_owner").HasMaxLength(128); builder.Property(x => x.LeaseExpiresAtUtc).HasColumnName("lease_expires_at_utc"); builder.Property(x => x.AttemptCount).HasColumnName("attempt_count"); builder.Property(x => x.ProgressPercent).HasColumnName("progress_percent"); builder.Property(x => x.LastHeartbeatUtc).HasColumnName("last_heartbeat_utc"); builder.Property(x => x.CompletedAtUtc).HasColumnName("completed_at_utc"); builder.Property(x => x.FailureCode).HasColumnName("failure_code").HasMaxLength(64); builder.Property(x => x.FailureDetails).HasColumnName("failure_details").HasMaxLength(4000);
        builder.Property(x => x.LeaseTokenHash).HasColumnName("lease_token_hash").HasColumnType("bytea");
        builder.HasOne<ProcessingRun>().WithOne().HasForeignKey<VisionJob>(x => x.ProcessingRunId).OnDelete(DeleteBehavior.Cascade); builder.HasIndex(x => new { x.Status, x.AvailableAtUtc });
        builder.HasIndex(x => x.LeaseExpiresAtUtc).HasDatabaseName("ix_vision_jobs_expired_lease")
            .HasFilter("status = 'Leased'");
    }
}
