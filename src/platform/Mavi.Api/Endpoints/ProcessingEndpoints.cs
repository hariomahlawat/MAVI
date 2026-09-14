using Mavi.Application.Modules.Intelligence;
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

        ParsedVisionRuntimeProvenance parsed;
        IReadOnlyDictionary<string, string> dependencies;
        try
        {
            parsed = provenanceParser.ParsePersisted(source.RuntimeProvenanceJson ?? string.Empty);
            dependencies = VisionRuntimeProvenanceParser.GetAttestationDependencies(parsed.Contract);
        }
        catch (VisionResultValidationException)
        {
            return Problem(
                StatusCodes.Status500InternalServerError,
                "processing_attestation_integrity_failure",
                "The completed processing run provenance is invalid.");
        }

        var value = parsed.Contract;
        var platform = value.Platform!;
        var response = new ProcessingRunAttestationResponse(
            source.ProcessingRunId,
            source.VideoAssetId,
            source.CompletedAtUtc,
            source.PipelineVersion,
            value.ModelId!,
            value.ModelVersion!,
            value.ModelManifestSha256!,
            value.CheckpointSha256!,
            value.ResolvedConfigSha256!,
            value.PipelineProfileId!,
            value.PipelineProfileVersion!,
            value.PipelineProfileSha256!,
            value.QualificationId,
            value.QualificationSha256,
            value.VerificationStatus!,
            value.RuntimeProfileId!,
            value.RuntimeProfileSha256!,
            value.RuntimeVariant!,
            value.PlatformLockSha256,
            value.MaviBuild!,
            value.MaviCommit!,
            value.ConfiguredDevicePolicy!,
            value.ConfiguredDeviceIndex!.Value,
            value.ActualDevice!,
            new ProcessingRunPlatformAttestationResponse(
                platform.System!,
                platform.Release!,
                platform.Version!,
                platform.Machine!,
                platform.Processor!,
                platform.PythonVersion!,
                platform.PythonImplementation!,
                platform.PythonBuild!,
                platform.PythonCompiler!),
            value.Gpu is null
                ? null
                : new ProcessingRunGpuAttestationResponse(
                    value.Gpu.Name!,
                    value.Gpu.Index!.Value,
                    value.Gpu.VramBytes!.Value,
                    value.Gpu.DriverVersion!,
                    value.Gpu.CudaRuntimeVersion!),
            dependencies,
            source.DetectorName,
            source.DetectorVersion,
            source.TrackerName,
            source.TrackerVersion,
            source.FramesProcessed,
            source.TracksCreated,
            source.ProcessingDurationMs);

        return Results.Ok(response);
    }

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(
            statusCode: statusCode,
            detail: detail,
            extensions: new Dictionary<string, object?> { ["code"] = code });
}
