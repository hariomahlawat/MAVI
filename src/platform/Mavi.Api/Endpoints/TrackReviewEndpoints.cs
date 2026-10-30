using Mavi.Api.Identity;
using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Review;
using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Review;

namespace Mavi.Api.Endpoints;

/// <summary>
/// Track review decisions (PoC S11-full; ADR-027 §1, §5). Every route requires <see cref="OperatorPolicy"/>; the decision
/// is JSON, its operator and time come from the server, and it is recorded with its audit row in one transaction. A
/// decision says whether the detection is correct, never who or which object it is.
/// </summary>
public static class TrackReviewEndpoints
{
    public const string InvalidCode = "track_review_invalid";
    public const string ConflictCode = "track_review_conflict";
    public const string DecisionConflictCode = "track_review_decision_conflict";
    public const string NothingToClearCode = "track_review_nothing_to_clear";
    public const int DefaultHistoryLimit = 50;
    public const int MaximumHistoryLimit = 200;

    public static IEndpointRouteBuilder MapTrackReviewEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        var review = endpoints.MapGroup("/api/tracks/{id:guid}").RequireAuthorization(OperatorPolicy.Name);
        review.MapPost("/review", DecideAsync);
        review.MapGet("/review", GetAsync);
        review.MapGet("/review-history", HistoryAsync);
        return endpoints;
    }

    public sealed record ReviewRequest(Guid? DecisionId, string? Decision, string? ExpectedReviewStatus, string? Note);

    public sealed record DecisionResponse(Guid DecisionId, Guid TrackId, string Decision, string PreviousStatus, string ResultingStatus,
        string? Note, string OperatorId, string OperatorDisplayName, string IdentitySource, DateTimeOffset DecidedAtUtc, Guid AuditEntryId);

    public sealed record DecideResponse(Guid TrackId, string ReviewStatus, DecisionResponse LatestDecision, bool Replayed);

    public sealed record OtherRunResponse(Guid ProcessingRunId, DateTimeOffset? CompletedAtUtc, int ReviewedTrackCount);

    public sealed record StateResponse(Guid TrackId, Guid ProcessingRunId, string ReviewStatus, DecisionResponse? LatestDecision,
        IReadOnlyList<OtherRunResponse> OtherRuns, string Statement);

    public sealed record HistoryResponse(Guid TrackId, IReadOnlyList<DecisionResponse> Items, string? NextCursor);

    public const string Statement =
        "A review decision says whether the detection is correct. It never says who or which object the Track shows. " +
        "Decisions belong to this processing run; a new run starts Unreviewed.";

    private static async Task<IResult> DecideAsync(Guid id, ReviewRequest request, ITrackReviewRepository repository,
        CancellationToken cancellationToken)
    {
        if (request.DecisionId is not { } decisionId || decisionId == Guid.Empty ||
            !TryParseName<TrackReviewDecisionKind>(request.Decision, out var decision) ||
            !TryParseName<ReviewStatus>(request.ExpectedReviewStatus, out var expected))
            return Problem(400, InvalidCode, "decisionId, decision (Confirmed, Rejected or Cleared) and expectedReviewStatus are required.");
        string? note;
        try
        {
            note = TrackReviewDecision.NormaliseNote(request.Note);
        }
        catch (DomainValidationException exception)
        {
            return Problem(400, exception.Code, exception.Message);
        }

        // The request hash tells an identical replay from a reuse of the id with another payload.
        var requestSha256 = AuditPayload.Sha256(new { trackId = id, decision = decision.ToString(), expectedReviewStatus = expected.ToString(), note });
        var outcome = await repository.DecideAsync(new TrackReviewRequest(decisionId, id, decision, expected, note), requestSha256,
            cancellationToken);
        return outcome.Kind switch
        {
            TrackReviewOutcomeKind.Recorded or TrackReviewOutcomeKind.Replayed => Results.Ok(new DecideResponse(id,
                (outcome.CurrentStatus ?? outcome.Decision!.ResultingStatus).ToString(), Decision(outcome.Decision!),
                outcome.Kind == TrackReviewOutcomeKind.Replayed)),
            TrackReviewOutcomeKind.TrackNotFound => Problem(404, "track_not_found", "Track was not found."),
            TrackReviewOutcomeKind.StatusConflict => Conflict(ConflictCode,
                "The Track's review status changed since it was read.", outcome),
            TrackReviewOutcomeKind.DecisionIdConflict => Conflict(DecisionConflictCode,
                "This decisionId was already used for a different decision.", outcome),
            TrackReviewOutcomeKind.NothingToClear => Problem(409, NothingToClearCode, "The Track has no decision to clear."),
            _ => throw new InvalidOperationException("Unknown review outcome."),
        };
    }

    private static async Task<IResult> GetAsync(Guid id, HttpRequest http, ITrackReviewRepository repository, CancellationToken cancellationToken)
    {
        if (http.Query.Count > 0) return Problem(400, InvalidCode, "This endpoint takes no query parameters.");
        var state = await repository.GetStateAsync(id, cancellationToken);
        if (state is null) return Problem(404, "track_not_found", "Track was not found.");
        return Results.Ok(new StateResponse(state.TrackId, state.ProcessingRunId, state.ReviewStatus.ToString(),
            state.LatestDecision is { } latest ? Decision(latest) : null,
            state.OtherRuns.Select(run => new OtherRunResponse(run.ProcessingRunId, run.CompletedAtUtc, run.ReviewedTrackCount)).ToList(),
            Statement));
    }

    private static async Task<IResult> HistoryAsync(Guid id, HttpRequest http, ITrackReviewRepository repository,
        CancellationToken cancellationToken)
    {
        var query = http.Query;
        if (query.Keys.Any(key => key is not ("cursor" or "limit")) || query.Any(pair => pair.Value.Count != 1))
            return Problem(400, InvalidCode, "Unknown or repeated query key.");
        var limit = DefaultHistoryLimit;
        if (query.TryGetValue("limit", out var limitValue) &&
            (!int.TryParse(limitValue, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out limit) ||
             limit is < 1 or > MaximumHistoryLimit))
            return Problem(400, InvalidCode, $"limit is 1 to {MaximumHistoryLimit}.");
        long? before = null;
        if (query.TryGetValue("cursor", out var cursorValue))
        {
            if (!long.TryParse(cursorValue, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture,
                    out var parsed) || parsed < 1)
                return Problem(400, InvalidCode, "The cursor is invalid.");
            before = parsed;
        }

        var page = await repository.GetHistoryAsync(id, before, limit, cancellationToken);
        if (page is null) return Problem(404, "track_not_found", "Track was not found.");
        return Results.Ok(new HistoryResponse(id, page.Items.Select(Decision).ToList(),
            page.NextBeforeSequence?.ToString(System.Globalization.CultureInfo.InvariantCulture)));
    }

    private static IResult Conflict(string code, string detail, TrackReviewOutcome outcome) => Results.Problem(statusCode: 409, detail: detail,
        extensions: new Dictionary<string, object?>
        {
            ["code"] = code,
            ["currentReviewStatus"] = outcome.CurrentStatus?.ToString(),
            ["currentDecision"] = outcome.Decision is { } decision ? Decision(decision) : null,
        });

    private static DecisionResponse Decision(TrackReviewDecisionView view) => new(view.DecisionId, view.TrackId, view.Decision.ToString(),
        view.PreviousStatus.ToString(), view.ResultingStatus.ToString(), view.Note, view.OperatorId, view.OperatorDisplayName, view.IdentitySource,
        view.DecidedAtUtc, view.AuditEntryId);

    /// <summary>Only the exact member name: no numbers, no case folding.</summary>
    internal static bool TryParseName<T>(string? value, out T parsed) where T : struct, Enum
    {
        parsed = default;
        return value is not null && Enum.GetNames<T>().Contains(value, StringComparer.Ordinal) && Enum.TryParse(value, out parsed);
    }

    private static IResult Problem(int status, string code, string detail) => FaceEndpoints.Problem(status, code, detail);
}
