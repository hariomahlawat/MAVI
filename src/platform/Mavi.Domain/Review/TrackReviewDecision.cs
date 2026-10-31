using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;

namespace Mavi.Domain.Review;

/// <summary>What an operator decided about a Track's detection (ADR-027 §1). It never says who or which object it is.</summary>
public enum TrackReviewDecisionKind { Confirmed, Rejected, Cleared }

/// <summary>
/// One operator decision on a Track's detection (ADR-027 §1; review plan §2.2). Append-only: the database
/// refuses UPDATE, DELETE and TRUNCATE on its table, and <see cref="Track.ReviewStatus"/> is the projection of
/// the latest decision by <see cref="Sequence"/>. The operator and time come from the server, never the request.
/// </summary>
public sealed class TrackReviewDecision
{
    public const int NoteMaxLength = 1000;

    private TrackReviewDecision() { }

    public static TrackReviewDecision Create(Guid decisionId, Guid trackId, TrackReviewDecisionKind decision, ReviewStatus previousStatus,
        string? note, string operatorId, string operatorDisplayName, string identitySource, DateTimeOffset decidedAtUtc, string requestSha256,
        Guid auditEntryId)
    {
        if (decisionId == Guid.Empty || trackId == Guid.Empty || auditEntryId == Guid.Empty || !Enum.IsDefined(decision) || !Enum.IsDefined(previousStatus))
            throw Invalid();
        if (decision == TrackReviewDecisionKind.Cleared && previousStatus == ReviewStatus.Unreviewed)
            throw new DomainValidationException("track_review_nothing_to_clear", "The Track has no decision to clear.");
        if (decidedAtUtc.Offset != TimeSpan.Zero || !CanonicalSha256.IsCanonical(requestSha256))
            throw Invalid();
        if (string.IsNullOrWhiteSpace(operatorId) || string.IsNullOrWhiteSpace(operatorDisplayName) || string.IsNullOrWhiteSpace(identitySource))
            throw Invalid();
        return new TrackReviewDecision
        {
            Id = decisionId,
            TrackId = trackId,
            Decision = decision,
            PreviousStatus = previousStatus,
            ResultingStatus = ResultOf(decision),
            Note = NormaliseNote(note),
            OperatorId = operatorId,
            OperatorDisplayName = operatorDisplayName,
            IdentitySource = identitySource,
            DecidedAtUtc = decidedAtUtc,
            RequestSha256 = requestSha256,
            AuditEntryId = auditEntryId,
        };
    }

    /// <summary>The review status a decision leaves the Track in.</summary>
    public static ReviewStatus ResultOf(TrackReviewDecisionKind decision) => decision switch
    {
        TrackReviewDecisionKind.Confirmed => ReviewStatus.Confirmed,
        TrackReviewDecisionKind.Rejected => ReviewStatus.Rejected,
        TrackReviewDecisionKind.Cleared => ReviewStatus.Unreviewed,
        _ => throw Invalid(),
    };

    /// <summary>A blank note is no note; a note longer than <see cref="NoteMaxLength"/> is refused.</summary>
    public static string? NormaliseNote(string? note)
    {
        if (string.IsNullOrWhiteSpace(note)) return null;
        var trimmed = note.Trim();
        if (trimmed.Length > NoteMaxLength)
            throw new DomainValidationException("track_review_note_too_long", $"The note is longer than {NoteMaxLength} characters.");
        return trimmed;
    }

    /// <summary>The client's <c>decisionId</c>: an identical replay finds this row instead of deciding again.</summary>
    public Guid Id { get; private set; }

    /// <summary>The database's total order of decisions; the latest per Track is the projection.</summary>
    public long Sequence { get; private set; }

    public Guid TrackId { get; private set; }
    public TrackReviewDecisionKind Decision { get; private set; }
    public ReviewStatus PreviousStatus { get; private set; }
    public ReviewStatus ResultingStatus { get; private set; }
    public string? Note { get; private set; }
    public string OperatorId { get; private set; } = string.Empty;
    public string OperatorDisplayName { get; private set; } = string.Empty;
    public string IdentitySource { get; private set; } = string.Empty;
    public DateTimeOffset DecidedAtUtc { get; private set; }

    /// <summary>SHA-256 of the request (Track, decision, note, expectation), to tell a replay from a conflicting reuse.</summary>
    public string RequestSha256 { get; private set; } = string.Empty;

    /// <summary>The audit entry written in the same transaction; its time is <see cref="DecidedAtUtc"/>.</summary>
    public Guid AuditEntryId { get; private set; }

    private static DomainValidationException Invalid() => new("track_review_decision_invalid", "The review decision is invalid.");
}
