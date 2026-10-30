using System.Linq.Expressions;
using Mavi.Application.Modules.Audit;
using Mavi.Domain.Audit;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Audit;

/// <summary>The audit read surface (ADR-027 §3): keyset pages over <c>audit_entries</c>, newest first. It never writes.</summary>
public sealed class AuditReader(MaviDbContext db) : IAuditReader
{
    public async Task<AuditPage> ReadAsync(AuditQuery query, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        var entries = db.AuditEntries.AsNoTracking();
        if (query.Subjects.Count > 0)
        {
            // OR over the subjects, each an equality pair the (subject_type, subject_id, recorded_at_utc) index serves.
            var keys = query.Subjects.Select(subject => subject.Type + "\u001f" + subject.Id).ToList();
            entries = entries.Where(entry => keys.Contains(entry.SubjectType + "\u001f" + entry.SubjectId));
        }

        if (query.Action is { } action) entries = entries.Where(entry => entry.Action == action);
        if (query.OperatorId is { } operatorId) entries = entries.Where(entry => entry.OperatorId == operatorId);
        if (query.Before is { } before)
            entries = entries.Where(entry => entry.RecordedAtUtc < before.RecordedAtUtc ||
                                             (entry.RecordedAtUtc == before.RecordedAtUtc && entry.Id.CompareTo(before.EntryId) < 0));
        var rows = await entries.OrderByDescending(entry => entry.RecordedAtUtc).ThenByDescending(entry => entry.Id)
            .Take(query.Limit + 1).ToListAsync(cancellationToken);
        var items = rows.Take(query.Limit).Select(entry => new AuditEntryView(entry.Id, entry.OperatorId, entry.OperatorDisplayName,
            entry.IdentitySource, entry.Action, entry.SubjectType, entry.SubjectId, entry.RecordedAtUtc, entry.PayloadSha256,
            entry.CorrelationId)).ToList();
        return new AuditPage(items, rows.Count > query.Limit ? (items[^1].RecordedAtUtc, items[^1].EntryId) : null);
    }

    private static Expression<Func<AuditEntry, bool>> AnySubject(IReadOnlyList<(string Type, string Id)> subjects)
    {
        var entry = Expression.Parameter(typeof(AuditEntry), "entry");
        Expression? any = null;
        foreach (var (type, id) in subjects)
        {
            // Each pair is a captured value, so it is sent as a parameter, never spliced into SQL.
            var pair = Expression.AndAlso(
                Expression.Equal(Expression.Property(entry, nameof(AuditEntry.SubjectType)), Captured(type)),
                Expression.Equal(Expression.Property(entry, nameof(AuditEntry.SubjectId)), Captured(id)));
            any = any is null ? pair : Expression.OrElse(any, pair);
        }

        return Expression.Lambda<Func<AuditEntry, bool>>(any ?? Expression.Constant(true), entry);
    }

    private static Expression Captured(string value)
    {
        Expression<Func<string>> holder = () => value;
        return holder.Body;
    }
}
