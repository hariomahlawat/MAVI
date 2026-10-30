using Mavi.Domain.Audit;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Review;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// <c>track_review_decisions</c> (ADR-027 §1). Append-only: migration <c>AddReviewAndCases</c> installs the triggers that
/// refuse UPDATE, DELETE and TRUNCATE. The Track is a restricting foreign key, so a decision's Track cannot vanish under it.
/// </summary>
public sealed class TrackReviewDecisionConfiguration : IEntityTypeConfiguration<TrackReviewDecision>
{
    public void Configure(EntityTypeBuilder<TrackReviewDecision> builder)
    {
        builder.ToTable("track_review_decisions", table =>
        {
            table.HasCheckConstraint("ck_track_review_decisions_request_sha256", "request_sha256 ~ '^[0-9a-f]{64}$'");
            table.HasCheckConstraint("ck_track_review_decisions_result",
                "(decision = 'Confirmed' AND resulting_status = 'Confirmed') OR (decision = 'Rejected' AND resulting_status = 'Rejected') " +
                "OR (decision = 'Cleared' AND resulting_status = 'Unreviewed' AND previous_status <> 'Unreviewed')");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id").ValueGeneratedNever();
        builder.Property(x => x.Sequence).HasColumnName("sequence").UseIdentityAlwaysColumn();
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.Decision).HasColumnName("decision").HasConversion<string>().HasMaxLength(16);
        builder.Property(x => x.PreviousStatus).HasColumnName("previous_status").HasConversion<string>().HasMaxLength(32);
        builder.Property(x => x.ResultingStatus).HasColumnName("resulting_status").HasConversion<string>().HasMaxLength(32);
        builder.Property(x => x.Note).HasColumnName("note").HasMaxLength(TrackReviewDecision.NoteMaxLength);
        builder.Property(x => x.OperatorId).HasColumnName("operator_id").HasMaxLength(AuditEntry.OperatorIdMaxLength);
        builder.Property(x => x.OperatorDisplayName).HasColumnName("operator_display_name").HasMaxLength(AuditEntry.DisplayNameMaxLength);
        builder.Property(x => x.IdentitySource).HasColumnName("identity_source").HasMaxLength(AuditEntry.IdentitySourceMaxLength);
        builder.Property(x => x.DecidedAtUtc).HasColumnName("decided_at_utc");
        builder.Property(x => x.RequestSha256).HasColumnName("request_sha256").HasMaxLength(64).IsFixedLength();
        builder.Property(x => x.AuditEntryId).HasColumnName("audit_entry_id");
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => x.Sequence).IsUnique();
        builder.HasIndex(x => new { x.TrackId, x.Sequence }).HasDatabaseName("ix_track_review_decisions_track_sequence");
        builder.HasIndex(x => x.AuditEntryId).IsUnique();
    }
}
