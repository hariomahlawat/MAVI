using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Identity;
using Mavi.Domain.Audit;
using Mavi.Infrastructure.Persistence;

namespace Mavi.Infrastructure.Audit;

/// <summary>
/// Stages audit entries on the request's <see cref="MaviDbContext"/> (ADR-010 §4), so the entry and the
/// mutation it records share one <c>SaveChanges</c> and one transaction.
/// </summary>
public sealed class AuditWriter(MaviDbContext db, ICurrentOperator currentOperator, IAuditCorrelation correlation,
    TimeProvider timeProvider) : IAuditWriter
{
    public AuditEntryReceipt Append(AuditRecord record)
    {
        ArgumentNullException.ThrowIfNull(record);
        var actor = currentOperator.Required;
        var recordedAtUtc = timeProvider.GetUtcNow().ToUniversalTime();
        var entry = AuditEntry.Create(Guid.CreateVersion7(recordedAtUtc), actor.OperatorId, actor.DisplayName, actor.IdentitySource,
            record.Action, record.SubjectType, record.SubjectId, recordedAtUtc, AuditPayload.Sha256(record.Payload),
            correlation.CorrelationId);
        db.AuditEntries.Add(entry);
        return new AuditEntryReceipt(entry.Id, entry.RecordedAtUtc, entry.OperatorId, entry.IdentitySource);
    }

    public async Task<AuditEntryReceipt> AppendAndCommitAsync(AuditRecord record, CancellationToken cancellationToken)
    {
        var receipt = Append(record);
        await db.SaveChangesAsync(cancellationToken);
        return receipt;
    }
}
