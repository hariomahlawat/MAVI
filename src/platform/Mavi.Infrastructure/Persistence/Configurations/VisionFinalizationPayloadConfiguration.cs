using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// The exact accepted completion body of one attempt (plan §4). Bound to its job by key and
/// cascade only: neither side has a navigation, so no job, lease, status or search query can
/// load the bytes by accident, and the finalizer reads them on purpose.
/// </summary>
public sealed class VisionFinalizationPayloadConfiguration : IEntityTypeConfiguration<VisionFinalizationPayload>
{
    public void Configure(EntityTypeBuilder<VisionFinalizationPayload> builder)
    {
        builder.ToTable("vision_finalization_payloads", t =>
        {
            t.HasCheckConstraint("ck_vision_finalization_payloads_attempt", "attempt_count >= 1");
            t.HasCheckConstraint(
                "ck_vision_finalization_payloads_length",
                $"payload_length = octet_length(payload) AND payload_length >= 1 AND payload_length <= {WorkerContractRules.MaximumCompletionRequestBodyBytes}");
            t.HasCheckConstraint("ck_vision_finalization_payloads_sha256", "payload_sha256 ~ '^[0-9a-f]{64}$'");
            t.HasCheckConstraint("ck_vision_finalization_payloads_digest", "completion_digest ~ '^[0-9a-f]{64}$'");
        });
        builder.HasKey(x => new { x.JobId, x.AttemptCount });
        builder.Property(x => x.JobId).HasColumnName("job_id");
        builder.Property(x => x.AttemptCount).HasColumnName("attempt_count");
        builder.Property(x => x.Payload).HasColumnName("payload").HasColumnType("bytea").IsRequired();
        builder.Property(x => x.PayloadLength).HasColumnName("payload_length");
        builder.Property(x => x.PayloadSha256).HasColumnName("payload_sha256").HasMaxLength(64).IsRequired();
        builder.Property(x => x.CompletionDigest).HasColumnName("completion_digest").HasMaxLength(64).IsRequired();
        builder.Property(x => x.AcceptedAtUtc).HasColumnName("accepted_at_utc");

        builder.HasOne<VisionJob>().WithMany().HasForeignKey(x => x.JobId).OnDelete(DeleteBehavior.Cascade);
    }
}
