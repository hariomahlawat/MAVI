using System.Text.Json;
using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Faces;
using Mavi.Api.Identity;
using Mavi.Application.Modules.Identity;
using Mavi.Domain.Common;
using Mavi.Domain.Faces;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The operator surface of face intelligence (PoC S6; ADR-022 §1, §4–§7). Every route requires
/// <see cref="OperatorPolicy"/> (so it is refused with <c>Identity:Mode=disabled</c>) and every state change is JSON;
/// each mutation and each biometric search writes one audit row through <see cref="IAuditWriter"/> in its
/// transaction, with ids and counts only: no vector, image or gallery label (ADR-022 §6). Every result is a
/// candidate with its score and the reference threshold, never identity; nothing stores a match.
/// </summary>
public static class FaceOperatorEndpoints
{
    public const string NotConfiguredCode = "faces_not_configured";
    public const string Label = "Face candidates — not identification — Development";
    public const string NoGalleryCandidateMessage = "No gallery candidate above the threshold";
    public const string QueryInvalidCode = "face_query_image_invalid";
    public const string QueueFullCode = "face_query_queue_full";
    public const string SubjectFace = "face";
    public const string SubjectCamera = "camera";
    public const string SubjectGallery = "face-gallery-entry";
    public const string SubjectQuery = "face-query";

    public static IEndpointRouteBuilder MapFaceOperatorEndpoints(this IEndpointRouteBuilder endpoints)
    {
        ArgumentNullException.ThrowIfNull(endpoints);
        endpoints.MapPut("/api/cameras/{id:guid}/face-analysis", SetCameraAsync).RequireAuthorization(OperatorPolicy.Name);
        endpoints.MapGet("/api/tracks/{id:guid}/faces", TrackFacesAsync).RequireAuthorization(OperatorPolicy.Name);
        var faces = endpoints.MapGroup("/api/faces").RequireAuthorization(OperatorPolicy.Name);
        faces.MapPost("/queries", UploadQueryAsync);
        faces.MapGet("/queries/{id:guid}", GetQueryAsync);
        faces.MapPost("/search", SearchAsync);
        faces.MapPost("/gallery/compare", CompareAsync);
        faces.MapGet("/gallery", ListGalleryAsync);
        faces.MapPost("/gallery", EnrolAsync);
        faces.MapPatch("/gallery/{id:guid}", UpdateGalleryAsync);
        faces.MapPost("/gallery/{id:guid}/templates", AddTemplateAsync);
        faces.MapPost("/gallery/{id:guid}/templates/{templateId:guid}/delete", DeleteTemplateAsync);
        faces.MapPost("/gallery/{id:guid}/delete", DeleteGalleryAsync);
        return endpoints;
    }

    // --- Requests and responses ------------------------------------------------------------------

    public sealed record CameraFaceAnalysisRequest(bool? Enabled);

    public sealed record FaceSourceRequest(Guid? FaceId, Guid? QueryId, int? FaceIndex)
    {
        public FaceSource ToSource() => new(FaceId, QueryId, FaceIndex);
    }

    public sealed record FaceQueryUploadRequest(string? ImageBase64, string? MimeType);

    public sealed record FaceSearchRequest(FaceSourceRequest? Source, int? K, string? Snapshot);

    public sealed record FaceCompareRequest(FaceSourceRequest? Source);

    public sealed record GalleryEnrolRequest(string? Label, string? Note, FaceSourceRequest? Source);

    public sealed record GalleryTemplateRequest(FaceSourceRequest? Source);

    public sealed record IdentityResponse(string Fingerprint, string ModelId, string ModelVersion);

    public sealed record ThresholdResponse(double Cosine, string Provenance, bool CalibratedOnCctv);

    public sealed record BoxResponse(double X, double Y, double Width, double Height);

    public sealed record TrackFaceResponse(Guid FaceId, Guid ObservationId, string? EvidenceCropUrl, BoxResponse Box,
        IReadOnlyList<double[]> Landmarks, double Score, bool Usable);

    public sealed record TrackFacesResponse(string Label, string State, string? Reason, IdentityResponse? Identity,
        ThresholdResponse? ReferenceThreshold, IReadOnlyList<TrackFaceResponse> Faces);

    public sealed record QueryFaceResponse(int FaceIndex, BoxResponse Box, double Score, bool Usable, string? ThumbnailDataUrl);

    public sealed record QueryResponse(string Label, Guid QueryId, string Status, string? FailureCode, DateTimeOffset PurgeAfterUtc,
        IReadOnlyList<QueryFaceResponse> Faces);

    public sealed record CandidateResponse(int Rank, Guid TrackId, Guid ProcessingRunId, Guid CameraId, string CameraName,
        DateTimeOffset StartTimestampUtc, double Score, bool AboveThreshold, Guid FaceId, Guid ObservationId, string? EvidenceCropUrl,
        BoxResponse Box);

    public sealed record SearchResponse(string Label, IdentityResponse Identity, ThresholdResponse ReferenceThreshold, string Snapshot,
        DateTimeOffset SnapshotUtc, IReadOnlyList<CandidateResponse> Candidates);

    public sealed record GalleryCandidateResponse(Guid EnrolledPersonId, string Label, double Score, bool AboveThreshold);

    public sealed record CompareResponse(string Label, IdentityResponse Identity, ThresholdResponse ReferenceThreshold,
        IReadOnlyList<GalleryCandidateResponse> Candidates, string? Message);

    public sealed record GalleryTemplateResponse(Guid TemplateId, string SourceKind, Guid? SourceFaceId, Guid? SourceObservationId,
        string? EvidenceCropUrl, BoxResponse? Box, string? ThumbnailDataUrl, DateTimeOffset CreatedAtUtc);

    public sealed record GalleryEntryResponse(Guid EnrolledPersonId, string Label, string? Note, DateTimeOffset CreatedAtUtc,
        DateTimeOffset UpdatedAtUtc, IReadOnlyList<GalleryTemplateResponse> Templates);

    // --- Camera opt-in ---------------------------------------------------------------------------

    private static async Task<IResult> SetCameraAsync(Guid id, CameraFaceAnalysisRequest request, IFaceRepository repository,
        IAuditWriter audit, CancellationToken cancellationToken)
    {
        if (request.Enabled is not { } enabled) return Problem(400, "face_camera_switch_invalid", "enabled is required.");
        try
        {
            var (deleted, _) = await audit.RecordAsync(new AuditRecord(enabled ? "faces.camera-opted-in" : "faces.camera-opted-out",
                    SubjectCamera, id.ToString("D"), new { cameraId = id, enabled }),
                async token => await repository.SetCameraFaceAnalysisAsync(id, enabled, token) ?? throw new Refusal(404, "camera_not_found"),
                cancellationToken);
            return Results.Ok(new { cameraId = id, faceAnalysisEnabled = enabled, faceAnalysesDeleted = deleted });
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
    }

    // --- Track faces -----------------------------------------------------------------------------

    private static async Task<IResult> TrackFacesAsync(Guid id, HttpRequest http, IFaceRepository repository, IFaceRelease release,
        CancellationToken cancellationToken)
    {
        if (http.Query.Count > 0) return Problem(400, "face_query_invalid", "This endpoint takes no query parameters.");
        if (release.Resolution.Definition is not { } definition)
            return Results.Ok(new TrackFacesResponse(Label, "notConfigured", null, null, null, []));
        var view = await repository.GetTrackFacesAsync(id, definition.Identity.Fingerprint, cancellationToken);
        if (view is null) return Problem(404, "track_not_found", "The Track does not exist.");
        return Results.Ok(new TrackFacesResponse(Label, view.State, view.Reason, Identity(definition), Threshold(definition),
            view.Faces.Select(face => new TrackFaceResponse(face.FaceId, face.ObservationId, CropUrl(face.ArtifactId), Box(face.Box),
                Landmarks(face.Landmarks), face.Score, face.Usable)).ToList()));
    }

    // --- Transient query images ------------------------------------------------------------------

    private static async Task<IResult> UploadQueryAsync(FaceQueryUploadRequest request, IFaceRepository repository, IFaceRelease release,
        IOptions<FaceOptions> options, IAuditWriter audit, CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition) return NotConfigured();
        if (request.MimeType is not { } mime || !FaceQuery.MimeTypes.Contains(mime) || request.ImageBase64 is not { Length: > 0 } encoded ||
            encoded.Length > (definition.QueryImageMaximumBytes + 2) / 3 * 4)
            return Problem(400, QueryInvalidCode, "A JPEG or PNG image of at most the configured size, base64 encoded, is required.");
        byte[] image;
        try
        {
            image = Convert.FromBase64String(encoded);
        }
        catch (FormatException)
        {
            return Problem(400, QueryInvalidCode, "The image is not valid base64.");
        }

        var signatureMatches = mime == "image/jpeg" ? image is [0xFF, 0xD8, 0xFF, ..] : image is [0x89, 0x50, 0x4E, 0x47, ..];
        if (image.Length is < 1 || image.Length > definition.QueryImageMaximumBytes || !signatureMatches)
            return Problem(400, QueryInvalidCode, "The image is not a JPEG or PNG of at most the configured size.");

        try
        {
            // The id is fixed before the mutation so the audit row names the query it created (ADR-022 §6).
            var queryId = Guid.CreateVersion7();
            var (query, _) = await audit.RecordAsync(new AuditRecord("faces.query-uploaded", SubjectQuery, queryId.ToString("D"),
                    new { sizeBytes = image.Length, mimeType = mime }),
                token => repository.CreateQueryAsync(queryId, definition.Identity.Fingerprint, image, mime, options.Value.MaximumPendingQueries, token),
                cancellationToken);
            return Results.Accepted($"/api/faces/queries/{query.Id}", new { queryId = query.Id, status = "pending", purgeAfterUtc = query.PurgeAfterUtc });
        }
        catch (FaceQueryQueueFullException)
        {
            return Problem(503, QueueFullCode, "Too many query images wait for the face worker; retry later.");
        }
    }

    private static async Task<IResult> GetQueryAsync(Guid id, IFaceRepository repository, CancellationToken cancellationToken)
    {
        var view = await repository.GetQueryAsync(id, cancellationToken);
        if (view is null) return Problem(404, FaceQuery.NotFoundCode, "The query does not exist or has been purged.");
        return Results.Ok(new QueryResponse(Label, view.QueryId, StatusToken(view.Status), view.FailureCode, view.PurgeAfterUtc,
            view.Faces.Select(face => new QueryFaceResponse(face.FaceIndex, Box(face.Box), Math.Round(face.Score, 4), face.Usable,
                view.Thumbnails.TryGetValue(face.FaceIndex, out var thumbnail) && thumbnail is not null
                    ? "data:image/jpeg;base64," + Convert.ToBase64String(thumbnail)
                    : null)).ToList()));
    }

    // --- Find this face and the gallery comparison -------------------------------------------------

    private static async Task<IResult> SearchAsync(FaceSearchRequest request, FaceSearchService search, IFaceRelease release, IAuditWriter audit,
        CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition) return NotConfigured();
        if (request.Source is not { } sourceRequest) return Problem(400, FaceSearchService.InvalidCode, "A source face is required.");
        var source = sourceRequest.ToSource();
        try
        {
            var (result, _) = await audit.RecordAsync(new AuditRecord("faces.search", SubjectFace, source.Canonical,
                    new { source = source.Canonical, k = request.K, replay = request.Snapshot is not null }),
                async token =>
                {
                    var found = await search.FindAsync(definition, source, request.K, request.Snapshot, token);
                    return found.ErrorCode is null ? found : throw new Refusal(found.HttpStatus, found.ErrorCode);
                },
                cancellationToken);
            var threshold = definition.ReferenceThreshold.Cosine;
            return Results.Ok(new SearchResponse(Label, Identity(definition), Threshold(definition), result.Snapshot!, result.SnapshotUtc!.Value,
                result.Candidates.Select((row, index) => new CandidateResponse(index + 1, row.TrackId, row.ProcessingRunId, row.CameraId,
                    row.CameraName, row.StartTimestampUtc, row.Score, row.Score >= threshold, row.FaceId, row.ObservationId,
                    CropUrl(row.ArtifactId), Box(row.Box))).ToList()));
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
    }

    private static async Task<IResult> CompareAsync(FaceCompareRequest request, FaceSearchService search, IFaceRelease release, IAuditWriter audit,
        CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition) return NotConfigured();
        if (request.Source is not { } sourceRequest) return Problem(400, FaceSearchService.InvalidCode, "A source face is required.");
        var source = sourceRequest.ToSource();
        try
        {
            var (result, _) = await audit.RecordAsync(new AuditRecord("faces.gallery-compared", SubjectFace, source.Canonical,
                    new { source = source.Canonical }),
                async token =>
                {
                    var compared = await search.CompareAsync(definition, source, token);
                    return compared.ErrorCode is null ? compared : throw new Refusal(compared.HttpStatus, compared.ErrorCode);
                },
                cancellationToken);
            return Results.Ok(new CompareResponse(Label, Identity(definition), Threshold(definition),
                result.Candidates.Select(item => new GalleryCandidateResponse(item.EnrolledPersonId, item.Label, item.Score, true)).ToList(),
                result.Candidates.Count == 0 ? NoGalleryCandidateMessage : null));
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
    }

    // --- Gallery ---------------------------------------------------------------------------------

    private static async Task<IResult> ListGalleryAsync(IFaceRepository repository, CancellationToken cancellationToken)
    {
        var entries = await repository.ListGalleryAsync(cancellationToken);
        return Results.Ok(new { label = Label, entries = entries.Select(Entry).ToList() });
    }

    private static async Task<IResult> EnrolAsync(GalleryEnrolRequest request, IFaceRepository repository, IFaceRelease release, IAuditWriter audit,
        CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition) return NotConfigured();
        if (request.Source is not { } sourceRequest || !sourceRequest.ToSource().IsValid)
            return Problem(400, FaceSearchService.InvalidCode, "A source face is required.");
        var source = sourceRequest.ToSource();
        try
        {
            // The id is fixed before the mutation so the audit row names the entry it created (ADR-022 §6).
            var enrolledPersonId = Guid.CreateVersion7();
            var (id, _) = await audit.RecordAsync(new AuditRecord("faces.gallery-enrolled", SubjectGallery, enrolledPersonId.ToString("D"),
                    new { source = source.Canonical }),
                async token => await repository.EnrolAsync(enrolledPersonId, request.Label, request.Note,
                    await ResolveOrRefuseAsync(repository, source, definition, token), definition.Identity.Fingerprint, token),
                cancellationToken);
            return Results.Created($"/api/faces/gallery/{id}", new { enrolledPersonId = id });
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
        catch (DomainValidationException exception)
        {
            return Problem(400, exception.Code, exception.Message);
        }
    }

    private static async Task<IResult> UpdateGalleryAsync(Guid id, JsonElement body, IFaceRepository repository, IAuditWriter audit,
        CancellationToken cancellationToken)
    {
        if (body.ValueKind != JsonValueKind.Object ||
            body.EnumerateObject().Any(property => property.Name is not ("label" or "note")))
            return Problem(400, EnrolledPerson.InvalidCode, "Only label and note can be updated.");
        string? label = null;
        string? note = null;
        var noteGiven = false;
        foreach (var property in body.EnumerateObject())
        {
            if (property.Value.ValueKind is not (JsonValueKind.String or JsonValueKind.Null))
                return Problem(400, EnrolledPerson.InvalidCode, "label and note are strings.");
            if (property.Name == "label")
            {
                label = property.Value.GetString() ?? throw new InvalidOperationException();
            }
            else
            {
                note = property.Value.GetString();
                noteGiven = true;
            }
        }

        if (label is null && !noteGiven) return Problem(400, EnrolledPerson.InvalidCode, "Nothing to update.");
        try
        {
            await audit.RecordAsync(new AuditRecord("faces.gallery-updated", SubjectGallery, id.ToString("D"),
                    new { enrolledPersonId = id, labelChanged = label is not null, noteChanged = noteGiven }),
                async token => await repository.UpdateGalleryEntryAsync(id, label, note, noteGiven, token)
                    ? true
                    : throw new Refusal(404, EnrolledPerson.NotFoundCode),
                cancellationToken);
            return Results.Ok(Entry((await repository.GetGalleryEntryAsync(id, cancellationToken))!));
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
        catch (DomainValidationException exception)
        {
            return Problem(400, exception.Code, exception.Message);
        }
    }

    private static async Task<IResult> AddTemplateAsync(Guid id, GalleryTemplateRequest request, IFaceRepository repository, IFaceRelease release,
        IAuditWriter audit, CancellationToken cancellationToken)
    {
        if (release.Resolution.Definition is not { } definition) return NotConfigured();
        if (request.Source is not { } sourceRequest || !sourceRequest.ToSource().IsValid)
            return Problem(400, FaceSearchService.InvalidCode, "A source face is required.");
        var source = sourceRequest.ToSource();
        try
        {
            var (templateId, _) = await audit.RecordAsync(new AuditRecord("faces.gallery-template-added", SubjectGallery, id.ToString("D"),
                    new { enrolledPersonId = id, source = source.Canonical }),
                async token => await repository.AddTemplateAsync(id, await ResolveOrRefuseAsync(repository, source, definition, token),
                    definition.Identity.Fingerprint, token) ?? throw new Refusal(404, EnrolledPerson.NotFoundCode),
                cancellationToken);
            return Results.Created($"/api/faces/gallery/{id}", new { enrolledPersonId = id, templateId });
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
    }

    private static async Task<IResult> DeleteTemplateAsync(Guid id, Guid templateId, JsonElement body, IFaceRepository repository, IAuditWriter audit,
        CancellationToken cancellationToken)
    {
        if (body.ValueKind != JsonValueKind.Object || body.EnumerateObject().Any())
            return Problem(400, EnrolledPerson.InvalidCode, "The body is an empty JSON object.");
        try
        {
            await audit.RecordAsync(new AuditRecord("faces.gallery-template-removed", SubjectGallery, id.ToString("D"),
                    new { enrolledPersonId = id, templateId }),
                async token => await repository.DeleteTemplateAsync(id, templateId, token) ? true : throw new Refusal(404, EnrolledPerson.NotFoundCode),
                cancellationToken);
            return Results.NoContent();
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
    }

    private static async Task<IResult> DeleteGalleryAsync(Guid id, JsonElement body, IFaceRepository repository, IAuditWriter audit,
        CancellationToken cancellationToken)
    {
        if (body.ValueKind != JsonValueKind.Object || body.EnumerateObject().Any())
            return Problem(400, EnrolledPerson.InvalidCode, "The body is an empty JSON object.");
        try
        {
            await audit.RecordAsync(new AuditRecord("faces.gallery-deleted", SubjectGallery, id.ToString("D"), new { enrolledPersonId = id }),
                async token => await repository.DeleteGalleryEntryAsync(id, token) ? true : throw new Refusal(404, EnrolledPerson.NotFoundCode),
                cancellationToken);
            return Results.NoContent();
        }
        catch (Refusal refusal)
        {
            return refusal.Result;
        }
    }

    // --- Shared ------------------------------------------------------------------------------

    /// <summary>Thrown inside an audited mutation to refuse it: the transaction rolls back and no audit row remains.</summary>
    private sealed class Refusal(int status, string code) : Exception("The face operation was refused.")
    {
        public IResult Result => Problem(status, code, Message);
    }

    private static async Task<ResolvedFace> ResolveOrRefuseAsync(IFaceRepository repository, FaceSource source, FaceReleaseDefinition definition,
        CancellationToken cancellationToken)
    {
        var resolved = await repository.ResolveAsync(source, definition.Identity.Fingerprint, cancellationToken);
        return resolved.Face ?? throw new Refusal(FaceSearchService.StatusFor(resolved.RefusalCode), resolved.RefusalCode!);
    }

    private static GalleryEntryResponse Entry(GalleryEntryView view) => new(view.EnrolledPersonId, view.Label, view.Note, view.CreatedAtUtc,
        view.UpdatedAtUtc, view.Templates.Select(template => new GalleryTemplateResponse(template.TemplateId,
            template.SourceKind == EnrolledFaceSource.Evidence ? "evidence" : "query", template.SourceFaceId, template.SourceObservationId,
            CropUrl(template.SourceArtifactId), template.Box is null ? null : Box(template.Box),
            template.Thumbnail is null ? null : "data:image/jpeg;base64," + Convert.ToBase64String(template.Thumbnail),
            template.CreatedAtUtc)).ToList());

    private static IdentityResponse Identity(FaceReleaseDefinition definition) =>
        new(definition.Identity.Fingerprint, definition.Identity.ModelId, definition.Identity.ModelVersion);

    private static ThresholdResponse Threshold(FaceReleaseDefinition definition) =>
        new(definition.ReferenceThreshold.Cosine, definition.ReferenceThreshold.Provenance, CalibratedOnCctv: false);

    private static BoxResponse Box(FaceBox box) => new(Math.Round(box.X, 2), Math.Round(box.Y, 2), Math.Round(box.Width, 2), Math.Round(box.Height, 2));

    private static List<double[]> Landmarks(float[] values) =>
        Enumerable.Range(0, values.Length / 2).Select(index => new[] { Math.Round(values[2 * index], 2), Math.Round(values[2 * index + 1], 2) }).ToList();

    private static string? CropUrl(Guid? artifactId) => artifactId is { } id ? $"/api/artifacts/{id}/content" : null;

    private static string StatusToken(FaceQueryStatus status) => status switch
    {
        FaceQueryStatus.Pending or FaceQueryStatus.Running => "pending",
        FaceQueryStatus.Completed => "completed",
        _ => "failed",
    };

    private static IResult NotConfigured() => Problem(409, NotConfiguredCode, "No face identity is configured.");

    private static IResult Problem(int status, string code, string detail) => FaceEndpoints.Problem(status, code, detail);
}
