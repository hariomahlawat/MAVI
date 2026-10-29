using Mavi.Domain.Audit;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// <c>audit_entries</c> (ADR-010 §4). Append-only: migration <c>AddAuditEntries</c> installs the
/// triggers that refuse UPDATE, DELETE and TRUNCATE.
/// </summary>
public sealed class AuditEntryConfiguration : IEntityTypeConfiguration<AuditEntry>
{
    public void Configure(EntityTypeBuilder<AuditEntry> builder)
    {
        builder.ToTable("audit_entries", table =>
        {
            table.HasCheckConstraint("ck_audit_entries_payload_sha256", "payload_sha256 ~ '^[0-9a-f]{64}$'");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(x => x.OperatorId).HasColumnName("operator_id").HasMaxLength(AuditEntry.OperatorIdMaxLength).IsRequired();
        builder.Property(x => x.OperatorDisplayName).HasColumnName("operator_display_name").HasMaxLength(AuditEntry.DisplayNameMaxLength).IsRequired();
        builder.Property(x => x.IdentitySource).HasColumnName("identity_source").HasMaxLength(AuditEntry.IdentitySourceMaxLength).IsRequired();
        builder.Property(x => x.Action).HasColumnName("action").HasMaxLength(AuditEntry.ActionMaxLength).IsRequired();
        builder.Property(x => x.SubjectType).HasColumnName("subject_type").HasMaxLength(AuditEntry.SubjectTypeMaxLength).IsRequired();
        builder.Property(x => x.SubjectId).HasColumnName("subject_id").HasMaxLength(AuditEntry.SubjectIdMaxLength).IsRequired();
        builder.Property(x => x.RecordedAtUtc).HasColumnName("recorded_at_utc").IsRequired();
        builder.Property(x => x.PayloadSha256).HasColumnName("payload_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.CorrelationId).HasColumnName("correlation_id").HasMaxLength(AuditEntry.CorrelationIdMaxLength).IsRequired();
        builder.HasIndex(x => new { x.SubjectType, x.SubjectId, x.RecordedAtUtc }).HasDatabaseName("ix_audit_entries_subject");
        builder.HasIndex(x => x.RecordedAtUtc).HasDatabaseName("ix_audit_entries_recorded_at_utc");
    }
}
