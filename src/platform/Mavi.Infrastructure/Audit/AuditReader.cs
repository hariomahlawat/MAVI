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
        if (query.Subjects.Count > 0 || query.SubjectSets is { Count: > 0 })
        {
            // OR over the subjects (equality pairs) and the subject sets (a type and an id array, one parameter each): both are
            // served by the (subject_type, subject_id, recorded_at_utc) index, and a set has no count limit.
            entries = entries.Where(AnySubject(query.Subjects, query.SubjectSets ?? []));
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

    private static Expression<Func<AuditEntry, bool>> AnySubject(IReadOnlyList<(string Type, string Id)> subjects,
        IReadOnlyList<AuditSubjectSet> sets)
    {
        var entry = Expression.Parameter(typeof(AuditEntry), "entry");
        Expression? any = null;
        foreach (var set in sets)
        {
            if (set.Ids.Count == 0) continue;
            var ids = set.Ids.ToList();
            Expression<Func<List<string>>> holder = () => ids;
            var member = Expression.AndAlso(
                Expression.Equal(Expression.Property(entry, nameof(AuditEntry.SubjectType)), Captured(set.Type)),
                Expression.Call(holder.Body, typeof(List<string>).GetMethod(nameof(List<string>.Contains))!,
                    Expression.Property(entry, nameof(AuditEntry.SubjectId))));
            any = any is null ? member : Expression.OrElse(any, member);
        }

        foreach (var (type, id) in subjects)
        {
            // Each pair is a captured value, so it is sent as a parameter, never spliced into SQL.
            var pair = Expression.AndAlso(
                Expression.Equal(Expression.Property(entry, nameof(AuditEntry.SubjectType)), Captured(type)),
                Expression.Equal(Expression.Property(entry, nameof(AuditEntry.SubjectId)), Captured(id)));
            any = any is null ? pair : Expression.OrElse(any, pair);
        }

        // A scope that resolved to nothing matches nothing (never everything).
        return Expression.Lambda<Func<AuditEntry, bool>>(any ?? Expression.Constant(false), entry);
    }

    private static Expression Captured(string value)
    {
        Expression<Func<string>> holder = () => value;
        return holder.Body;
    }
}
