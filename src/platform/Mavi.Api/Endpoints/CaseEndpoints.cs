using System.Globalization;
using Mavi.Api.Identity;
using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Review;
using Mavi.Domain.Common;
using Mavi.Domain.Review;

namespace Mavi.Api.Endpoints;

/// <summary>
/// Cases (PoC S11-full; ADR-027 §2). Every route requires <see cref="OperatorPolicy"/>; writes are JSON and each writes one
/// audit row (subject: the case) in its transaction. A case collects evidence for investigation and asserts nothing about
/// what its items show; removing an item is recorded, never deleted.
/// </summary>
public static class CaseEndpoints
{
    public const string InvalidCode = "case_invalid";
    public const int DefaultLimit = 50;
    public const int MaximumLimit = 200;

    public static IEndpointRouteBuilder MapCaseEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        var cases = endpoints.MapGroup("/api/cases").RequireAuthorization(OperatorPolicy.Name);
        cases.MapPost("", CreateAsync);
        cases.MapGet("", ListAsync);
        cases.MapGet("/{id:guid}", GetAsync);
        cases.MapPost("/{id:guid}/items", AddItemAsync);
        cases.MapPost("/{id:guid}/items/{itemId:guid}/remove", RemoveItemAsync);
        cases.MapPost("/{id:guid}/notes", AddNoteAsync);
        return endpoints;
    }

    public sealed record CreateRequest(string? Title, string? Purpose);

    public sealed record AddItemRequest(string? Kind, Guid? SubjectId, string? Note);

    public sealed record RemoveItemRequest(string? Note);

    public sealed record AddNoteRequest(string? Body);

    public sealed record ActorResponse(string OperatorId, string DisplayName, string IdentitySource, DateTimeOffset AtUtc, Guid AuditEntryId);

    public sealed record SummaryResponse(Guid CaseId, string Title, string? Purpose, ActorResponse CreatedBy, int ActiveItemCount,
        int RemovedItemCount, int NoteCount);

    public sealed record SubjectResponse(bool Available, bool EarlierRun, string? ObjectClass, Guid? CameraId, string? CameraName,
        DateTimeOffset? StartUtc, DateTimeOffset? EndUtc, string? ReviewStatus, string? RuleId, string? EntityDisplayCode, Guid? ProcessingRunId,
        Guid? VideoAssetId, long? StartOffsetMs);

    public sealed record ItemResponse(Guid ItemId, string Kind, Guid SubjectId, string? Note, ActorResponse AddedBy, ActorResponse? RemovedBy,
        string? RemovalNote, SubjectResponse Subject);

    public sealed record NoteResponse(Guid NoteId, string Body, ActorResponse Author);

    public sealed record ListResponse(string Statement, IReadOnlyList<SummaryResponse> Cases);

    public sealed record DetailResponse(string Statement, SummaryResponse Case, IReadOnlyList<ItemResponse> Items, IReadOnlyList<NoteResponse> Notes);

    private static async Task<IResult> CreateAsync(CreateRequest request, ICaseRepository repository, CancellationToken cancellationToken) =>
        await Validated(async () =>
        {
            var created = await repository.CreateAsync(request.Title ?? string.Empty, request.Purpose, cancellationToken);
            return Results.Created($"/api/cases/{created.CaseId}", Summary(created));
        });

    private static async Task<IResult> ListAsync(HttpRequest http, ICaseRepository repository, CancellationToken cancellationToken)
    {
        var query = http.Query;
        if (query.Keys.Any(key => key is not ("subjectKind" or "subjectId" or "limit")) || query.Any(pair => pair.Value.Count != 1))
            return Problem(400, InvalidCode, "Unknown or repeated query key.");
        var limit = DefaultLimit;
        if (query.TryGetValue("limit", out var limitValue) &&
            (!int.TryParse(limitValue, NumberStyles.None, CultureInfo.InvariantCulture, out limit) || limit is < 1 or > MaximumLimit))
            return Problem(400, InvalidCode, $"limit is 1 to {MaximumLimit}.");
        CaseItemKind? kind = null;
        Guid? subjectId = null;
        if (query.ContainsKey("subjectKind") || query.ContainsKey("subjectId"))
        {
            if (!TrackReviewEndpoints.TryParseName<CaseItemKind>(query["subjectKind"], out var parsedKind) ||
                !Guid.TryParseExact(query["subjectId"], "D", out var parsedId))
                return Problem(400, InvalidCode, "subjectKind (Track, AnalyticEvent or Entity) and subjectId go together.");
            kind = parsedKind;
            subjectId = parsedId;
        }

        var cases = await repository.ListAsync(kind, subjectId, limit, cancellationToken);
        return Results.Ok(new ListResponse(InvestigationCase.Statement, cases.Select(Summary).ToList()));
    }

    private static async Task<IResult> GetAsync(Guid id, HttpRequest http, ICaseRepository repository, CancellationToken cancellationToken)
    {
        if (http.Query.Count > 0) return Problem(400, InvalidCode, "This endpoint takes no query parameters.");
        var detail = await repository.GetAsync(id, cancellationToken);
        if (detail is null) return Problem(404, "case_not_found", "The case does not exist.");
        return Results.Ok(new DetailResponse(InvestigationCase.Statement, Summary(detail.Summary), detail.Items.Select(Item).ToList(),
            detail.Notes.Select(Note).ToList()));
    }

    private static async Task<IResult> AddItemAsync(Guid id, AddItemRequest request, ICaseRepository repository,
        CancellationToken cancellationToken)
    {
        if (!TrackReviewEndpoints.TryParseName<CaseItemKind>(request.Kind, out var kind) || request.SubjectId is not { } subjectId ||
            subjectId == Guid.Empty)
            return Problem(400, InvalidCode, "kind (Track, AnalyticEvent or Entity) and subjectId are required.");
        return await Validated(async () => Written(await repository.AddItemAsync(id, kind, subjectId, request.Note, cancellationToken),
            item => Results.Created($"/api/cases/{id}", Item(item))));
    }

    private static async Task<IResult> RemoveItemAsync(Guid id, Guid itemId, RemoveItemRequest request, ICaseRepository repository,
        CancellationToken cancellationToken) =>
        await Validated(async () => Written(await repository.RemoveItemAsync(id, itemId, request.Note, cancellationToken),
            item => Results.Ok(Item(item))));

    private static async Task<IResult> AddNoteAsync(Guid id, AddNoteRequest request, ICaseRepository repository, CancellationToken cancellationToken) =>
        await Validated(async () => Written(await repository.AddNoteAsync(id, request.Body ?? string.Empty, cancellationToken),
            note => Results.Created($"/api/cases/{id}", Note(note))));

    private static async Task<IResult> Validated(Func<Task<IResult>> action)
    {
        try
        {
            return await action();
        }
        catch (DomainValidationException exception)
        {
            return Problem(400, exception.Code, exception.Message);
        }
    }

    private static IResult Written<T>(CaseWriteResult<T> result, Func<T, IResult> done) where T : class => result.Outcome switch
    {
        CaseWriteOutcome.Done => done(result.Value!),
        CaseWriteOutcome.CaseNotFound => Problem(404, "case_not_found", "The case does not exist."),
        CaseWriteOutcome.SubjectNotFound => Problem(404, "case_subject_not_found", "The Track, event or Entity does not exist."),
        CaseWriteOutcome.AlreadyInCase => Problem(409, "case_item_already_present", "The subject is already an item of this case."),
        CaseWriteOutcome.ItemNotFound => Problem(404, "case_item_not_found", "The item does not exist in this case."),
        CaseWriteOutcome.AlreadyRemoved => Problem(409, "case_item_already_removed", "The item was already removed from the case."),
        _ => throw new InvalidOperationException("Unknown case outcome."),
    };

    private static ActorResponse Actor(CaseActorView actor) =>
        new(actor.OperatorId, actor.DisplayName, actor.IdentitySource, actor.AtUtc, actor.AuditEntryId);

    private static SummaryResponse Summary(CaseSummary summary) => new(summary.CaseId, summary.Title, summary.Purpose, Actor(summary.CreatedBy),
        summary.ActiveItemCount, summary.RemovedItemCount, summary.NoteCount);

    private static ItemResponse Item(CaseItemView item) => new(item.ItemId, item.Kind.ToString(), item.SubjectId, item.Note, Actor(item.AddedBy),
        item.RemovedBy is { } removedBy ? Actor(removedBy) : null, item.RemovalNote,
        new SubjectResponse(item.Subject.Available, item.Subject.EarlierRun, item.Subject.ObjectClass, item.Subject.CameraId, item.Subject.CameraName,
            item.Subject.StartUtc, item.Subject.EndUtc, item.Subject.ReviewStatus, item.Subject.RuleId, item.Subject.EntityDisplayCode,
            item.Subject.ProcessingRunId, item.Subject.VideoAssetId, item.Subject.StartOffsetMs));

    private static NoteResponse Note(CaseNoteView note) => new(note.NoteId, note.Body, Actor(note.Author));

    private static IResult Problem(int status, string code, string detail) => FaceEndpoints.Problem(status, code, detail);
}

/// <summary>
/// The audit read surface (PoC S11-full; ADR-027 §3): read-only, operator-only, newest first. Filters by subject
/// (<c>subject=type:id</c>, repeatable up to 50), <c>action</c> and <c>operatorId</c>.
/// </summary>
public static class AuditEndpoints
{
    public const string InvalidCode = "audit_query_invalid";
    public const int MaximumSubjects = 50;
    public const int DefaultLimit = 50;
    public const int MaximumLimit = 200;

    public static IEndpointRouteBuilder MapAuditEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        endpoints.MapGet("/api/audit", ReadAsync).RequireAuthorization(OperatorPolicy.Name);
        return endpoints;
    }

    public sealed record EntryResponse(Guid EntryId, string OperatorId, string OperatorDisplayName, string IdentitySource, string Action,
        string SubjectType, string SubjectId, DateTimeOffset RecordedAtUtc, string PayloadSha256, string CorrelationId);

    public sealed record PageResponse(string Statement, IReadOnlyList<EntryResponse> Items, string? NextCursor);

    public const string Statement =
        "Append-only audit of operator actions. Each entry records who acted (and how they were identified), what, on which subject " +
        "and when by the server's clock; the submitted payload is not stored, only its SHA-256.";

    private static async Task<IResult> ReadAsync(HttpRequest http, IAuditReader reader, CancellationToken cancellationToken)
    {
        var query = http.Query;
        if (query.Keys.Any(key => key is not ("subject" or "action" or "operatorId" or "cursor" or "limit")) ||
            query.Any(pair => pair.Key != "subject" && pair.Value.Count != 1))
            return Problem(400, "Unknown or repeated query key.");
        var subjects = new List<(string, string)>();
        foreach (var value in query["subject"])
        {
            var separator = value?.IndexOf(':', StringComparison.Ordinal) ?? -1;
            if (separator < 1 || separator == value!.Length - 1) return Problem(400, "subject is type:id.");
            subjects.Add((value[..separator], value[(separator + 1)..]));
        }

        if (subjects.Count > MaximumSubjects) return Problem(400, $"At most {MaximumSubjects} subjects.");
        var limit = DefaultLimit;
        if (query.TryGetValue("limit", out var limitValue) &&
            (!int.TryParse(limitValue, NumberStyles.None, CultureInfo.InvariantCulture, out limit) || limit is < 1 or > MaximumLimit))
            return Problem(400, $"limit is 1 to {MaximumLimit}.");
        (DateTimeOffset, Guid)? before = null;
        if (query.TryGetValue("cursor", out var cursorValue))
        {
            if (!TryParseCursor(cursorValue.ToString(), out var parsed)) return Problem(400, "The cursor is invalid.");
            before = parsed;
        }

        var page = await reader.ReadAsync(new AuditQuery(subjects, Optional(query, "action"), Optional(query, "operatorId"), before, limit),
            cancellationToken);
        return Results.Ok(new PageResponse(Statement,
            page.Items.Select(entry => new EntryResponse(entry.EntryId, entry.OperatorId, entry.OperatorDisplayName, entry.IdentitySource,
                entry.Action, entry.SubjectType, entry.SubjectId, entry.RecordedAtUtc, entry.PayloadSha256, entry.CorrelationId)).ToList(),
            page.Next is { } next ? FormatCursor(next) : null));
    }

    private static string? Optional(IQueryCollection query, string key) =>
        query.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value) ? value.ToString() : null;

    /// <summary>The cursor is the last entry's server time (UTC ticks) and id: <c>ticks.id</c>.</summary>
    internal static string FormatCursor((DateTimeOffset RecordedAtUtc, Guid EntryId) position) =>
        position.RecordedAtUtc.UtcTicks.ToString(CultureInfo.InvariantCulture) + "." + position.EntryId.ToString("N");

    internal static bool TryParseCursor(string value, out (DateTimeOffset, Guid) position)
    {
        position = default;
        var parts = value.Split('.');
        if (parts.Length != 2 || !long.TryParse(parts[0], NumberStyles.None, CultureInfo.InvariantCulture, out var ticks) ||
            ticks < DateTimeOffset.MinValue.UtcTicks || ticks > DateTimeOffset.MaxValue.UtcTicks || !Guid.TryParseExact(parts[1], "N", out var id))
            return false;
        position = (new DateTimeOffset(ticks, TimeSpan.Zero), id);
        return true;
    }

    private static IResult Problem(int status, string detail) => FaceEndpoints.Problem(status, InvalidCode, detail);
}
