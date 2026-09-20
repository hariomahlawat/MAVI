using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Contracts.Api.Scene;
using Mavi.Domain.Common;
using Mavi.Domain.Scene;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Api.Endpoints;

/// <summary>
/// Reads and saves a camera's scene geometry.
/// </summary>
/// <remarks>
/// A save creates the next revision and activates it in one step; nothing here ever
/// edits a revision that already exists. The analytics lifecycle endpoints that the
/// contracts also describe are deliberately absent until the lifecycle itself exists.
/// </remarks>
public static class SceneEndpoints
{
    // Route registration
    public static IEndpointRouteBuilder MapSceneEndpoints(this IEndpointRouteBuilder endpoints)
    {
        var scenes = endpoints.MapGroup("/api/cameras/{cameraId:guid}/scene");
        scenes.MapGet("/", GetAsync).WithName("GetCameraScene");
        scenes.MapPut("/", SaveAsync);
        scenes.MapGet("/revisions/{revisionNumber:int}", GetRevisionAsync);
        return endpoints;
    }

    // Handlers
    private static async Task<IResult> GetAsync(
        Guid cameraId,
        SceneConfigurationService service,
        CancellationToken cancellationToken)
    {
        var scene = await service.GetAsync(cameraId, cancellationToken);
        return scene is null
            ? Problem(StatusCodes.Status404NotFound, CameraErrorCodes.NotFound, "Camera was not found.")
            : Results.Ok(ToResponse(scene));
    }

    private static async Task<IResult> GetRevisionAsync(
        Guid cameraId,
        int revisionNumber,
        SceneConfigurationService service,
        CancellationToken cancellationToken)
    {
        // A missing camera is reported as such rather than as a missing revision, so
        // the answer names what the caller actually got wrong.
        if (await service.GetAsync(cameraId, cancellationToken) is null)
        {
            return Problem(StatusCodes.Status404NotFound, CameraErrorCodes.NotFound, "Camera was not found.");
        }

        var revision = await service.GetRevisionAsync(cameraId, revisionNumber, cancellationToken);
        return revision is null
            ? Problem(
                StatusCodes.Status404NotFound,
                SceneErrorCodes.RevisionNotFound,
                "Scene revision was not found.")
            : Results.Ok(ToResponse(revision, cameraId));
    }

    private static async Task<IResult> SaveAsync(
        Guid cameraId,
        SaveSceneRequest request,
        SceneConfigurationService service,
        CancellationToken cancellationToken)
    {
        try
        {
            var revision = await service.SaveAsync(
                new SaveSceneCommand(cameraId, request.ExpectedRevisionNumber, ToDraft(request)),
                cancellationToken);
            if (revision is null)
            {
                return Problem(StatusCodes.Status404NotFound, CameraErrorCodes.NotFound, "Camera was not found.");
            }

            var response = ToResponse(revision, cameraId);
            return Results.Created(
                $"/api/cameras/{cameraId}/scene/revisions/{response.RevisionNumber}",
                response);
        }
        catch (DomainValidationException exception)
        {
            return Problem(StatusCodes.Status400BadRequest, exception.Code, exception.Message);
        }
        catch (SceneRevisionConflictException exception)
        {
            return Problem(StatusCodes.Status409Conflict, SceneRevisionConflictException.Code, exception.Message);
        }
        catch (SceneConcurrentSaveException)
        {
            // Another request for this camera committed between our read and our write.
            // The caller is in exactly the position a stale revision number describes.
            return Problem(
                StatusCodes.Status409Conflict,
                SceneErrorCodes.RevisionConflict,
                "The scene was saved by another request.");
        }
    }

    // Request mapping
    //
    // A non-nullable element type is an annotation, not a guarantee: a JSON array may
    // still carry a null entry, and the deserializer will put it in the list. Every
    // element is therefore checked before it is read, so a null zone or line is a
    // validation failure rather than a dereference.
    private static SceneRevisionDraft ToDraft(SaveSceneRequest request) => new(
        request.Note,
        request.ReferenceFrameVideoAssetId,
        request.ReferenceFrameOffsetMs,
        [.. (request.Zones ?? []).Select(ToDraft)],
        [.. (request.TripLines ?? []).Select(ToDraft)]);

    private static SceneZoneDraft ToDraft(SaveSceneZoneRequest? request)
    {
        Require(request);
        return new SceneZoneDraft(
            request.ZoneId,
            request.Name,
            request.Kind,
            request.Enabled ?? true,
            request.Vertices is null ? null : [.. request.Vertices.Select(ToVertexDraft)],
            request.LoiteringThresholdSeconds);
    }

    private static TripLineDraft ToDraft(SaveSceneTripLineRequest? request)
    {
        Require(request);
        return new TripLineDraft(
            request.LineId,
            request.Name,
            request.Enabled ?? true,
            ToEndpointDraft(request.A),
            ToEndpointDraft(request.B),
            request.Directed ?? false,
            request.AToBLabel,
            request.BToALabel);
    }

    private static void Require([System.Diagnostics.CodeAnalysis.NotNull] object? element)
    {
        if (element is null)
        {
            throw new DomainValidationException(
                SceneErrorCodes.GeometryMissing,
                "A zone or trip line entry was empty.");
        }
    }

    /// <summary>A zone vertex; a missing component is a coordinate out of range.</summary>
    private static ScenePointDraft ToVertexDraft(ScenePointRequest? request) =>
        request?.X is { } x && request.Y is { } y
            ? new ScenePointDraft(x, y)
            : throw new DomainValidationException(
                SceneErrorCodes.ZoneVertexRange,
                "A zone vertex needs both coordinates.");

    /// <summary>
    /// A trip line endpoint. An absent endpoint stays absent so the domain reports it
    /// as a missing endpoint rather than as a stray coordinate.
    /// </summary>
    private static ScenePointDraft? ToEndpointDraft(ScenePointRequest? request) =>
        request?.X is { } x && request.Y is { } y ? new ScenePointDraft(x, y) : null;

    // Response mapping
    private static CameraSceneResponse ToResponse(CameraSceneView scene) => new(
        scene.CameraId,
        scene.Configured,
        scene.ActiveRevision is null ? null : ToResponse(scene.ActiveRevision, scene.CameraId),
        [.. scene.History.Select(ToSummary)]);

    private static SceneRevisionSummaryResponse ToSummary(SceneConfigurationRevision revision) => new(
        revision.Id,
        revision.RevisionNumber,
        revision.CreatedAtUtc,
        revision.CreatedBy,
        revision.Note,
        revision.AnalyticsEnabled,
        revision.Zones.Count,
        revision.TripLines.Count);

    private static SceneRevisionResponse ToResponse(SceneConfigurationRevision revision, Guid cameraId) => new(
        revision.Id,
        revision.RevisionNumber,
        cameraId,
        revision.CreatedAtUtc,
        revision.CreatedBy,
        revision.Note,
        revision.ReferenceFrameVideoAssetId,
        revision.ReferenceFrameOffsetMs,
        // Ordered by stable identity so that a zone or line keeps the same place in
        // the list from one revision to the next. The order itself carries no meaning
        // beyond being the same every time: a GUID does not sort chronologically.
        [.. revision.Zones.OrderBy(zone => zone.ZoneId).Select(ToResponse)],
        [.. revision.TripLines.OrderBy(line => line.LineId).Select(ToResponse)]);

    private static SceneZoneResponse ToResponse(SceneZone zone) => new(
        zone.ZoneId,
        zone.Name,
        zone.Kind.ToString(),
        zone.Enabled,
        [.. zone.Vertices.Select(ToResponse)],
        zone.LoiteringThresholdSeconds);

    private static SceneTripLineResponse ToResponse(TripLine line) => new(
        line.LineId,
        line.Name,
        line.Enabled,
        ToResponse(line.A),
        ToResponse(line.B),
        line.Directed,
        line.AToBLabel,
        line.BToALabel);

    private static ScenePointResponse ToResponse(NormalizedPoint point) => new(point.X, point.Y);

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(statusCode: statusCode, detail: detail, extensions: new Dictionary<string, object?>
        {
            ["code"] = code,
        });
}
