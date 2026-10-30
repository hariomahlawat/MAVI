using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Identity;
using Mavi.Application.Modules.Review;
using Mavi.Domain.Processing;
using Mavi.Domain.Review;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// Cases (ADR-027 §2). Every write opens one transaction, locks the case row <c>FOR NO KEY UPDATE</c> (so writes to one
/// case are serialised), checks under the lock, appends the audit row and writes the change; a refusal writes nothing.
/// Subjects are checked to exist when added and resolved again on every read; nothing here touches identity, Entity
/// membership or review status.
/// </summary>
public sealed class CaseRepository(MaviDbContext db, IAuditWriter audit, ICurrentOperator currentOperator) : ICaseRepository
{
    public const string SubjectType = "case";

    public async Task<CaseSummary> CreateAsync(string title, string? purpose, CancellationToken cancellationToken)
    {
        // Validate before anything is written; the domain repeats it with the recorded actor.
        var cleanTitle = Text.Required(title, InvestigationCase.TitleMaxLength, "case_title_invalid", "title");
        var cleanPurpose = Text.Optional(purpose, InvestigationCase.PurposeMaxLength, "case_purpose_too_long", "purpose");
        var id = Guid.CreateVersion7();
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        var actor = await AppendAsync("cases.created", id, new { caseId = id, title = cleanTitle, purpose = cleanPurpose }, cancellationToken);
        var created = InvestigationCase.Create(id, cleanTitle, cleanPurpose, actor);
        db.Cases.Add(created);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new CaseSummary(created.Id, created.Title, created.Purpose, View(actor), 0, 0, 0);
    }

    public async Task<IReadOnlyList<CaseSummary>> ListAsync(CaseItemKind? subjectKind, Guid? subjectId, int limit,
        CancellationToken cancellationToken)
    {
        var cases = db.Cases.AsNoTracking();
        if (subjectKind is { } kind && subjectId is { } subject)
            cases = cases.Where(c => db.CaseItems.Any(item => item.CaseId == c.Id && item.Kind == kind && item.SubjectId == subject &&
                                                              item.RemovedAtUtc == null));
        var rows = await cases
            .OrderByDescending(c => c.CreatedAtUtc).ThenByDescending(c => c.Id)
            .Take(limit)
            .Select(c => new
            {
                InvestigationCase = c,
                Active = db.CaseItems.Count(item => item.CaseId == c.Id && item.RemovedAtUtc == null),
                Removed = db.CaseItems.Count(item => item.CaseId == c.Id && item.RemovedAtUtc != null),
                Notes = db.CaseNotes.Count(note => note.CaseId == c.Id),
            })
            .ToListAsync(cancellationToken);
        return rows.Select(row => Summary(row.InvestigationCase, row.Active, row.Removed, row.Notes)).ToList();
    }

    public async Task<CaseDetail?> GetAsync(Guid caseId, CancellationToken cancellationToken)
    {
        var found = await db.Cases.AsNoTracking().SingleOrDefaultAsync(c => c.Id == caseId, cancellationToken);
        if (found is null) return null;
        var items = await db.CaseItems.AsNoTracking().Where(item => item.CaseId == caseId)
            .OrderBy(item => item.AddedAtUtc).ThenBy(item => item.Id).ToListAsync(cancellationToken);
        var notes = await db.CaseNotes.AsNoTracking().Where(note => note.CaseId == caseId)
            .OrderBy(note => note.CreatedAtUtc).ThenBy(note => note.Id).ToListAsync(cancellationToken);
        var subjects = await ResolveAsync(items.Select(item => (item.Kind, item.SubjectId)).ToList(), cancellationToken);
        return new CaseDetail(
            Summary(found, items.Count(item => item.RemovedAtUtc is null), items.Count(item => item.RemovedAtUtc is not null), notes.Count),
            items.Select(item => ItemView(item, subjects[(item.Kind, item.SubjectId)])).ToList(),
            notes.Select(note => new CaseNoteView(note.Id, note.Body,
                new CaseActorView(note.AuthorOperatorId, note.AuthorDisplayName, note.AuthorIdentitySource, note.CreatedAtUtc, note.AuditEntryId)))
                .ToList());
    }

    public async Task<CaseWriteResult<CaseItemView>> AddItemAsync(Guid caseId, CaseItemKind kind, Guid subjectId, string? note,
        CancellationToken cancellationToken)
    {
        var cleanNote = Text.Optional(note, CaseItem.NoteMaxLength, "case_note_too_long", "note");
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        if (!await LockCaseAsync(caseId, cancellationToken)) return new(CaseWriteOutcome.CaseNotFound, null);
        if (!await SubjectExistsAsync(kind, subjectId, cancellationToken)) return new(CaseWriteOutcome.SubjectNotFound, null);
        if (await db.CaseItems.AnyAsync(item => item.CaseId == caseId && item.Kind == kind && item.SubjectId == subjectId &&
                                                 item.RemovedAtUtc == null, cancellationToken))
            return new(CaseWriteOutcome.AlreadyInCase, null);

        var itemId = Guid.CreateVersion7();
        var actor = await AppendAsync("cases.item-added", caseId,
            new { caseId, itemId, kind = kind.ToString(), subjectId, note = cleanNote }, cancellationToken);
        var item = CaseItem.Add(itemId, caseId, kind, subjectId, cleanNote, actor);
        db.CaseItems.Add(item);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        var subjects = await ResolveAsync([(kind, subjectId)], cancellationToken);
        return new(CaseWriteOutcome.Done, ItemView(item, subjects[(kind, subjectId)]));
    }

    public async Task<CaseWriteResult<CaseItemView>> RemoveItemAsync(Guid caseId, Guid itemId, string? note, CancellationToken cancellationToken)
    {
        var cleanNote = Text.Optional(note, CaseItem.NoteMaxLength, "case_note_too_long", "note");
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        if (!await LockCaseAsync(caseId, cancellationToken)) return new(CaseWriteOutcome.CaseNotFound, null);
        var item = await db.CaseItems.SingleOrDefaultAsync(x => x.Id == itemId && x.CaseId == caseId, cancellationToken);
        if (item is null) return new(CaseWriteOutcome.ItemNotFound, null);
        if (item.RemovedAtUtc is not null) return new(CaseWriteOutcome.AlreadyRemoved, null);

        var actor = await AppendAsync("cases.item-removed", caseId, new { caseId, itemId, note = cleanNote }, cancellationToken);
        item.Remove(cleanNote, actor);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        var subjects = await ResolveAsync([(item.Kind, item.SubjectId)], cancellationToken);
        return new(CaseWriteOutcome.Done, ItemView(item, subjects[(item.Kind, item.SubjectId)]));
    }

    public async Task<CaseWriteResult<CaseNoteView>> AddNoteAsync(Guid caseId, string body, CancellationToken cancellationToken)
    {
        var cleanBody = Text.Required(body, CaseNote.BodyMaxLength, "case_note_invalid", "body");
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        if (!await LockCaseAsync(caseId, cancellationToken)) return new(CaseWriteOutcome.CaseNotFound, null);
        var noteId = Guid.CreateVersion7();
        var actor = await AppendAsync("cases.note-added", caseId, new { caseId, noteId, body = cleanBody }, cancellationToken);
        var note = CaseNote.Add(noteId, caseId, cleanBody, actor);
        db.CaseNotes.Add(note);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new(CaseWriteOutcome.Done, new CaseNoteView(note.Id, note.Body, View(actor)));
    }

    // --- Helpers ---------------------------------------------------------------------------------

    private async Task<CaseActor> AppendAsync(string action, Guid caseId, object payload, CancellationToken cancellationToken)
    {
        var receipt = await audit.AppendInTransactionAsync(new AuditRecord(action, SubjectType, caseId.ToString("D"), payload), cancellationToken);
        var actor = currentOperator.Required;
        return new CaseActor(actor.OperatorId, actor.DisplayName, actor.IdentitySource, receipt.RecordedAtUtc, receipt.AuditEntryId);
    }

    private async Task<bool> LockCaseAsync(Guid caseId, CancellationToken cancellationToken)
    {
        var locked = await db.Database
            .SqlQuery<Guid>($"SELECT id AS \"Value\" FROM cases WHERE id = {caseId} FOR NO KEY UPDATE")
            .ToListAsync(cancellationToken);
        return locked.Count == 1;
    }

    private Task<bool> SubjectExistsAsync(CaseItemKind kind, Guid subjectId, CancellationToken cancellationToken) => kind switch
    {
        CaseItemKind.Track => db.Tracks.AnyAsync(x => x.Id == subjectId, cancellationToken),
        CaseItemKind.AnalyticEvent => db.AnalyticEvents.AnyAsync(x => x.Id == subjectId, cancellationToken),
        CaseItemKind.Entity => db.Entities.AnyAsync(x => x.Id == subjectId, cancellationToken),
        _ => Task.FromResult(false),
    };

    /// <summary>Reads every referenced subject now; one that no longer exists is unavailable, never dropped.</summary>
    private async Task<Dictionary<(CaseItemKind, Guid), CaseSubjectView>> ResolveAsync(IReadOnlyList<(CaseItemKind Kind, Guid Id)> references,
        CancellationToken cancellationToken)
    {
        var result = new Dictionary<(CaseItemKind, Guid), CaseSubjectView>();
        var trackIds = references.Where(r => r.Kind == CaseItemKind.Track).Select(r => r.Id).Distinct().ToList();
        var eventIds = references.Where(r => r.Kind == CaseItemKind.AnalyticEvent).Select(r => r.Id).Distinct().ToList();
        var entityIds = references.Where(r => r.Kind == CaseItemKind.Entity).Select(r => r.Id).Distinct().ToList();

        // The latest completed run per video is the visible one (the default search's base set); anything else is an earlier run.
        var latestRuns = db.ProcessingRuns.AsNoTracking()
            .Where(run => run.Status == ProcessingRunStatus.Completed &&
                          !db.ProcessingRuns.Any(later => later.VideoAssetId == run.VideoAssetId && later.Status == ProcessingRunStatus.Completed &&
                                                          later.VisibilitySequence > run.VisibilitySequence))
            .Select(run => run.Id);

        if (trackIds.Count > 0)
        {
            var tracks = await (from track in db.Tracks.AsNoTracking()
                                join video in db.VideoAssets.AsNoTracking() on track.VideoAssetId equals video.Id
                                join camera in db.Cameras.AsNoTracking() on video.CameraId equals camera.Id
                                where trackIds.Contains(track.Id)
                                select new
                                {
                                    track.Id, track.ObjectClass, camera.Name, CameraId = camera.Id, track.StartTimestampUtc, track.EndTimestampUtc,
                                    track.ReviewStatus, track.ProcessingRunId, track.VideoAssetId, track.StartOffsetMs,
                                    Latest = latestRuns.Contains(track.ProcessingRunId),
                                }).ToListAsync(cancellationToken);
            foreach (var t in tracks)
                result[(CaseItemKind.Track, t.Id)] = new CaseSubjectView(true, !t.Latest, t.ObjectClass.ToString(), t.CameraId, t.Name,
                    t.StartTimestampUtc, t.EndTimestampUtc, t.ReviewStatus.ToString(), null, null, t.ProcessingRunId, t.VideoAssetId, t.StartOffsetMs);
        }

        if (eventIds.Count > 0)
        {
            var events = await (from analyticEvent in db.AnalyticEvents.AsNoTracking()
                                join camera in db.Cameras.AsNoTracking() on analyticEvent.CameraId equals camera.Id
                                where eventIds.Contains(analyticEvent.Id)
                                select new
                                {
                                    analyticEvent.Id, analyticEvent.ObjectClass, camera.Name, CameraId = camera.Id, analyticEvent.StartUtc,
                                    analyticEvent.EndUtc, analyticEvent.RuleId, analyticEvent.ProcessingRunId, analyticEvent.VideoAssetId,
                                    analyticEvent.StartOffsetMs, Latest = latestRuns.Contains(analyticEvent.ProcessingRunId),
                                }).ToListAsync(cancellationToken);
            foreach (var e in events)
                result[(CaseItemKind.AnalyticEvent, e.Id)] = new CaseSubjectView(true, !e.Latest, e.ObjectClass, e.CameraId, e.Name, e.StartUtc,
                    e.EndUtc, null, e.RuleId, null, e.ProcessingRunId, e.VideoAssetId, e.StartOffsetMs);
        }

        if (entityIds.Count > 0)
        {
            var entities = await db.Entities.AsNoTracking().Where(x => entityIds.Contains(x.Id))
                .Select(x => new { x.Id, x.EntityType, x.DisplayCode }).ToListAsync(cancellationToken);
            foreach (var e in entities)
                result[(CaseItemKind.Entity, e.Id)] = new CaseSubjectView(true, false, e.EntityType.ToString(), null, null, null, null, null, null,
                    e.DisplayCode, null, null, null);
        }

        foreach (var reference in references)
            result.TryAdd(reference, new CaseSubjectView(false, false, null, null, null, null, null, null, null, null, null, null, null));
        return result;
    }

    private static CaseSummary Summary(InvestigationCase c, int active, int removed, int notes) => new(c.Id, c.Title, c.Purpose,
        new CaseActorView(c.CreatedByOperatorId, c.CreatedByDisplayName, c.CreatedByIdentitySource, c.CreatedAtUtc, c.AuditEntryId),
        active, removed, notes);

    private static CaseItemView ItemView(CaseItem item, CaseSubjectView subject) => new(item.Id, item.Kind, item.SubjectId, item.Note,
        new CaseActorView(item.AddedByOperatorId, item.AddedByDisplayName, item.AddedByIdentitySource, item.AddedAtUtc, item.AddedAuditEntryId),
        item.RemovedAtUtc is { } removedAt
            ? new CaseActorView(item.RemovedByOperatorId!, item.RemovedByDisplayName!, item.RemovedByIdentitySource!, removedAt,
                item.RemovedAuditEntryId!.Value)
            : null,
        item.RemovalNote, subject);

    private static CaseActorView View(CaseActor actor) =>
        new(actor.OperatorId, actor.DisplayName, actor.IdentitySource, actor.AtUtc, actor.AuditEntryId);
}
