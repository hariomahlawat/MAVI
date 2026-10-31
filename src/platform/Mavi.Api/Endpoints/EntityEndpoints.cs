using Mavi.Api.Identity;
using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Embeddings;
using Mavi.Application.Modules.Entities;
using Mavi.Application.Modules.Faces;
using Mavi.Application.Modules.Identity;
using Mavi.Domain.Intelligence;

namespace Mavi.Api.Endpoints;

/// <summary>
/// Entity candidates and operator-confirmed Entities (PoC S7; ADR-023). Every route requires <see cref="OperatorPolicy"/>,
/// so with <c>Identity:Mode=disabled</c> all of them are refused. Confirm and dismiss follow the plate re-analysis
/// pattern (ADR-010 §8): JSON, the actor from <see cref="ICurrentOperator"/>, one audit row in the decision's
/// transaction; a refusal writes nothing. The face factor is a separate, audited 1:1 comparison (ADR-023 §5).
/// Confirmation is the only path that writes <c>Track.EntityId</c>; nothing here merges automatically.
/// </summary>
public static class EntityEndpoints
{
    public const string InvalidCode = "entity_candidate_query_invalid";
    public const string DecisionInvalidCode = "entity_decision_invalid";
    public const string NotConfiguredCode = "embeddings_not_configured";
    public const string SubjectCandidate = "entity-candidate";
    public const string SubjectEntity = "entity";
    public const int MaximumLimit = 200;
    public const int DefaultLimit = 50;
    public const int MaximumOffset = 100_000;

    private static readonly HashSet<string> ListKeys = new(StringComparer.Ordinal)
    {
        "status", "objectClass", "cameraId", "otherCameraId", "trackId", "limit", "offset",
    };

    public static IEndpointRouteBuilder MapEntityEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        var candidates = endpoints.MapGroup("/api/entity-candidates").RequireAuthorization(OperatorPolicy.Name);
        candidates.MapGet("", ListAsync);
        candidates.MapGet("/summary", SummaryAsync);
        candidates.MapGet("/{id:guid}", GetAsync);
        candidates.MapPost("/{id:guid}/confirm", ConfirmAsync);
        candidates.MapPost("/{id:guid}/dismiss", DismissAsync);
        candidates.MapPost("/{id:guid}/face-factor", FaceFactorAsync);
        candidates.MapPost("/{id:guid}/reopen", ReopenAsync);
        candidates.MapGet("/{id:guid}/history", CandidateHistoryAsync);
        var entities = endpoints.MapGroup("/api/entities").RequireAuthorization(OperatorPolicy.Name);
        entities.MapGet("/{id:guid}", GetEntityAsync);
        entities.MapPost("/{id:guid}/merge", MergeAsync);
        entities.MapPost("/{id:guid}/unlink", UnlinkAsync);
        return endpoints;
    }

    // --- Requests and responses ------------------------------------------------------------------

    public sealed record DecisionRequest(string? Note);

    public sealed record MergeRequest(Guid? IntoEntityId, string? Note);

    public sealed record UnlinkRequest(Guid? TrackId, string? Note);

    public sealed record MembershipChangeResponse(long Sequence, Guid TrackId, Guid EntityId, string Change, string Cause, Guid? CandidateId,
        string? Note, string OperatorId, string OperatorDisplayName, string IdentitySource, DateTimeOffset AtUtc, Guid AuditEntryId);

    public sealed record CandidateDecisionResponse(long Sequence, string Decision, Guid? EntityId, string? Note, string OperatorId,
        string OperatorDisplayName, string IdentitySource, DateTimeOffset AtUtc, Guid AuditEntryId);

    public sealed record CandidateHistoryResponse(Guid CandidateId, IReadOnlyList<CandidateDecisionResponse> Decisions);

    public sealed record FaceFactorRequest;

    public sealed record ParameterResponse(string Name, string Value, string Source, string Rationale);

    public sealed record CatalogueResponse(string Version, string Sha256, double AppearanceFloor, long ConcurrencyToleranceMs,
        IReadOnlyList<ParameterResponse> Parameters, string PlausibilityDisclosure);

    public sealed record IdentityResponse(string Fingerprint, string ModelId, string ModelVersion);

    public sealed record TrackResponse(Guid TrackId, Guid ProcessingRunId, Guid VideoAssetId, Guid CameraId, string CameraCode, string CameraName,
        string ObjectClass, DateTimeOffset StartTimestampUtc, DateTimeOffset EndTimestampUtc, long StartOffsetMs, long EndOffsetMs,
        string? ThumbnailUrl, Guid? EntityId, bool Visible);

    public sealed record AppearanceFactor(double Score, double Floor, string Source);

    public sealed record PlausibilityFactor(string Verdict, bool SameCamera, long GapMs, long ConcurrencyToleranceMs, string Disclosure);

    public sealed record FaceAvailability(bool Available, string Note);

    public sealed record FactorsResponse(AppearanceFactor Appearance, PlausibilityFactor Plausibility, FaceAvailability? Face);

    public sealed record DecisionResponse(DateTimeOffset DecidedAtUtc, string OperatorId, string DisplayName, string IdentitySource, string? Note,
        Guid? AuditEntryId);

    public sealed record CandidateResponse(Guid CandidateId, string Label, string ObjectClass, string Status, string CatalogueVersion,
        string IdentityFingerprint, FactorsResponse Factors, DecisionResponse? Decision, Guid? EntityId, TrackResponse Lower, TrackResponse Higher);

    public sealed record ListResponse(string Label, CatalogueResponse Catalogue, IdentityResponse Identity, int Total, int Limit, int Offset,
        IReadOnlyList<CandidateResponse> Candidates);

    public sealed record PairCountResponse(Guid CameraId, string CameraCode, Guid OtherCameraId, string OtherCameraCode, string ObjectClass,
        int Open, int Confirmed, int Dismissed);

    public sealed record SummaryResponse(string Label, CatalogueResponse Catalogue, IdentityResponse? Identity, int Derivations,
        int PendingDerivations, IReadOnlyList<PairCountResponse> Pairs);

    public sealed record DecisionResult(string Label, CandidateResponse Candidate, Guid? EntityId, bool EntityCreated);

    public sealed record FaceThresholdResponse(double Cosine, string Provenance, bool CalibratedOnCctv);

    public sealed record FaceSideResponse(Guid TrackId, string State, string? Reason);

    public sealed record FaceBoxResponse(double X, double Y, double Width, double Height);

    public sealed record FacePairResponse(double Score, bool AboveThreshold, Guid LowerFaceId, Guid LowerObservationId, string? LowerEvidenceCropUrl,
        FaceBoxResponse LowerBox, Guid HigherFaceId, Guid HigherObservationId, string? HigherEvidenceCropUrl, FaceBoxResponse HigherBox);

    public sealed record FaceFactorResponse(string Label, string State, IdentityResponse Identity, FaceThresholdResponse ReferenceThreshold,
        FaceSideResponse Lower, FaceSideResponse Higher, FacePairResponse? Pair, string Note);

    public sealed record EntityResponse(string Label, Guid EntityId, string DisplayCode, string EntityType, string IdentityStatus,
        DateTimeOffset CreatedAtUtc, DateTimeOffset UpdatedAtUtc, IReadOnlyList<TrackResponse> Members, IReadOnlyList<CandidateResponse> Confirmations,
        string State, Guid? MergedIntoEntityId, IReadOnlyList<MembershipChangeResponse> History, IReadOnlyList<Guid> MergedFromEntityIds,
        IReadOnlyList<Guid> RelatedCandidateIds);

    // --- Reads -----------------------------------------------------------------------------------

    private static async Task<IResult> ListAsync(HttpRequest http, IEntityCandidateRepository repository, IEmbeddingRelease release,
        IFaceRelease faces, CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition) return Problem(409, NotConfiguredCode, "No embedding identity is configured.");
        if (http.Query.Keys.Any(key => !ListKeys.Contains(key)) || http.Query.Any(pair => pair.Value.Count != 1))
            return Problem(400, InvalidCode, "Unknown or repeated query key.");
        if (!TryParseQuery(http.Query, out var query)) return Problem(400, InvalidCode, "Invalid query value.");

        var catalogue = EntityCandidateCatalogue.Current;
        var page = await repository.ListAsync(query, definition.Identity.Fingerprint, catalogue.CatalogueVersion,
            faces.Resolution.Definition?.Identity.Fingerprint, cancellationToken);
        return Results.Ok(new ListResponse(EntityCandidateLabels.Candidates, Catalogue(catalogue), Identity(definition), page.Total, query.Limit,
            query.Offset, page.Items.Select(item => Candidate(item, catalogue, faces.Resolution.Definition is not null)).ToList()));
    }

    private static async Task<IResult> SummaryAsync(HttpRequest http, IEntityCandidateRepository repository, IEmbeddingRelease release,
        CancellationToken cancellationToken)
    {
        if (http.Query.Count > 0) return Problem(400, InvalidCode, "This endpoint takes no query parameters.");
        var catalogue = EntityCandidateCatalogue.Current;
        var definition = release.Resolution.Definition;
        var summary = await repository.SummarizeAsync(definition?.Identity.Fingerprint, catalogue.CatalogueVersion, cancellationToken);
        return Results.Ok(new SummaryResponse(EntityCandidateLabels.Candidates, Catalogue(catalogue), definition is null ? null : Identity(definition),
            summary.Derivations, summary.PendingDerivations,
            summary.Pairs.Select(pair => new PairCountResponse(pair.CameraId, pair.CameraCode, pair.OtherCameraId, pair.OtherCameraCode,
                pair.ObjectClass.ToString(), pair.Open, pair.Confirmed, pair.Dismissed)).ToList()));
    }

    private static async Task<IResult> GetAsync(Guid id, HttpRequest http, IEntityCandidateRepository repository, IFaceRelease faces,
        CancellationToken cancellationToken)
    {
        if (http.Query.Count > 0) return Problem(400, InvalidCode, "This endpoint takes no query parameters.");
        var view = await repository.GetAsync(id, faces.Resolution.Definition?.Identity.Fingerprint, cancellationToken);
        return view is null
            ? Problem(404, EntityCandidateFaceFactorService.NotFoundCode, "The candidate does not exist.")
            : Results.Ok(Candidate(view, EntityCandidateCatalogue.Current, faces.Resolution.Definition is not null));
    }

    private static async Task<IResult> GetEntityAsync(Guid id, HttpRequest http, IEntityCandidateRepository repository,
        CancellationToken cancellationToken)
    {
        if (http.Query.Count > 0) return Problem(400, InvalidCode, "This endpoint takes no query parameters.");
        var entity = await repository.GetEntityAsync(id, cancellationToken);
        if (entity is null) return Problem(404, "entity_not_found", "The Entity does not exist.");
        return Results.Ok(EntityBody(entity));
    }

    private static EntityResponse EntityBody(EntityView entity)
    {
        var catalogue = EntityCandidateCatalogue.Current;
        return new EntityResponse(EntityCandidateLabels.Entity, entity.EntityId, entity.DisplayCode, entity.EntityType.ToString(),
            nameof(IdentityStatus.Unknown), entity.CreatedAtUtc, entity.UpdatedAtUtc, entity.Members.Select(Track).ToList(),
            entity.Confirmations.Select(item => Candidate(item, catalogue, false)).ToList(), entity.State.ToString(), entity.MergedIntoEntityId,
            (entity.History ?? []).Select(change => new MembershipChangeResponse(change.Sequence, change.TrackId, change.EntityId,
                change.Change.ToString(), change.Cause.ToString(), change.CandidateId, change.Note, change.OperatorId, change.OperatorDisplayName,
                change.IdentitySource, change.AtUtc, change.AuditEntryId)).ToList(), entity.MergedFromEntityIds ?? [],
            entity.RelatedCandidateIds ?? []);
    }

    private static async Task<IResult> CandidateHistoryAsync(Guid id, HttpRequest http, IEntityCandidateRepository repository,
        CancellationToken cancellationToken)
    {
        if (http.Query.Count > 0) return Problem(400, InvalidCode, "This endpoint takes no query parameters.");
        var history = await repository.GetCandidateHistoryAsync(id, cancellationToken);
        if (history is null) return Problem(404, EntityCandidateFaceFactorService.NotFoundCode, "The candidate does not exist.");
        return Results.Ok(new CandidateHistoryResponse(id, history.Select(item => new CandidateDecisionResponse(item.Sequence,
            item.Decision.ToString(), item.EntityId, item.Note, item.OperatorId, item.OperatorDisplayName, item.IdentitySource, item.AtUtc,
            item.AuditEntryId)).ToList()));
    }

    // --- Corrections (ADR-027 §4) ----------------------------------------------------------------

    private static async Task<IResult> ReopenAsync(Guid id, DecisionRequest request, IEntityCandidateRepository repository, IAuditWriter audit,
        ICurrentOperator currentOperator, IEmbeddingRelease release, TimeProvider timeProvider, CancellationToken cancellationToken)
    {
        if (!ValidNote(request)) return Problem(400, DecisionInvalidCode, "The note is at most 500 characters.");
        if (release.Resolution.Definition is not { } definition) return Problem(409, NotConfiguredCode, "No embedding identity is configured.");
        var note = EntityCandidate.NormaliseNote(request.Note);
        var record = new AuditRecord("entities.candidate-reopened", SubjectCandidate, id.ToString("D"), new { candidateId = id, decision = "reopen", note });
        var result = await repository.ReopenAsync(id, note, Decider(currentOperator), token => audit.AppendInTransactionAsync(record, token),
            EntityCandidateCatalogue.Current, definition.Identity.Fingerprint, timeProvider.GetUtcNow(), cancellationToken);
        return result.RefusalCode switch
        {
            EntityCorrectionRules.CandidateNotDecided => Problem(409, result.RefusalCode, "The candidate is open; there is nothing to reopen."),
            EntityCorrectionRules.CandidateStillLinked => Results.Json(new
            {
                type = "about:blank",
                title = "Conflict",
                status = 409,
                code = result.RefusalCode,
                detail = "Both Tracks are still in one Entity; unlink one of them first.",
                entityId = result.EntityId,
            }, statusCode: 409, contentType: "application/problem+json"),
            _ => Decided(result, EntityCandidateCatalogue.Current),
        };
    }

    private static async Task<IResult> MergeAsync(Guid id, MergeRequest request, IEntityCandidateRepository repository, IAuditWriter audit,
        ICurrentOperator currentOperator, TimeProvider timeProvider, CancellationToken cancellationToken)
    {
        if (request.IntoEntityId is not { } into || into == Guid.Empty || !ValidNote(new DecisionRequest(request.Note)))
            return Problem(400, DecisionInvalidCode, "intoEntityId is required and the note is at most 500 characters.");
        var note = EntityCandidate.NormaliseNote(request.Note);
        var record = new AuditRecord("entities.merged", SubjectEntity, id.ToString("D"), new { entityId = id, intoEntityId = into, note });
        var result = await repository.MergeAsync(id, into, note, Decider(currentOperator), token => audit.AppendInTransactionAsync(record, token),
            EntityCandidateCatalogue.Current, timeProvider.GetUtcNow(), cancellationToken);
        return Corrected(result);
    }

    private static async Task<IResult> UnlinkAsync(Guid id, UnlinkRequest request, IEntityCandidateRepository repository, IAuditWriter audit,
        ICurrentOperator currentOperator, TimeProvider timeProvider, CancellationToken cancellationToken)
    {
        if (request.TrackId is not { } trackId || trackId == Guid.Empty || !ValidNote(new DecisionRequest(request.Note)))
            return Problem(400, DecisionInvalidCode, "trackId is required and the note is at most 500 characters.");
        var note = EntityCandidate.NormaliseNote(request.Note);
        var record = new AuditRecord("entities.track-unlinked", SubjectEntity, id.ToString("D"), new { entityId = id, trackId, note });
        var result = await repository.UnlinkAsync(id, trackId, note, Decider(currentOperator), token => audit.AppendInTransactionAsync(record, token),
            timeProvider.GetUtcNow(), cancellationToken);
        return Corrected(result);
    }

    private static IResult Corrected(EntityCorrectionResult result) => result.RefusalCode switch
    {
        null => Results.Ok(EntityBody(result.Entity!)),
        EntityCorrectionRules.EntityNotFound => Problem(404, result.RefusalCode, "The Entity does not exist."),
        EntityCorrectionRules.EntityNotActive => Problem(409, result.RefusalCode, "The Entity was merged into another and no longer changes."),
        EntityCorrectionRules.MergeInvalid => Problem(409, result.RefusalCode, "Only two different active Entities of one type can be merged."),
        EntityCorrectionRules.MergeSourceEmpty => Problem(409, result.RefusalCode,
            "The Entity to merge has no members; it is kept as the record of its decisions and there is nothing to move."),
        EntityCorrectionRules.TrackNotMember => Problem(409, result.RefusalCode, "The Track is not a member of this Entity."),
        EntityCorrectionRules.ChangedConcurrently => Problem(409, result.RefusalCode, "The Entities changed while merging; read them again."),
        EntityCorrectionRules.MergeImplausible => Results.Json(new
        {
            type = "about:blank",
            title = "Conflict",
            status = 409,
            code = result.RefusalCode,
            detail = "A member of one Entity cannot be the same object as a member of the other (time and camera).",
            conflictingTrackId = result.ConflictingTrackId,
            otherConflictingTrackId = result.OtherConflictingTrackId,
        }, statusCode: 409, contentType: "application/problem+json"),
        _ => Problem(409, result.RefusalCode, "The correction was refused."),
    };

    // --- Decisions -------------------------------------------------------------------------------

    private static async Task<IResult> ConfirmAsync(Guid id, DecisionRequest request, IEntityCandidateRepository repository, IAuditWriter audit,
        ICurrentOperator currentOperator, IEmbeddingRelease release, TimeProvider timeProvider, CancellationToken cancellationToken)
    {
        if (!ValidNote(request)) return Problem(400, DecisionInvalidCode, "The note is at most 500 characters.");
        if (release.Resolution.Definition is not { } definition) return Problem(409, NotConfiguredCode, "No embedding identity is configured.");
        var note = EntityCandidate.NormaliseNote(request.Note);
        var record = new AuditRecord("entities.candidate-confirmed", SubjectCandidate, id.ToString("D"), new { candidateId = id, decision = "confirm", note });
        var catalogue = EntityCandidateCatalogue.Current;
        var result = await repository.ConfirmAsync(id, note, Decider(currentOperator), token => audit.AppendInTransactionAsync(record, token),
            catalogue, definition.Identity.Fingerprint, timeProvider.GetUtcNow(), cancellationToken);
        return Decided(result, catalogue);
    }

    private static async Task<IResult> DismissAsync(Guid id, DecisionRequest request, IEntityCandidateRepository repository, IAuditWriter audit,
        ICurrentOperator currentOperator, IEmbeddingRelease release, TimeProvider timeProvider, CancellationToken cancellationToken)
    {
        if (!ValidNote(request)) return Problem(400, DecisionInvalidCode, "The note is at most 500 characters.");
        if (release.Resolution.Definition is not { } definition) return Problem(409, NotConfiguredCode, "No embedding identity is configured.");
        var note = EntityCandidate.NormaliseNote(request.Note);
        var record = new AuditRecord("entities.candidate-dismissed", SubjectCandidate, id.ToString("D"), new { candidateId = id, decision = "dismiss", note });
        var result = await repository.DismissAsync(id, note, Decider(currentOperator), token => audit.AppendInTransactionAsync(record, token),
            EntityCandidateCatalogue.Current, definition.Identity.Fingerprint, timeProvider.GetUtcNow(), cancellationToken);
        return Decided(result, EntityCandidateCatalogue.Current);
    }

    private static async Task<IResult> FaceFactorAsync(Guid id, FaceFactorRequest request, EntityCandidateFaceFactorService service, IAuditWriter audit,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        try
        {
            // A 1:1 biometric comparison: audited like a face search, ids only (ADR-022 §6, ADR-023 §5).
            var (result, _) = await audit.RecordAsync(new AuditRecord("entities.candidate-face-compared", SubjectCandidate, id.ToString("D"),
                    new { candidateId = id }),
                async token =>
                {
                    var computed = await service.ComputeAsync(id, token);
                    return computed.ErrorCode is null ? computed : throw new Refusal(computed.HttpStatus, computed.ErrorCode);
                },
                cancellationToken);
            var definition = result.Definition!;
            var threshold = definition.ReferenceThreshold.Cosine;
            var pair = result.Pair is { } found
                ? new FacePairResponse(found.Score, found.Score >= threshold, found.LowerFaceId, found.LowerObservationId, CropUrl(found.LowerArtifactId),
                    Box(found.LowerBox), found.HigherFaceId, found.HigherObservationId, CropUrl(found.HigherArtifactId), Box(found.HigherBox))
                : null;
            return Results.Ok(new FaceFactorResponse(FaceOperatorEndpoints.Label, pair is null ? FaceStates.Unknown : FaceStates.Observed,
                new IdentityResponse(definition.Identity.Fingerprint, definition.Identity.ModelId, definition.Identity.ModelVersion),
                new FaceThresholdResponse(threshold, definition.ReferenceThreshold.Provenance, CalibratedOnCctv: false),
                new FaceSideResponse(result.Lower!.TrackId, result.Lower.State, result.Lower.Reason),
                new FaceSideResponse(result.Higher!.TrackId, result.Higher.State, result.Higher.Reason),
                pair,
                "A separate factor: it takes no part in generating or ordering candidates, and is not stored."));
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
    }

    // --- Shared ------------------------------------------------------------------------------

    private sealed class Refusal(int status, string code) : Exception("The Entity operation was refused.")
    {
        public IResult Result => Problem(status, code, Message);
    }

    private static IResult Decided(EntityDecisionResult result, EntityCandidateCatalogueDefinition catalogue)
    {
        if (result.RefusalCode is null)
            return Results.Ok(new DecisionResult(EntityCandidateLabels.Entity, Candidate(result.Candidate!, catalogue, false), result.EntityId,
                result.EntityCreated));
        return result.RefusalCode switch
        {
            EntityCandidateFaceFactorService.NotFoundCode => Problem(404, result.RefusalCode, "The candidate does not exist."),
            EntityConfirmationRules.AlreadyDecided => Results.Json(new
            {
                type = "about:blank",
                title = "Conflict",
                status = 409,
                code = result.RefusalCode,
                detail = "The candidate has already been decided.",
                candidate = result.Candidate is null ? null : Candidate(result.Candidate, catalogue, false),
            }, statusCode: 409, contentType: "application/problem+json"),
            EntityConfirmationRules.ExtensionImplausible => Results.Json(new
            {
                type = "about:blank",
                title = "Conflict",
                status = 409,
                code = result.RefusalCode,
                detail = "The Track would join an Entity whose member it cannot be plausible against (time and camera).",
                entityId = result.EntityId,
                conflictingTrackId = result.ConflictingTrackId,
            }, statusCode: 409, contentType: "application/problem+json"),
            EntityConfirmationRules.Superseded => Problem(409, result.RefusalCode,
                "The candidate belongs to an earlier catalogue version or embedding identity; only current candidates are decided."),
            EntityConfirmationRules.MergeUnsupported => Problem(409, result.RefusalCode,
                "The two Tracks belong to different Entities; merge the Entities explicitly (POST /api/entities/{id}/merge)."),
            _ => Problem(409, result.RefusalCode, "A Track of the candidate is no longer in the latest run of its video."),
        };
    }

    private static bool ValidNote(DecisionRequest? request) =>
        request is not null && (EntityCandidate.NormaliseNote(request.Note)?.Length ?? 0) <= EntityCandidate.MaximumNoteLength;

    private static EntityCandidateDecider Decider(ICurrentOperator currentOperator)
    {
        var actor = currentOperator.Required;
        return new EntityCandidateDecider(actor.OperatorId, actor.DisplayName, actor.IdentitySource);
    }

    private static bool TryParseQuery(IQueryCollection values, out EntityCandidateListQuery query)
    {
        query = new EntityCandidateListQuery(EntityCandidateStatus.Open, null, null, null, null, DefaultLimit, 0);
        var status = EntityCandidateStatus.Open;
        if (values.TryGetValue("status", out var statusText))
        {
            EntityCandidateStatus? parsed = statusText.ToString() switch
            {
                "open" => EntityCandidateStatus.Open,
                "confirmed" => EntityCandidateStatus.Confirmed,
                "dismissed" => EntityCandidateStatus.Dismissed,
                _ => null,
            };
            if (parsed is not { } known) return false;
            status = known;
        }

        ObjectClass? objectClass = null;
        if (values.TryGetValue("objectClass", out var classText))
        {
            if (classText.ToString() is not ("Person" or "Vehicle")) return false;
            objectClass = Enum.Parse<ObjectClass>(classText.ToString());
        }

        if (!TryGuid(values, "cameraId", out var camera) || !TryGuid(values, "otherCameraId", out var other) || !TryGuid(values, "trackId", out var track))
            return false;
        if (other is not null && camera is null) return false;
        var limit = DefaultLimit;
        var offset = 0;
        if (values.TryGetValue("limit", out var limitText) &&
            (!int.TryParse(limitText, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out limit) ||
             limit is < 1 or > MaximumLimit))
            return false;
        if (values.TryGetValue("offset", out var offsetText) &&
            (!int.TryParse(offsetText, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out offset) ||
             offset > MaximumOffset))
            return false;
        query = new EntityCandidateListQuery(status, objectClass, camera, other, track, limit, offset);
        return true;
    }

    private static bool TryGuid(IQueryCollection values, string key, out Guid? value)
    {
        value = null;
        if (!values.TryGetValue(key, out var text)) return true;
        if (!Guid.TryParseExact(text.ToString(), "D", out var parsed) || parsed == Guid.Empty) return false;
        value = parsed;
        return true;
    }

    private static CandidateResponse Candidate(EntityCandidateView view, EntityCandidateCatalogueDefinition catalogue, bool facesConfigured)
    {
        var face = view.ObjectClass != ObjectClass.Person
            ? null
            : new FaceAvailability(view.FaceFactorAvailable, view.FaceFactorAvailable
                ? "Both Tracks have a usable face; the face factor is computed on request and audited."
                : facesConfigured ? "Unknown: at least one Track has no usable face (the face status request gives each Track's reason)." : "Unknown: no face release is configured.");
        return new CandidateResponse(view.CandidateId, EntityCandidateLabels.Candidates, view.ObjectClass.ToString(), Status(view.Status),
            view.CatalogueVersion, view.IdentityFingerprint,
            new FactorsResponse(
                new AppearanceFactor(view.AppearanceScore, catalogue.AppearanceFloor, "SigLIP 2 Track vectors (ADR-021); similarity, not identity"),
                new PlausibilityFactor("plausible", view.SameCamera, view.GapMs, catalogue.ConcurrencyToleranceMs, EntityCandidateLabels.PlausibilityDisclosure),
                face),
            view.Decision is { } decision
                ? new DecisionResponse(decision.DecidedAtUtc, decision.OperatorId, decision.DisplayName, decision.IdentitySource, decision.Note,
                    decision.AuditEntryId)
                : null,
            view.EntityId, Track(view.Lower), Track(view.Higher));
    }

    private static TrackResponse Track(EntityTrackView view) => new(view.TrackId, view.ProcessingRunId, view.VideoAssetId, view.CameraId,
        view.CameraCode, view.CameraName, view.ObjectClass.ToString(), view.StartTimestampUtc, view.EndTimestampUtc, view.StartOffsetMs,
        view.EndOffsetMs, CropUrl(view.ThumbnailArtifactId), view.EntityId, view.Visible);

    private static CatalogueResponse Catalogue(EntityCandidateCatalogueDefinition catalogue) => new(catalogue.CatalogueVersion, catalogue.Sha256,
        catalogue.AppearanceFloor, catalogue.ConcurrencyToleranceMs,
        catalogue.Parameters.Select(item => new ParameterResponse(item.Name, item.Value, item.Source, item.Rationale)).ToList(),
        EntityCandidateLabels.PlausibilityDisclosure);

    private static IdentityResponse Identity(EmbeddingReleaseDefinition definition) =>
        new(definition.Identity.Fingerprint, definition.Identity.ModelId, definition.Identity.ModelVersion);

    private static string Status(EntityCandidateStatus status) => status switch
    {
        EntityCandidateStatus.Confirmed => "confirmed",
        EntityCandidateStatus.Dismissed => "dismissed",
        _ => "open",
    };

    private static FaceBoxResponse Box(FaceBox box) => new(Math.Round(box.X, 2), Math.Round(box.Y, 2), Math.Round(box.Width, 2), Math.Round(box.Height, 2));

    private static string? CropUrl(Guid? artifactId) => artifactId is { } id ? $"/api/artifacts/{id}/content" : null;

    private static IResult Problem(int status, string code, string detail) => FaceEndpoints.Problem(status, code, detail);
}
