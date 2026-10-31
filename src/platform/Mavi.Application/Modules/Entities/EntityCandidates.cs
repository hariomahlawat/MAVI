using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Faces;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Entities;

/// <summary>One side of a candidate, or one member of an Entity, with what the operator needs to judge it.</summary>
public sealed record EntityTrackView(
    Guid TrackId,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    ObjectClass ObjectClass,
    DateTimeOffset StartTimestampUtc,
    DateTimeOffset EndTimestampUtc,
    long StartOffsetMs,
    long EndOffsetMs,
    Guid? ThumbnailArtifactId,
    Guid? EntityId,
    bool Visible);

public sealed record EntityCandidateDecisionView(
    DateTimeOffset DecidedAtUtc, string OperatorId, string DisplayName, string IdentitySource, string? Note, Guid? AuditEntryId);

/// <param name="FaceFactorAvailable">
/// Both sides of a Person pair have a usable face in a completed analysis of the current face release. Only that
/// fact is listed; the face score is computed on request, audited (ADR-023 §5).
/// </param>
public sealed record EntityCandidateView(
    Guid CandidateId,
    string CatalogueVersion,
    string IdentityFingerprint,
    ObjectClass ObjectClass,
    double AppearanceScore,
    bool SameCamera,
    long GapMs,
    EntityCandidateStatus Status,
    EntityCandidateDecisionView? Decision,
    Guid? EntityId,
    EntityTrackView Lower,
    EntityTrackView Higher,
    bool FaceFactorAvailable);

public sealed record EntityCandidateListQuery(
    EntityCandidateStatus Status,
    ObjectClass? ObjectClass,
    Guid? CameraId,
    Guid? OtherCameraId,
    Guid? TrackId,
    int Limit,
    int Offset);

public sealed record EntityCandidatePage(int Total, IReadOnlyList<EntityCandidateView> Items);

public sealed record EntityCandidatePairCount(
    Guid CameraId, string CameraCode, Guid OtherCameraId, string OtherCameraCode, ObjectClass ObjectClass, int Open, int Confirmed, int Dismissed);

public sealed record EntityCandidateSummary(
    string CatalogueVersion, string? IdentityFingerprint, int Derivations, int PendingDerivations, IReadOnlyList<EntityCandidatePairCount> Pairs);

public sealed record EntityView(
    Guid EntityId,
    string DisplayCode,
    EntityType EntityType,
    DateTimeOffset CreatedAtUtc,
    DateTimeOffset UpdatedAtUtc,
    IReadOnlyList<EntityTrackView> Members,
    IReadOnlyList<EntityCandidateView> Confirmations,
    EntityMergeState State = EntityMergeState.Active,
    Guid? MergedIntoEntityId = null,
    IReadOnlyList<EntityMembershipChangeView>? History = null,
    IReadOnlyList<Guid>? MergedFromEntityIds = null,
    IReadOnlyList<Guid>? RelatedCandidateIds = null);

/// <summary>One join or leave of a Track, as recorded (ADR-027 §4).</summary>
public sealed record EntityMembershipChangeView(long Sequence, Guid TrackId, Guid EntityId, EntityMembershipChangeKind Change,
    EntityMembershipCause Cause, Guid? CandidateId, string? Note, string OperatorId, string OperatorDisplayName, string IdentitySource,
    DateTimeOffset AtUtc, Guid AuditEntryId);

/// <summary>One confirm, dismiss or reopen of a candidate, as recorded (ADR-027 §4).</summary>
public sealed record EntityCandidateDecisionHistoryView(long Sequence, EntityCandidateDecisionKind Decision, Guid? EntityId, string? Note,
    string OperatorId, string OperatorDisplayName, string IdentitySource, DateTimeOffset AtUtc, Guid AuditEntryId);

/// <summary>The outcome of a merge, unlink or reopen: a refusal code (nothing written), or the Entity / candidate after it.</summary>
public sealed record EntityCorrectionResult(string? RefusalCode, EntityView? Entity = null, EntityCandidateView? Candidate = null,
    Guid? ConflictingTrackId = null, Guid? OtherConflictingTrackId = null);

/// <summary>Refusal codes of the Entity corrections (ADR-027 §4).</summary>
public static class EntityCorrectionRules
{
    public const string EntityNotFound = "entity_not_found";
    public const string EntityNotActive = "entity_not_active";
    public const string MergeInvalid = "entity_merge_invalid";
    public const string MergeImplausible = "entity_merge_implausible";
    /// <summary>The source has no members: a merge would move nothing and leave no membership history to record it.</summary>
    public const string MergeSourceEmpty = "entity_merge_source_empty";
    public const string TrackNotMember = "entity_track_not_member";
    public const string ChangedConcurrently = "entity_changed_concurrently";
    public const string CandidateNotDecided = "entity_candidate_not_decided";
    public const string CandidateStillLinked = "entity_candidate_still_linked";
}

public sealed record EntityDecisionResult(string? RefusalCode, EntityCandidateView? Candidate, Guid? EntityId, bool EntityCreated,
    Guid? ConflictingTrackId = null);

public enum EntityCandidateDerivationOutcome { Derived, NotVisible, AlreadyDerived, NotFound }

/// <summary>
/// The pair of usable faces with the highest cosine between two Person Tracks under one face identity, read when an
/// operator asks (ADR-023 §5). Never stored.
/// </summary>
public sealed record EntityFacePair(Guid LowerFaceId, Guid LowerObservationId, Guid? LowerArtifactId, FaceBox LowerBox,
    Guid HigherFaceId, Guid HigherObservationId, Guid? HigherArtifactId, FaceBox HigherBox, double Score);

/// <summary>Entity candidates and confirmed Entities (ADR-023). The only writer of <c>Track.EntityId</c> is <see cref="ConfirmAsync"/>.</summary>
public interface IEntityCandidateRepository
{
    Task<IReadOnlyList<Guid>> ListAnalysesAwaitingDerivationAsync(
        string identityFingerprint, EntityCandidateCatalogueDefinition catalogue, int batchSize, CancellationToken cancellationToken);

    /// <summary>
    /// Derives the candidates of one completed embedding analysis under one global advisory lock (ADR-023 §2): its
    /// embedded Tracks against every visible embedded Track of the identity, pair-local rule only.
    /// </summary>
    Task<(EntityCandidateDerivationOutcome Outcome, int Inserted)> DeriveAsync(
        Guid embeddingAnalysisId, string identityFingerprint, EntityCandidateCatalogueDefinition catalogue, DateTimeOffset nowUtc,
        CancellationToken cancellationToken);

    Task<EntityCandidatePage> ListAsync(EntityCandidateListQuery query, string identityFingerprint, string catalogueVersion,
        string? faceIdentityFingerprint, CancellationToken cancellationToken);

    Task<EntityCandidateView?> GetAsync(Guid candidateId, string? faceIdentityFingerprint, CancellationToken cancellationToken);

    Task<EntityCandidateSummary> SummarizeAsync(string? identityFingerprint, string catalogueVersion, CancellationToken cancellationToken);

    Task<EntityView?> GetEntityAsync(Guid entityId, CancellationToken cancellationToken);

    /// <summary>
    /// Confirms under row locks (candidate, then both Tracks in id order, then the Entity) and appends the audit entry
    /// in the same transaction before any state changes (ADR-023 §6). A refusal changes nothing and writes no entry; a
    /// candidate of another catalogue version or embedding identity is refused as superseded.
    /// </summary>
    Task<EntityDecisionResult> ConfirmAsync(Guid candidateId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, EntityCandidateCatalogueDefinition catalogue, string identityFingerprint,
        DateTimeOffset nowUtc, CancellationToken cancellationToken);

    /// <summary>Records a dismissal under the same locks and audit rule; a candidate of another catalogue or identity is refused.</summary>
    Task<EntityDecisionResult> DismissAsync(Guid candidateId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, EntityCandidateCatalogueDefinition catalogue, string identityFingerprint,
        DateTimeOffset nowUtc, CancellationToken cancellationToken);

    /// <summary>
    /// Unlinks a member Track (ADR-027 §4): locks the Track then the Entity, re-checks membership, appends the audit entry,
    /// records the leave and clears <c>Track.EntityId</c>. The Entity stays with its remaining members (option (a)).
    /// </summary>
    Task<EntityCorrectionResult> UnlinkAsync(Guid entityId, Guid trackId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, DateTimeOffset nowUtc, CancellationToken cancellationToken);

    /// <summary>
    /// Merges <paramref name="sourceEntityId"/> into <paramref name="targetEntityId"/> (ADR-027 §4): every member Track of both,
    /// then both Entities, are locked in id order; refused unless both are active, of one type, and every cross pair is
    /// physically plausible under the catalogue. Each source member records a leave and a join; the source becomes Merged.
    /// </summary>
    Task<EntityCorrectionResult> MergeAsync(Guid sourceEntityId, Guid targetEntityId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, EntityCandidateCatalogueDefinition catalogue, DateTimeOffset nowUtc,
        CancellationToken cancellationToken);

    /// <summary>
    /// Reopens a dismissed candidate, or a confirmed one whose Tracks are no longer together in one Entity (ADR-027 §4);
    /// current catalogue and identity only.
    /// </summary>
    Task<EntityDecisionResult> ReopenAsync(Guid candidateId, string? note, EntityCandidateDecider decider,
        Func<CancellationToken, Task<AuditEntryReceipt>> appendAudit, EntityCandidateCatalogueDefinition catalogue, string identityFingerprint,
        DateTimeOffset nowUtc, CancellationToken cancellationToken);

    /// <summary>Every recorded decision on the candidate, oldest first; null when it does not exist.</summary>
    Task<IReadOnlyList<EntityCandidateDecisionHistoryView>?> GetCandidateHistoryAsync(Guid candidateId, CancellationToken cancellationToken);

    Task<EntityFacePair?> BestFacePairAsync(Guid lowerTrackId, Guid higherTrackId, string faceIdentityFingerprint, CancellationToken cancellationToken);
}

public static class EntityCandidateLabels
{
    public const string Candidates = "Entity candidates — not identification — Development";
    public const string Entity = "Operator-confirmed Entity — not identification — Development";
    public const string PlausibilityDisclosure =
        "Time and camera only: MAVI knows no camera locations, distances, view overlap, travel times or clock errors.";
}

/// <summary>The derivation sweep's application side, like ADR-025's.</summary>
public sealed class EntityCandidateService(IEntityCandidateRepository repository, Embeddings.IEmbeddingRelease release, TimeProvider timeProvider)
{
    public async Task<int> DeriveDueAsync(int batchSize, CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition) return 0;
        var catalogue = EntityCandidateCatalogue.Current;
        var due = await repository.ListAnalysesAwaitingDerivationAsync(definition.Identity.Fingerprint, catalogue, batchSize, cancellationToken);
        var derived = 0;
        foreach (var analysisId in due)
        {
            var (outcome, _) = await repository.DeriveAsync(analysisId, definition.Identity.Fingerprint, catalogue, timeProvider.GetUtcNow(),
                cancellationToken);
            if (outcome is EntityCandidateDerivationOutcome.Derived or EntityCandidateDerivationOutcome.NotVisible) derived++;
        }

        return derived;
    }
}

/// <summary>A side of the face factor: Observed, or Unknown with the reason ADR-022 gives.</summary>
public sealed record FaceFactorSide(Guid TrackId, string State, string? Reason);

public sealed record FaceFactorResult(string? ErrorCode, int HttpStatus, FaceReleaseDefinition? Definition, FaceFactorSide? Lower,
    FaceFactorSide? Higher, EntityFacePair? Pair);

/// <summary>
/// The face factor of a Person candidate (ADR-023 §5): the best cosine between the two Tracks' usable faces under the
/// current face release, with the reference threshold, or Unknown with each side's reason. Separate from every other
/// factor, computed on request, never stored; the endpoint audits it.
/// </summary>
public sealed class EntityCandidateFaceFactorService(IEntityCandidateRepository repository, IFaceRepository faces, IFaceRelease release)
{
    public const string NotPersonCode = "entity_candidate_not_person";
    public const string NotFoundCode = "entity_candidate_not_found";

    public async Task<FaceFactorResult> ComputeAsync(Guid candidateId, CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition) return new FaceFactorResult("faces_not_configured", 409, null, null, null, null);
        var candidate = await repository.GetAsync(candidateId, null, cancellationToken);
        if (candidate is null) return new FaceFactorResult(NotFoundCode, 404, definition, null, null, null);
        if (candidate.ObjectClass != ObjectClass.Person) return new FaceFactorResult(NotPersonCode, 409, definition, null, null, null);

        var fingerprint = definition.Identity.Fingerprint;
        var lower = await SideAsync(candidate.Lower.TrackId, fingerprint, cancellationToken);
        var higher = await SideAsync(candidate.Higher.TrackId, fingerprint, cancellationToken);
        var pair = lower.State == FaceStates.Observed && higher.State == FaceStates.Observed
            ? await repository.BestFacePairAsync(candidate.Lower.TrackId, candidate.Higher.TrackId, fingerprint, cancellationToken)
            : null;
        return new FaceFactorResult(null, 200, definition, lower, higher, pair);
    }

    private async Task<FaceFactorSide> SideAsync(Guid trackId, string fingerprint, CancellationToken cancellationToken)
    {
        var view = await faces.GetTrackFacesAsync(trackId, fingerprint, cancellationToken);
        return view is null ? new FaceFactorSide(trackId, FaceStates.Unknown, "no_evidence") : new FaceFactorSide(trackId, view.State, view.Reason);
    }
}
