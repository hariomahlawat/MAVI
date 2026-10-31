using Mavi.Domain.Common;

namespace Mavi.Domain.Intelligence;

/// <summary>Whether an Entity still groups Tracks or was merged into another (ADR-027 §4). A projection of its history.</summary>
public enum EntityMergeState { Active, Merged }

public enum EntityMembershipChangeKind { Joined, Left }

/// <summary>Which audited operator decision changed a Track's membership (ADR-027 §4).</summary>
public enum EntityMembershipCause { CandidateConfirmed, Unlinked, Merged }

/// <summary>The operator who decided and when, from the server (ADR-010 §2, §5), with the audit entry of the decision.</summary>
public sealed record EntityDecisionActor(string OperatorId, string DisplayName, string IdentitySource, DateTimeOffset AtUtc, Guid AuditEntryId)
{
    internal void Validate()
    {
        if (string.IsNullOrWhiteSpace(OperatorId) || string.IsNullOrWhiteSpace(DisplayName) || string.IsNullOrWhiteSpace(IdentitySource) ||
            AtUtc.Offset != TimeSpan.Zero || AuditEntryId == Guid.Empty)
            throw new DomainValidationException("entity_decision_actor_invalid", "The decision has no valid operator, time or audit entry.");
    }
}

/// <summary>
/// One join or leave of a Track (ADR-027 §4). Append-only: the database refuses UPDATE, DELETE and TRUNCATE, and
/// <see cref="Track.EntityId"/> is the projection of each Track's latest change (a join sets it, a leave clears it).
/// </summary>
public sealed class EntityMembershipChange
{
    private EntityMembershipChange() { }

    public static EntityMembershipChange Record(Guid trackId, Guid entityId, EntityMembershipChangeKind change, EntityMembershipCause cause,
        Guid? candidateId, string? note, EntityDecisionActor actor)
    {
        ArgumentNullException.ThrowIfNull(actor);
        actor.Validate();
        var confirmed = cause == EntityMembershipCause.CandidateConfirmed;
        if (trackId == Guid.Empty || entityId == Guid.Empty || !Enum.IsDefined(change) || !Enum.IsDefined(cause) ||
            confirmed != candidateId.HasValue || candidateId == Guid.Empty ||
            (confirmed && change != EntityMembershipChangeKind.Joined) ||
            (cause == EntityMembershipCause.Unlinked && change != EntityMembershipChangeKind.Left))
            throw new DomainValidationException("entity_membership_change_invalid", "The membership change is invalid.");
        return new EntityMembershipChange
        {
            Id = Guid.CreateVersion7(actor.AtUtc),
            TrackId = trackId,
            EntityId = entityId,
            Change = change,
            Cause = cause,
            CandidateId = candidateId,
            Note = EntityNotes.Normalise(note),
            OperatorId = actor.OperatorId,
            OperatorDisplayName = actor.DisplayName,
            IdentitySource = actor.IdentitySource,
            AtUtc = actor.AtUtc,
            AuditEntryId = actor.AuditEntryId,
        };
    }

    public Guid Id { get; private set; }

    /// <summary>The database's total order; the latest per Track is the projection.</summary>
    public long Sequence { get; private set; }

    public Guid TrackId { get; private set; }
    public Guid EntityId { get; private set; }
    public EntityMembershipChangeKind Change { get; private set; }
    public EntityMembershipCause Cause { get; private set; }
    public Guid? CandidateId { get; private set; }
    public string? Note { get; private set; }
    public string OperatorId { get; private set; } = string.Empty;
    public string OperatorDisplayName { get; private set; } = string.Empty;
    public string IdentitySource { get; private set; } = string.Empty;
    public DateTimeOffset AtUtc { get; private set; }
    public Guid AuditEntryId { get; private set; }
}

public enum EntityCandidateDecisionKind { Confirmed, Dismissed, Reopened }

/// <summary>
/// One decision on an Entity candidate (ADR-027 §4): confirm, dismiss or reopen. Append-only; the candidate's status and
/// decision fields are the projection of the latest one.
/// </summary>
public sealed class EntityCandidateDecisionRecord
{
    private EntityCandidateDecisionRecord() { }

    public static EntityCandidateDecisionRecord Record(Guid candidateId, EntityCandidateDecisionKind decision, Guid? entityId, string? note,
        EntityDecisionActor actor)
    {
        ArgumentNullException.ThrowIfNull(actor);
        actor.Validate();
        if (candidateId == Guid.Empty || !Enum.IsDefined(decision) || (decision == EntityCandidateDecisionKind.Confirmed) != entityId.HasValue ||
            entityId == Guid.Empty)
            throw new DomainValidationException("entity_candidate_decision_invalid", "The candidate decision is invalid.");
        return new EntityCandidateDecisionRecord
        {
            Id = Guid.CreateVersion7(actor.AtUtc),
            CandidateId = candidateId,
            Decision = decision,
            EntityId = entityId,
            Note = EntityNotes.Normalise(note),
            OperatorId = actor.OperatorId,
            OperatorDisplayName = actor.DisplayName,
            IdentitySource = actor.IdentitySource,
            AtUtc = actor.AtUtc,
            AuditEntryId = actor.AuditEntryId,
        };
    }

    public Guid Id { get; private set; }
    public long Sequence { get; private set; }
    public Guid CandidateId { get; private set; }
    public EntityCandidateDecisionKind Decision { get; private set; }
    public Guid? EntityId { get; private set; }
    public string? Note { get; private set; }
    public string OperatorId { get; private set; } = string.Empty;
    public string OperatorDisplayName { get; private set; } = string.Empty;
    public string IdentitySource { get; private set; } = string.Empty;
    public DateTimeOffset AtUtc { get; private set; }
    public Guid AuditEntryId { get; private set; }
}

/// <summary>Operator notes on Entity decisions: trimmed, blank is absent, at most <see cref="EntityCandidate.MaximumNoteLength"/>.</summary>
public static class EntityNotes
{
    public static string? Normalise(string? note)
    {
        var normalised = EntityCandidate.NormaliseNote(note);
        if (normalised is { Length: > EntityCandidate.MaximumNoteLength })
            throw new DomainValidationException("entity_note_too_long", $"The note is longer than {EntityCandidate.MaximumNoteLength} characters.");
        return normalised;
    }
}
