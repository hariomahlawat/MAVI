using Mavi.Domain.Common;

namespace Mavi.Domain.Intelligence;

public enum EntityCandidateStatus { Open, Confirmed, Dismissed }

/// <summary>
/// A machine proposal that two Tracks of one class might show the same person or vehicle (ADR-023 §1–§3). It is a
/// candidate, never identity. Its factors are kept separate; the pair (lower, higher Track id) is unique per
/// catalogue version and embedding identity, and only the decision changes after creation, once.
/// </summary>
public sealed class EntityCandidate
{
    public const int MaximumNoteLength = 500;
    public const int MaximumTokenLength = 64;

    private EntityCandidate() { }

    public static EntityCandidate Create(
        Guid derivationId,
        string catalogueVersion,
        string identityFingerprint,
        Guid firstTrackId,
        Guid secondTrackId,
        ObjectClass objectClass,
        double appearanceScore,
        bool sameCamera,
        long gapMs,
        DateTimeOffset createdAtUtc)
    {
        if (derivationId == Guid.Empty || firstTrackId == Guid.Empty || secondTrackId == Guid.Empty || firstTrackId == secondTrackId ||
            !IsToken(catalogueVersion) || !CanonicalSha256.IsCanonical(identityFingerprint) ||
            objectClass is not (ObjectClass.Person or ObjectClass.Vehicle) ||
            !double.IsFinite(appearanceScore) || appearanceScore is < -1 or > 1)
            throw Invalid();
        var (lower, higher) = firstTrackId.CompareTo(secondTrackId) < 0 ? (firstTrackId, secondTrackId) : (secondTrackId, firstTrackId);
        return new EntityCandidate
        {
            Id = Guid.CreateVersion7(),
            DerivationId = derivationId,
            CatalogueVersion = catalogueVersion,
            IdentityFingerprint = identityFingerprint,
            LowerTrackId = lower,
            HigherTrackId = higher,
            ObjectClass = objectClass,
            AppearanceScore = appearanceScore,
            SameCamera = sameCamera,
            GapMs = gapMs,
            Status = EntityCandidateStatus.Open,
            CreatedAtUtc = createdAtUtc.ToUniversalTime(),
        };
    }

    public void Confirm(Guid entityId, EntityCandidateDecider decider, string? note, Guid auditEntryId, DateTimeOffset nowUtc)
    {
        if (entityId == Guid.Empty) throw Invalid();
        Decide(EntityCandidateStatus.Confirmed, decider, note, auditEntryId, nowUtc);
        EntityId = entityId;
    }

    public void Dismiss(EntityCandidateDecider decider, string? note, Guid auditEntryId, DateTimeOffset nowUtc) =>
        Decide(EntityCandidateStatus.Dismissed, decider, note, auditEntryId, nowUtc);

    /// <summary>
    /// Returns a decided candidate to Open (ADR-027 §4). Its decision fields are a projection of the append-only decision
    /// history, which keeps every earlier decision; the caller checks that a confirmed pair is no longer together.
    /// </summary>
    public void Reopen()
    {
        if (Status == EntityCandidateStatus.Open)
            throw new DomainValidationException("entity_candidate_not_decided", "The candidate is open.");
        Status = EntityCandidateStatus.Open;
        DecidedAtUtc = null;
        DecidedByOperatorId = null;
        DecidedByDisplayName = null;
        DecidedByIdentitySource = null;
        DecisionNote = null;
        DecisionAuditEntryId = null;
        EntityId = null;
    }

    public static string? NormaliseNote(string? note)
    {
        var trimmed = note?.Trim();
        return string.IsNullOrEmpty(trimmed) ? null : trimmed;
    }

    public Guid Id { get; private set; }
    public Guid DerivationId { get; private set; }
    public string CatalogueVersion { get; private set; } = string.Empty;
    public string IdentityFingerprint { get; private set; } = string.Empty;
    public Guid LowerTrackId { get; private set; }
    public Guid HigherTrackId { get; private set; }
    public ObjectClass ObjectClass { get; private set; }
    public double AppearanceScore { get; private set; }
    public bool SameCamera { get; private set; }

    /// <summary>Milliseconds from the earlier Track's end to the later Track's start; negative inside the tolerance.</summary>
    public long GapMs { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public EntityCandidateStatus Status { get; private set; }
    public DateTimeOffset? DecidedAtUtc { get; private set; }
    public string? DecidedByOperatorId { get; private set; }
    public string? DecidedByDisplayName { get; private set; }
    public string? DecidedByIdentitySource { get; private set; }
    public string? DecisionNote { get; private set; }
    public Guid? DecisionAuditEntryId { get; private set; }
    public Guid? EntityId { get; private set; }

    private void Decide(EntityCandidateStatus status, EntityCandidateDecider decider, string? note, Guid auditEntryId, DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(decider);
        if (Status != EntityCandidateStatus.Open)
            throw new DomainValidationException("entity_candidate_already_decided", "The candidate has already been decided.");
        var normalised = NormaliseNote(note);
        if (normalised is { Length: > MaximumNoteLength } || auditEntryId == Guid.Empty ||
            string.IsNullOrWhiteSpace(decider.OperatorId) || string.IsNullOrWhiteSpace(decider.DisplayName) ||
            string.IsNullOrWhiteSpace(decider.IdentitySource))
            throw Invalid();
        Status = status;
        DecidedAtUtc = nowUtc.ToUniversalTime();
        DecidedByOperatorId = decider.OperatorId;
        DecidedByDisplayName = decider.DisplayName;
        DecidedByIdentitySource = decider.IdentitySource;
        DecisionNote = normalised;
        DecisionAuditEntryId = auditEntryId;
    }

    private static bool IsToken(string? value) =>
        value is { Length: > 0 and <= MaximumTokenLength } && value.All(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '.' or '_');

    private static DomainValidationException Invalid() => new("entity_candidate_invalid", "The entity candidate is invalid.");
}

/// <summary>The operator who decided, taken from the server-side identity (ADR-010 §2), never from a request body.</summary>
public sealed record EntityCandidateDecider(string OperatorId, string DisplayName, string IdentitySource);

/// <summary>One derivation of Entity candidates for one completed embedding analysis and catalogue version (ADR-023 §2).</summary>
public sealed class EntityCandidateDerivation
{
    public const string OutcomeDerived = "derived";
    public const string OutcomeNotVisible = "not_visible";

    private EntityCandidateDerivation() { }

    public static EntityCandidateDerivation Create(Guid embeddingAnalysisId, Guid processingRunId, string catalogueVersion, string catalogueSha256,
        string identityFingerprint, string outcome, int candidateCount, DateTimeOffset derivedAtUtc)
    {
        if (embeddingAnalysisId == Guid.Empty || processingRunId == Guid.Empty || string.IsNullOrWhiteSpace(catalogueVersion) ||
            !CanonicalSha256.IsCanonical(catalogueSha256) || !CanonicalSha256.IsCanonical(identityFingerprint) ||
            outcome is not (OutcomeDerived or OutcomeNotVisible) || candidateCount < 0 || (outcome == OutcomeNotVisible && candidateCount != 0))
            throw new DomainValidationException("entity_candidate_derivation_invalid", "The entity candidate derivation is invalid.");
        return new EntityCandidateDerivation
        {
            Id = Guid.CreateVersion7(),
            EmbeddingAnalysisId = embeddingAnalysisId,
            ProcessingRunId = processingRunId,
            CatalogueVersion = catalogueVersion,
            CatalogueSha256 = catalogueSha256,
            IdentityFingerprint = identityFingerprint,
            Outcome = outcome,
            CandidateCount = candidateCount,
            DerivedAtUtc = derivedAtUtc.ToUniversalTime(),
        };
    }

    public Guid Id { get; private set; }
    public Guid EmbeddingAnalysisId { get; private set; }
    public Guid ProcessingRunId { get; private set; }
    public string CatalogueVersion { get; private set; } = string.Empty;
    public string CatalogueSha256 { get; private set; } = string.Empty;
    public string IdentityFingerprint { get; private set; } = string.Empty;
    public string Outcome { get; private set; } = string.Empty;
    public int CandidateCount { get; private set; }
    public DateTimeOffset DerivedAtUtc { get; private set; }
}
