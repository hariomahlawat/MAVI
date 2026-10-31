using Mavi.Domain.Audit;
using Mavi.Domain.Intelligence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// <c>entity_membership_changes</c> (ADR-027 §4). Append-only: migration <c>AddEntityCorrections</c> installs the triggers that
/// refuse UPDATE, DELETE and TRUNCATE. The Track, Entity and candidate are restricting foreign keys, so history cannot vanish
/// under a deletion: a run whose Tracks carry history cannot be deleted (no path deletes runs today).
/// </summary>
public sealed class EntityMembershipChangeConfiguration : IEntityTypeConfiguration<EntityMembershipChange>
{
    public void Configure(EntityTypeBuilder<EntityMembershipChange> builder)
    {
        builder.ToTable("entity_membership_changes", table => table.HasCheckConstraint("ck_entity_membership_changes_cause",
            "(cause = 'CandidateConfirmed' AND change = 'Joined' AND candidate_id IS NOT NULL) OR " +
            "(cause = 'Unlinked' AND change = 'Left' AND candidate_id IS NULL) OR (cause = 'Merged' AND candidate_id IS NULL)"));
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(x => x.Sequence).HasColumnName("sequence").UseIdentityAlwaysColumn();
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.EntityId).HasColumnName("entity_id");
        builder.Property(x => x.Change).HasColumnName("change").HasConversion<string>().HasMaxLength(16);
        builder.Property(x => x.Cause).HasColumnName("cause").HasConversion<string>().HasMaxLength(32);
        builder.Property(x => x.CandidateId).HasColumnName("candidate_id");
        builder.Property(x => x.Note).HasColumnName("note").HasMaxLength(EntityCandidate.MaximumNoteLength);
        EntityHistoryColumns.Actor(builder, x => x.OperatorId, x => x.OperatorDisplayName, x => x.IdentitySource);
        builder.Property(x => x.AtUtc).HasColumnName("at_utc");
        builder.Property(x => x.AuditEntryId).HasColumnName("audit_entry_id");
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<Entity>().WithMany().HasForeignKey(x => x.EntityId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<EntityCandidate>().WithMany().HasForeignKey(x => x.CandidateId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => x.AuditEntryId);
        builder.HasIndex(x => x.Sequence).IsUnique();
        builder.HasIndex(x => new { x.TrackId, x.Sequence }).HasDatabaseName("ix_entity_membership_changes_track_sequence");
        builder.HasIndex(x => new { x.EntityId, x.Sequence }).HasDatabaseName("ix_entity_membership_changes_entity_sequence");
    }
}

/// <summary><c>entity_candidate_decisions</c> (ADR-027 §4): every confirm, dismiss and reopen. Append-only like the above.</summary>
public sealed class EntityCandidateDecisionRecordConfiguration : IEntityTypeConfiguration<EntityCandidateDecisionRecord>
{
    public void Configure(EntityTypeBuilder<EntityCandidateDecisionRecord> builder)
    {
        builder.ToTable("entity_candidate_decisions", table => table.HasCheckConstraint("ck_entity_candidate_decisions_entity",
            "(decision = 'Confirmed') = (entity_id IS NOT NULL)"));
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(x => x.Sequence).HasColumnName("sequence").UseIdentityAlwaysColumn();
        builder.Property(x => x.CandidateId).HasColumnName("candidate_id");
        builder.Property(x => x.Decision).HasColumnName("decision").HasConversion<string>().HasMaxLength(16);
        builder.Property(x => x.EntityId).HasColumnName("entity_id");
        builder.Property(x => x.Note).HasColumnName("note").HasMaxLength(EntityCandidate.MaximumNoteLength);
        EntityHistoryColumns.Actor(builder, x => x.OperatorId, x => x.OperatorDisplayName, x => x.IdentitySource);
        builder.Property(x => x.AtUtc).HasColumnName("at_utc");
        builder.Property(x => x.AuditEntryId).HasColumnName("audit_entry_id");
        builder.HasOne<EntityCandidate>().WithMany().HasForeignKey(x => x.CandidateId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<Entity>().WithMany().HasForeignKey(x => x.EntityId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => x.AuditEntryId);
        builder.HasIndex(x => x.Sequence).IsUnique();
        builder.HasIndex(x => new { x.CandidateId, x.Sequence }).HasDatabaseName("ix_entity_candidate_decisions_candidate_sequence");
    }
}

internal static class EntityHistoryColumns
{
    public static void Actor<T>(EntityTypeBuilder<T> builder, System.Linq.Expressions.Expression<Func<T, string>> operatorId,
        System.Linq.Expressions.Expression<Func<T, string>> displayName, System.Linq.Expressions.Expression<Func<T, string>> identitySource)
        where T : class
    {
        builder.Property(operatorId).HasColumnName("operator_id").HasMaxLength(AuditEntry.OperatorIdMaxLength);
        builder.Property(displayName).HasColumnName("operator_display_name").HasMaxLength(AuditEntry.DisplayNameMaxLength);
        builder.Property(identitySource).HasColumnName("identity_source").HasMaxLength(AuditEntry.IdentitySourceMaxLength);
    }
}
