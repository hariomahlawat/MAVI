using Mavi.Application.Modules.Evidence;

namespace Mavi.Api.Endpoints;

public static class ArtifactEndpoints
{
    public static IEndpointRouteBuilder MapArtifactEndpoints(this IEndpointRouteBuilder endpoints)
    {
        endpoints.MapGet("/api/artifacts/{id:guid}/content", GetContentAsync);
        return endpoints;
    }

    private static async Task<IResult> GetContentAsync(
        Guid id,
        HttpContext context,
        ContentReadService service,
        CancellationToken cancellationToken)
    {
        var result = await service.OpenEvidenceAsync(id, cancellationToken);
        if (!result.IsSuccess)
            return Problem(
                result.IsNotFound ? 404 : 500,
                result.ErrorCode!,
                result.IsNotFound
                    ? "Artifact was not found."
                    : "Artifact content is unavailable.");

        return StreamResult(context, result.Descriptor!, result.Stream!);
    }

    internal static IResult StreamResult(
        HttpContext context,
        ContentDescriptor descriptor,
        Stream stream)
    {
        context.Response.Headers.ETag = "\"" + descriptor.Sha256 + "\"";
        context.Response.Headers.AcceptRanges = "bytes";
        return Results.Stream(
            stream,
            descriptor.MimeType,
            enableRangeProcessing: true);
    }

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(
            statusCode: statusCode,
            detail: detail,
            extensions: new Dictionary<string, object?> { ["code"] = code });
}
