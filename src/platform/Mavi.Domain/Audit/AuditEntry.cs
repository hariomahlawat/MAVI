using Mavi.Domain.Common;

namespace Mavi.Domain.Audit;

/// <summary>
/// One attributable mutation (ADR-010 §4). Immutable once created; the database refuses UPDATE,
/// DELETE and TRUNCATE on its table. The payload itself is not stored: the mutation's own table
/// holds the state, and <see cref="PayloadSha256"/> binds this entry to what was submitted.
/// </summary>
public sealed class AuditEntry
{
    public const int OperatorIdMaxLength = 256;
    public const int DisplayNameMaxLength = 256;
    public const int IdentitySourceMaxLength = 64;
    public const int ActionMaxLength = 128;
    public const int SubjectTypeMaxLength = 64;
    public const int SubjectIdMaxLength = 256;
    public const int CorrelationIdMaxLength = 128;

    private AuditEntry(Guid id, string operatorId, string operatorDisplayName, string identitySource, string action,
        string subjectType, string subjectId, DateTimeOffset recordedAtUtc, string payloadSha256, string correlationId)
    {
        Id = id;
        OperatorId = operatorId;
        OperatorDisplayName = operatorDisplayName;
        IdentitySource = identitySource;
        Action = action;
        SubjectType = subjectType;
        SubjectId = subjectId;
        RecordedAtUtc = recordedAtUtc;
        PayloadSha256 = payloadSha256;
        CorrelationId = correlationId;
    }

    public Guid Id { get; private set; }
    public string OperatorId { get; private set; }
    public string OperatorDisplayName { get; private set; }
    public string IdentitySource { get; private set; }
    public string Action { get; private set; }
    public string SubjectType { get; private set; }
    public string SubjectId { get; private set; }
    public DateTimeOffset RecordedAtUtc { get; private set; }
    public string PayloadSha256 { get; private set; }
    public string CorrelationId { get; private set; }

    public static AuditEntry Create(Guid id, string operatorId, string operatorDisplayName, string identitySource, string action,
        string subjectType, string subjectId, DateTimeOffset recordedAtUtc, string payloadSha256, string correlationId)
    {
        if (id == Guid.Empty)
            throw new ArgumentException("An audit entry needs an id.", nameof(id));
        if (recordedAtUtc.Offset != TimeSpan.Zero)
            throw new ArgumentException("An audit entry's time is a UTC instant.", nameof(recordedAtUtc));
        if (!CanonicalSha256.IsCanonical(payloadSha256))
            throw new ArgumentException("The payload hash must be a canonical SHA-256.", nameof(payloadSha256));
        return new AuditEntry(id,
            Required(operatorId, OperatorIdMaxLength, nameof(operatorId)),
            Required(operatorDisplayName, DisplayNameMaxLength, nameof(operatorDisplayName)),
            Required(identitySource, IdentitySourceMaxLength, nameof(identitySource)),
            Required(action, ActionMaxLength, nameof(action)),
            Required(subjectType, SubjectTypeMaxLength, nameof(subjectType)),
            Required(subjectId, SubjectIdMaxLength, nameof(subjectId)),
            recordedAtUtc,
            payloadSha256,
            Required(correlationId, CorrelationIdMaxLength, nameof(correlationId)));
    }

    private static string Required(string value, int maxLength, string name)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new ArgumentException($"An audit entry needs {name}.", name);
        if (value.Length > maxLength)
            throw new ArgumentException($"{name} is longer than {maxLength} characters.", name);
        return value;
    }
}
