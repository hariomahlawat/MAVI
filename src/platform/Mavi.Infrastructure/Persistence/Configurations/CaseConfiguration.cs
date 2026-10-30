using Mavi.Domain.Audit;
using Mavi.Domain.Review;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// <c>cases</c>, <c>case_items</c> and <c>case_notes</c> (ADR-027 §2). Migration <c>AddReviewAndCases</c> installs the
/// guards: cases and notes refuse UPDATE, DELETE and TRUNCATE; items refuse DELETE and TRUNCATE and every UPDATE except
/// the one removal transition. An item's subject is a kind and an id with no foreign key.
/// </summary>
public sealed class CaseConfiguration : IEntityTypeConfiguration<InvestigationCase>
{
    public void Configure(EntityTypeBuilder<InvestigationCase> builder)
    {
        builder.ToTable("cases");
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(x => x.Title).HasColumnName("title").HasMaxLength(InvestigationCase.TitleMaxLength);
        builder.Property(x => x.Purpose).HasColumnName("purpose").HasMaxLength(InvestigationCase.PurposeMaxLength);
        CaseColumns.Actor(builder, "created_by", x => x.CreatedByOperatorId, x => x.CreatedByDisplayName, x => x.CreatedByIdentitySource);
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.Property(x => x.AuditEntryId).HasColumnName("audit_entry_id");
        builder.HasOne<AuditEntry>().WithMany().HasForeignKey(x => x.AuditEntryId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => x.CreatedAtUtc);
    }
}

public sealed class CaseItemConfiguration : IEntityTypeConfiguration<CaseItem>
{
    public void Configure(EntityTypeBuilder<CaseItem> builder)
    {
        builder.ToTable("case_items", table => table.HasCheckConstraint("ck_case_items_removal",
            "(removed_at_utc IS NULL AND removed_by_operator_id IS NULL AND removed_by_display_name IS NULL AND " +
            "removed_by_identity_source IS NULL AND removed_audit_entry_id IS NULL AND removal_note IS NULL) OR " +
            "(removed_at_utc IS NOT NULL AND removed_by_operator_id IS NOT NULL AND removed_by_display_name IS NOT NULL AND " +
            "removed_by_identity_source IS NOT NULL AND removed_audit_entry_id IS NOT NULL)"));
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(x => x.CaseId).HasColumnName("case_id");
        builder.Property(x => x.Kind).HasColumnName("kind").HasConversion<string>().HasMaxLength(32);
        builder.Property(x => x.SubjectId).HasColumnName("subject_id");
        builder.Property(x => x.Note).HasColumnName("note").HasMaxLength(CaseItem.NoteMaxLength);
        CaseColumns.Actor(builder, "added_by", x => x.AddedByOperatorId, x => x.AddedByDisplayName, x => x.AddedByIdentitySource);
        builder.Property(x => x.AddedAtUtc).HasColumnName("added_at_utc");
        builder.Property(x => x.AddedAuditEntryId).HasColumnName("added_audit_entry_id");
        builder.Property(x => x.RemovalNote).HasColumnName("removal_note").HasMaxLength(CaseItem.NoteMaxLength);
        builder.Property(x => x.RemovedByOperatorId).HasColumnName("removed_by_operator_id").HasMaxLength(AuditEntry.OperatorIdMaxLength);
        builder.Property(x => x.RemovedByDisplayName).HasColumnName("removed_by_display_name").HasMaxLength(AuditEntry.DisplayNameMaxLength);
        builder.Property(x => x.RemovedByIdentitySource).HasColumnName("removed_by_identity_source").HasMaxLength(AuditEntry.IdentitySourceMaxLength);
        builder.Property(x => x.RemovedAtUtc).HasColumnName("removed_at_utc");
        builder.Property(x => x.RemovedAuditEntryId).HasColumnName("removed_audit_entry_id");
        builder.HasOne<InvestigationCase>().WithMany().HasForeignKey(x => x.CaseId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<AuditEntry>().WithMany().HasForeignKey(x => x.AddedAuditEntryId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<AuditEntry>().WithMany().HasForeignKey(x => x.RemovedAuditEntryId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => new { x.CaseId, x.Kind, x.SubjectId }).IsUnique().HasFilter("removed_at_utc IS NULL")
            .HasDatabaseName("ux_case_items_active_subject");
        builder.HasIndex(x => new { x.Kind, x.SubjectId }).HasDatabaseName("ix_case_items_subject");
        builder.HasIndex(x => new { x.CaseId, x.AddedAtUtc });
    }
}

public sealed class CaseNoteConfiguration : IEntityTypeConfiguration<CaseNote>
{
    public void Configure(EntityTypeBuilder<CaseNote> builder)
    {
        builder.ToTable("case_notes");
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(x => x.CaseId).HasColumnName("case_id");
        builder.Property(x => x.Body).HasColumnName("body").HasMaxLength(CaseNote.BodyMaxLength);
        CaseColumns.Actor(builder, "author", x => x.AuthorOperatorId, x => x.AuthorDisplayName, x => x.AuthorIdentitySource);
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.Property(x => x.AuditEntryId).HasColumnName("audit_entry_id");
        builder.HasOne<InvestigationCase>().WithMany().HasForeignKey(x => x.CaseId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<AuditEntry>().WithMany().HasForeignKey(x => x.AuditEntryId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => new { x.CaseId, x.CreatedAtUtc });
    }
}

internal static class CaseColumns
{
    public static void Actor<T>(EntityTypeBuilder<T> builder, string prefix, System.Linq.Expressions.Expression<Func<T, string>> operatorId,
        System.Linq.Expressions.Expression<Func<T, string>> displayName, System.Linq.Expressions.Expression<Func<T, string>> identitySource)
        where T : class
    {
        builder.Property(operatorId).HasColumnName($"{prefix}_operator_id").HasMaxLength(AuditEntry.OperatorIdMaxLength);
        builder.Property(displayName).HasColumnName($"{prefix}_display_name").HasMaxLength(AuditEntry.DisplayNameMaxLength);
        builder.Property(identitySource).HasColumnName($"{prefix}_identity_source").HasMaxLength(AuditEntry.IdentitySourceMaxLength);
    }
}
