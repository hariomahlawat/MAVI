using Mavi.Domain.Review;

namespace Mavi.Application.Modules.Review;

/// <summary>Who did something to a case, as recorded (ADR-027 §2).</summary>
public sealed record CaseActorView(string OperatorId, string DisplayName, string IdentitySource, DateTimeOffset AtUtc, Guid AuditEntryId);

public sealed record CaseSummary(Guid CaseId, string Title, string? Purpose, CaseActorView CreatedBy, int ActiveItemCount, int RemovedItemCount,
    int NoteCount, bool? HoldsSubject = null);

/// <summary>
/// One page of the case list, newest first (ADR-027 §2). <paramref name="Subject"/> keeps only the cases holding it as an active
/// item; <paramref name="TitleContains"/> keeps titles containing the text (case-insensitive); <paramref name="Holding"/> marks each
/// case with whether it holds that subject. <paramref name="Before"/> continues after the last case of the previous page.
/// </summary>
public sealed record CaseListQuery((CaseItemKind Kind, Guid Id)? Subject, string? TitleContains, (CaseItemKind Kind, Guid Id)? Holding,
    (DateTimeOffset CreatedAtUtc, Guid CaseId)? Before, int Limit);

public sealed record CaseListPage(IReadOnlyList<CaseSummary> Items, (DateTimeOffset CreatedAtUtc, Guid CaseId)? Next);

/// <summary>
/// What a case item refers to, read now. <see cref="Available"/> is false when the subject no longer exists; it is shown, never
/// dropped. <see cref="EarlierRun"/> marks a Track or event of a run that is no longer the latest of its video (ADR-027 §5).
/// </summary>
public sealed record CaseSubjectView(bool Available, bool EarlierRun, string? ObjectClass, Guid? CameraId, string? CameraName,
    DateTimeOffset? StartUtc, DateTimeOffset? EndUtc, string? ReviewStatus, string? RuleId, string? EntityDisplayCode, Guid? ProcessingRunId,
    Guid? VideoAssetId, long? StartOffsetMs);

public sealed record CaseItemView(Guid ItemId, CaseItemKind Kind, Guid SubjectId, string? Note, CaseActorView AddedBy, CaseActorView? RemovedBy,
    string? RemovalNote, CaseSubjectView Subject);

public sealed record CaseNoteView(Guid NoteId, string Body, CaseActorView Author);

public sealed record CaseDetail(CaseSummary Summary, IReadOnlyList<CaseItemView> Items, IReadOnlyList<CaseNoteView> Notes);

public enum CaseWriteOutcome { Done, CaseNotFound, SubjectNotFound, AlreadyInCase, ItemNotFound, AlreadyRemoved }

public sealed record CaseWriteResult<T>(CaseWriteOutcome Outcome, T? Value) where T : class;

public interface ICaseRepository
{
    Task<CaseSummary> CreateAsync(string title, string? purpose, CancellationToken cancellationToken);

    /// <summary>One keyset page, newest first; every case is reachable through the continuation.</summary>
    Task<CaseListPage> ListAsync(CaseListQuery query, CancellationToken cancellationToken);

    Task<CaseDetail?> GetAsync(Guid caseId, CancellationToken cancellationToken);

    Task<CaseWriteResult<CaseItemView>> AddItemAsync(Guid caseId, CaseItemKind kind, Guid subjectId, string? note,
        CancellationToken cancellationToken);

    Task<CaseWriteResult<CaseItemView>> RemoveItemAsync(Guid caseId, Guid itemId, string? note, CancellationToken cancellationToken);

    Task<CaseWriteResult<CaseNoteView>> AddNoteAsync(Guid caseId, string body, CancellationToken cancellationToken);
}
