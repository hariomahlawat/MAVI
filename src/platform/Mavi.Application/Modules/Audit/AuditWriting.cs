using System.Security.Cryptography;
using System.Text.Json;
using Mavi.Domain.Common;

namespace Mavi.Application.Modules.Audit;

/// <summary>
/// What an attributable mutation records (ADR-010 §4). The operator, the time and the correlation id
/// are not part of it: the writer takes them from the server side.
/// </summary>
/// <param name="Action">Dotted verb, for example <c>plates.reanalysis-requested</c>.</param>
/// <param name="SubjectType">The kind of thing acted on, for example <c>video</c>.</param>
/// <param name="SubjectId">Its identity.</param>
/// <param name="Payload">What was submitted; only its hash is stored (<see cref="AuditPayload.Sha256"/>).</param>
public sealed record AuditRecord(string Action, string SubjectType, string SubjectId, object? Payload);

public sealed record AuditEntryReceipt(Guid AuditEntryId, DateTimeOffset RecordedAtUtc, string OperatorId, string IdentitySource);

public interface IAuditWriter
{
    /// <summary>
    /// Runs <paramref name="mutation"/> and writes its audit entry in one database transaction: both commit
    /// or neither does. The mutation may save several times or clear the change tracker; the entry is
    /// inserted directly, not staged on the tracker. When a transaction is already open the mutation and
    /// the entry join it and its owner commits. Only a transaction on the request's scoped database context is
    /// joined; a mutation on another context instance is not covered. The operator is resolved first: without
    /// one the mutation does not run.
    /// </summary>
    Task<(T Result, AuditEntryReceipt Receipt)> RecordAsync<T>(AuditRecord record, Func<CancellationToken, Task<T>> mutation,
        CancellationToken cancellationToken);

    /// <summary>
    /// Inserts the entry inside the transaction the caller has open (for a mutation that manages its own
    /// transaction); refuses when none is open, so an entry can never commit apart from its mutation.
    /// </summary>
    Task<AuditEntryReceipt> AppendInTransactionAsync(AuditRecord record, CancellationToken cancellationToken);
}

/// <summary>The current request's correlation id (the API host's trace identifier).</summary>
public interface IAuditCorrelation
{
    string CorrelationId { get; }
}

public static class AuditPayload
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);

    /// <summary>
    /// SHA-256 of the payload's UTF-8 JSON (System.Text.Json web defaults; <c>null</c> for no payload).
    /// Deterministic for a given payload type and value; not a canonical JSON form.
    /// </summary>
    public static string Sha256(object? payload)
    {
        var bytes = payload is null ? "null"u8.ToArray() : JsonSerializer.SerializeToUtf8Bytes(payload, payload.GetType(), Options);
        return CanonicalSha256.ToHex(SHA256.HashData(bytes));
    }
}

/// <summary>One audit entry as the read surface shows it (ADR-027 §3). The payload is not stored, only its hash.</summary>
public sealed record AuditEntryView(Guid EntryId, string OperatorId, string OperatorDisplayName, string IdentitySource, string Action,
    string SubjectType, string SubjectId, DateTimeOffset RecordedAtUtc, string PayloadSha256, string CorrelationId);

/// <summary>Filters of the audit read surface; every given filter must hold, and an entry matches any of the subjects.</summary>
public sealed record AuditQuery(IReadOnlyList<(string Type, string Id)> Subjects, string? Action, string? OperatorId,
    (DateTimeOffset RecordedAtUtc, Guid EntryId)? Before, int Limit, IReadOnlyList<AuditSubjectSet>? SubjectSets = null);

/// <summary>Every subject of one type among <paramref name="Ids"/>: a scope resolved on the server, with no count limit.</summary>
public sealed record AuditSubjectSet(string Type, IReadOnlyList<string> Ids);

public sealed record AuditPage(IReadOnlyList<AuditEntryView> Items, (DateTimeOffset RecordedAtUtc, Guid EntryId)? Next);

/// <summary>Read-only access to <c>audit_entries</c>, newest first (ADR-027 §3).</summary>
public interface IAuditReader
{
    Task<AuditPage> ReadAsync(AuditQuery query, CancellationToken cancellationToken);
}
