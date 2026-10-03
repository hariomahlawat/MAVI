using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Processing;
using Mavi.Contracts.Api.Processing;

namespace Mavi.Api.Endpoints;

public static class ProcessingEndpoints
{
    public static IEndpointRouteBuilder MapProcessingEndpoints(this IEndpointRouteBuilder endpoints)
    {
        endpoints.MapGet("/api/processing/runs/{processingRunId:guid}/attestation", AttestationAsync);
        return endpoints;
    }

    private static async Task<IResult> AttestationAsync(
        Guid processingRunId,
        IProcessingOrchestrator orchestrator,
        VisionRuntimeProvenanceParser provenanceParser,
        CancellationToken cancellationToken)
    {
        var source = await orchestrator.GetCompletedRunAttestationAsync(
            processingRunId,
            cancellationToken);

        // Unknown and non-completed runs intentionally share the same non-disclosing result.
        if (source is null)
            return Problem(
                StatusCodes.Status404NotFound,
                "processing_run_not_found",
                "The completed processing run was not found.");

        ProcessingRunAttestationResponse response;
        try
        {
            var parsed = provenanceParser.ParsePersisted(source.RuntimeProvenanceJson ?? string.Empty);
            response = ProcessingRunAttestationFactory.Build(source, parsed);
        }
        catch (VisionResultValidationException)
        {
            return Problem(
                StatusCodes.Status500InternalServerError,
                "processing_attestation_integrity_failure",
                "The completed processing run provenance is invalid.");
        }

        return Results.Ok(response);
    }

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(
            statusCode: statusCode,
            detail: detail,
            extensions: new Dictionary<string, object?> { ["code"] = code });
}
