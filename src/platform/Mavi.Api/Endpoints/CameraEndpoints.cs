using Mavi.Application.Modules.Cameras;
using Mavi.Contracts.Api.Cameras;
using Mavi.Domain.Cameras;
using Mavi.Domain.Common;

namespace Mavi.Api.Endpoints;

public static class CameraEndpoints
{
    // Route registration
    public static IEndpointRouteBuilder MapCameraEndpoints(this IEndpointRouteBuilder endpoints)
    {
        var cameras = endpoints.MapGroup("/api/cameras");
        cameras.MapPost("/", CreateAsync);
        cameras.MapGet("/", ListAsync);
        cameras.MapGet("/{id:guid}", GetAsync).WithName("GetCamera");
        return endpoints;
    }

    // Handlers
    private static async Task<IResult> CreateAsync(
        CreateCameraRequest request,
        CameraService service,
        CancellationToken cancellationToken)
    {
        try
        {
            var result = await service.CreateAsync(
                new CreateCameraCommand(request.Code, request.Name, request.TimeZoneId),
                cancellationToken);
            if (!result.IsSuccess)
            {
                return Problem(StatusCodes.Status409Conflict, result.ErrorCode!, "Camera code already exists.");
            }

            var response = ToResponse(result.Camera!);
            return Results.Created($"/api/cameras/{response.Id}", response);
        }
        catch (DomainValidationException exception)
        {
            return Problem(StatusCodes.Status400BadRequest, exception.Code, exception.Message);
        }
    }

    private static async Task<IResult> GetAsync(
        Guid id,
        CameraService service,
        CancellationToken cancellationToken)
    {
        var camera = await service.GetAsync(id, cancellationToken);
        return camera is null
            ? Problem(StatusCodes.Status404NotFound, CameraErrorCodes.NotFound, "Camera was not found.")
            : Results.Ok(ToResponse(camera));
    }

    private static async Task<IResult> ListAsync(CameraService service, CancellationToken cancellationToken) =>
        Results.Ok((await service.ListAsync(cancellationToken)).Select(ToResponse));

    // Response mapping
    private static CameraResponse ToResponse(Camera camera) => new(
        camera.Id,
        camera.Code,
        camera.Name,
        camera.Description,
        camera.LocationName,
        camera.TimeZoneId,
        camera.IsActive,
        camera.CreatedAtUtc,
        camera.UpdatedAtUtc);

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(statusCode: statusCode, detail: detail, extensions: new Dictionary<string, object?>
        {
            ["code"] = code,
        });
}
