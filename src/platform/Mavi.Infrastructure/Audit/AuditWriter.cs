using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Identity;
using Mavi.Domain.Audit;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Audit;

/// <summary>
/// Writes audit entries in the mutation's own database transaction (ADR-010 §4). The entry is inserted
/// with SQL on the request's <see cref="MaviDbContext"/> connection rather than staged on its change
/// tracker, so a mutation that saves several times or clears the tracker cannot drop it.
/// </summary>
public sealed class AuditWriter(MaviDbContext db, ICurrentOperator currentOperator, IAuditCorrelation correlation,
    TimeProvider timeProvider) : IAuditWriter
{
    public async Task<(T Result, AuditEntryReceipt Receipt)> RecordAsync<T>(AuditRecord record,
        Func<CancellationToken, Task<T>> mutation, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(record);
        ArgumentNullException.ThrowIfNull(mutation);
        var actor = currentOperator.Required;
        if (db.Database.CurrentTransaction is not null)
        {
            var joined = await mutation(cancellationToken);
            return (joined, await InsertAsync(record, actor, cancellationToken));
        }

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        var result = await mutation(cancellationToken);
        var receipt = await InsertAsync(record, actor, cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return (result, receipt);
    }

    public Task<AuditEntryReceipt> AppendInTransactionAsync(AuditRecord record, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(record);
        var actor = currentOperator.Required;
        if (db.Database.CurrentTransaction is null)
            throw new InvalidOperationException("An audit entry is written only inside its mutation's transaction.");
        return InsertAsync(record, actor, cancellationToken);
    }

    private async Task<AuditEntryReceipt> InsertAsync(AuditRecord record, OperatorIdentity actor, CancellationToken cancellationToken)
    {
        var recordedAtUtc = timeProvider.GetUtcNow().ToUniversalTime();
        var entry = AuditEntry.Create(Guid.CreateVersion7(recordedAtUtc), actor.OperatorId, actor.DisplayName, actor.IdentitySource,
            record.Action, record.SubjectType, record.SubjectId, recordedAtUtc, AuditPayload.Sha256(record.Payload),
            correlation.CorrelationId);
        await db.Database.ExecuteSqlInterpolatedAsync($"""
            INSERT INTO audit_entries (id, operator_id, operator_display_name, identity_source, action, subject_type, subject_id,
                recorded_at_utc, payload_sha256, correlation_id)
            VALUES ({entry.Id}, {entry.OperatorId}, {entry.OperatorDisplayName}, {entry.IdentitySource}, {entry.Action},
                {entry.SubjectType}, {entry.SubjectId}, {entry.RecordedAtUtc}, {entry.PayloadSha256}, {entry.CorrelationId})
            """, cancellationToken);
        return new AuditEntryReceipt(entry.Id, entry.RecordedAtUtc, entry.OperatorId, entry.IdentitySource);
    }
}
