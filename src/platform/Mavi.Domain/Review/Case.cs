using Mavi.Domain.Common;

namespace Mavi.Domain.Review;

/// <summary>What a case item refers to (ADR-027 §2). The reference is a kind and an id, never a copy and never a foreign key.</summary>
public enum CaseItemKind { Track, AnalyticEvent, Entity }

/// <summary>Who did something and when, from the server (ADR-010 §2, §5).</summary>
public sealed record CaseActor(string OperatorId, string DisplayName, string IdentitySource, DateTimeOffset AtUtc, Guid AuditEntryId)
{
    internal void Validate()
    {
        if (string.IsNullOrWhiteSpace(OperatorId) || string.IsNullOrWhiteSpace(DisplayName) || string.IsNullOrWhiteSpace(IdentitySource) ||
            AtUtc.Offset != TimeSpan.Zero || AuditEntryId == Guid.Empty)
            throw new DomainValidationException("case_actor_invalid", "The case action has no valid operator, time or audit entry.");
    }
}

/// <summary>
/// A named container for investigation (ADR-027 §2; review plan §2.7). It asserts nothing about what its items show:
/// items in one case are not asserted to show the same person or vehicle. Append-only: the database refuses changes.
/// </summary>
public sealed class InvestigationCase
{
    public const int TitleMaxLength = 200;
    public const int PurposeMaxLength = 2000;

    public const string Statement =
        "A case collects evidence for investigation. Items in one case are not asserted to show the same person or vehicle.";

    private InvestigationCase() { }

    public static InvestigationCase Create(Guid id, string? title, string? purpose, CaseActor createdBy)
    {
        ArgumentNullException.ThrowIfNull(createdBy);
        createdBy.Validate();
        if (id == Guid.Empty) throw new DomainValidationException("case_invalid", "The case needs an id.");
        return new InvestigationCase
        {
            Id = id,
            Title = Text.Required(title, TitleMaxLength, "case_title_invalid", "title"),
            Purpose = Text.Optional(purpose, PurposeMaxLength, "case_purpose_too_long", "purpose"),
            CreatedByOperatorId = createdBy.OperatorId,
            CreatedByDisplayName = createdBy.DisplayName,
            CreatedByIdentitySource = createdBy.IdentitySource,
            CreatedAtUtc = createdBy.AtUtc,
            AuditEntryId = createdBy.AuditEntryId,
        };
    }

    public Guid Id { get; private set; }
    public string Title { get; private set; } = string.Empty;
    public string? Purpose { get; private set; }
    public string CreatedByOperatorId { get; private set; } = string.Empty;
    public string CreatedByDisplayName { get; private set; } = string.Empty;
    public string CreatedByIdentitySource { get; private set; } = string.Empty;
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public Guid AuditEntryId { get; private set; }
}

/// <summary>
/// A Track, analytic event or Entity collected into a case, with an operator note (ADR-027 §2). Removal is a recorded state
/// change: the removal fields are set once and the row stays; the database refuses every other change.
/// </summary>
public sealed class CaseItem
{
    public const int NoteMaxLength = 1000;

    private CaseItem() { }

    public static CaseItem Add(Guid id, Guid caseId, CaseItemKind kind, Guid subjectId, string? note, CaseActor addedBy)
    {
        ArgumentNullException.ThrowIfNull(addedBy);
        addedBy.Validate();
        if (id == Guid.Empty || caseId == Guid.Empty || subjectId == Guid.Empty || !Enum.IsDefined(kind))
            throw new DomainValidationException("case_item_invalid", "The case item is invalid.");
        return new CaseItem
        {
            Id = id,
            CaseId = caseId,
            Kind = kind,
            SubjectId = subjectId,
            Note = Text.Optional(note, NoteMaxLength, "case_note_too_long", "note"),
            AddedByOperatorId = addedBy.OperatorId,
            AddedByDisplayName = addedBy.DisplayName,
            AddedByIdentitySource = addedBy.IdentitySource,
            AddedAtUtc = addedBy.AtUtc,
            AddedAuditEntryId = addedBy.AuditEntryId,
        };
    }

    /// <summary>Records the removal once; a removed item is never restored (adding the subject again is a new item).</summary>
    public void Remove(string? note, CaseActor removedBy)
    {
        ArgumentNullException.ThrowIfNull(removedBy);
        removedBy.Validate();
        if (RemovedAtUtc is not null)
            throw new DomainValidationException("case_item_already_removed", "The item was already removed from the case.");
        RemovalNote = Text.Optional(note, NoteMaxLength, "case_note_too_long", "note");
        RemovedByOperatorId = removedBy.OperatorId;
        RemovedByDisplayName = removedBy.DisplayName;
        RemovedByIdentitySource = removedBy.IdentitySource;
        RemovedAtUtc = removedBy.AtUtc;
        RemovedAuditEntryId = removedBy.AuditEntryId;
    }

    public Guid Id { get; private set; }
    public Guid CaseId { get; private set; }
    public CaseItemKind Kind { get; private set; }
    public Guid SubjectId { get; private set; }
    public string? Note { get; private set; }
    public string AddedByOperatorId { get; private set; } = string.Empty;
    public string AddedByDisplayName { get; private set; } = string.Empty;
    public string AddedByIdentitySource { get; private set; } = string.Empty;
    public DateTimeOffset AddedAtUtc { get; private set; }
    public Guid AddedAuditEntryId { get; private set; }
    public string? RemovalNote { get; private set; }
    public string? RemovedByOperatorId { get; private set; }
    public string? RemovedByDisplayName { get; private set; }
    public string? RemovedByIdentitySource { get; private set; }
    public DateTimeOffset? RemovedAtUtc { get; private set; }
    public Guid? RemovedAuditEntryId { get; private set; }
}

/// <summary>An operator's note on a case (ADR-027 §2). Append-only.</summary>
public sealed class CaseNote
{
    public const int BodyMaxLength = 4000;

    private CaseNote() { }

    public static CaseNote Add(Guid id, Guid caseId, string? body, CaseActor author)
    {
        ArgumentNullException.ThrowIfNull(author);
        author.Validate();
        if (id == Guid.Empty || caseId == Guid.Empty) throw new DomainValidationException("case_note_invalid", "The case note is invalid.");
        return new CaseNote
        {
            Id = id,
            CaseId = caseId,
            Body = Text.Required(body, BodyMaxLength, "case_note_invalid", "body"),
            AuthorOperatorId = author.OperatorId,
            AuthorDisplayName = author.DisplayName,
            AuthorIdentitySource = author.IdentitySource,
            CreatedAtUtc = author.AtUtc,
            AuditEntryId = author.AuditEntryId,
        };
    }

    public Guid Id { get; private set; }
    public Guid CaseId { get; private set; }
    public string Body { get; private set; } = string.Empty;
    public string AuthorOperatorId { get; private set; } = string.Empty;
    public string AuthorDisplayName { get; private set; } = string.Empty;
    public string AuthorIdentitySource { get; private set; } = string.Empty;
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public Guid AuditEntryId { get; private set; }
}

/// <summary>Operator free text: trimmed, blank is absent, bounded.</summary>
public static class Text
{
    public static string Required(string? value, int maxLength, string code, string name) =>
        Optional(value, maxLength, code, name) ?? throw new DomainValidationException(code, $"{name} is required.");

    public static string? Optional(string? value, int maxLength, string code, string name)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        var trimmed = value.Trim();
        if (trimmed.Length > maxLength)
            throw new DomainValidationException(code, $"{name} is longer than {maxLength} characters.");
        return trimmed;
    }
}
