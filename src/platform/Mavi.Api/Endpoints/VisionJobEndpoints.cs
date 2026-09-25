using System.Diagnostics;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;

namespace Mavi.Api.Endpoints;

public static class VisionJobEndpoints
{
    // Route registration
    public static IEndpointRouteBuilder MapVisionJobEndpoints(this IEndpointRouteBuilder endpoints)
    {
        // Additive capability probe (S1.2a): a worker that emits completion 3.x
        // checks it before becoming ready. Workers that predate it never call it.
        // Since F2 it lists 2.0 and 3.1; 3.0 is retired (plan §15.2).
        endpoints.MapGet("/api/vision/contract", () => Results.Ok(new VisionContractCapabilitiesResponse(
            WorkerContractRules.SchemaVersion,
            WorkerContractRules.CompletionSchemaVersions)));

        var jobs = endpoints.MapGroup("/api/vision/jobs");
        jobs.MapPost("/lease", LeaseAsync);
        jobs.MapPost("/{id:guid}/heartbeat", HeartbeatAsync);
        jobs.MapPost("/{id:guid}/fail", FailAsync);
        jobs.MapPost("/{id:guid}/complete", CompleteAsync);
        return endpoints;
    }

    // Worker commands
    private static async Task<IResult> LeaseAsync(VisionJobLeaseRequest request, IProcessingOrchestrator orchestrator,
        CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != WorkerContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        var lease = await orchestrator.LeaseAsync(workerId, cancellationToken);
        return lease is null ? Results.NoContent() : Results.Ok(Map(lease));
    }

    private static async Task<IResult> HeartbeatAsync(Guid id, VisionJobHeartbeatRequest request,
        IProcessingOrchestrator orchestrator, CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != WorkerContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!WorkerContractRules.IsCanonicalLeaseToken(request.LeaseToken) || request.ProgressPercent is not { } progressPercent ||
            !double.IsFinite(progressPercent) || progressPercent is < 0 or > 100)
            return Problem(400, "vision_job_heartbeat_invalid", "Heartbeat input is invalid.");
        var result = await orchestrator.HeartbeatAsync(id, workerId, request.LeaseToken!, progressPercent, cancellationToken);
        return result switch
        {
            HeartbeatResult.Success success => Results.Ok(new VisionJobHeartbeatResponse(
                WorkerContractRules.SchemaVersion, success.ProgressPercent, success.LeaseExpiresAtUtc)),
            HeartbeatResult.Failure failure => Problem(
                failure.ErrorCode == "vision_job_not_found" ? 404 : 409, failure.ErrorCode,
                "The vision job operation was rejected."),
            _ => throw new UnreachableException(),
        };
    }

    private static async Task<IResult> FailAsync(Guid id, VisionJobFailRequest request,
        IProcessingOrchestrator orchestrator, CancellationToken cancellationToken)
    {
        if (request.SchemaVersion != WorkerContractRules.SchemaVersion) return VersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!WorkerContractRules.IsCanonicalLeaseToken(request.LeaseToken) || !WorkerContractRules.IsFailureCode(request.FailureCode) ||
            request.FailureMessage?.Length > 4000 || request.FailureCode!.Contains(request.LeaseToken!, StringComparison.Ordinal) ||
            (request.FailureMessage?.Contains(request.LeaseToken!, StringComparison.Ordinal) ?? false))
            return Problem(400, "vision_job_failure_invalid", "Failure input is invalid.");
        var result = await orchestrator.FailAsync(id, workerId, request.LeaseToken!, request.FailureCode, request.FailureMessage, cancellationToken);
        return Result(result);
    }

    private static async Task<IResult> CompleteAsync(
        Guid id,
        VisionJobCompleteRequest request,
        IProcessingResultStore resultStore,
        IVisionFinalizationSubmissionStore submissionStore,
        CancellationToken cancellationToken)
    {
        if (!WorkerContractRules.IsAcceptedCompletionSchemaVersion(request.SchemaVersion)) return CompletionVersionProblem();
        if (!WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId)) return WorkerProblem();
        if (!WorkerContractRules.IsCanonicalLeaseToken(request.LeaseToken))
            return Problem(400, "vision_job_completion_invalid", "Completion input is invalid.");

        // 3.1 is the durable hand-off (S1.4 B3 plan §6): no sealing, no graph, no completion
        // in this request. 2.0 keeps the synchronous store unchanged.
        if (WorkerContractRules.IsAsynchronousCompletionSchemaVersion(request.SchemaVersion))
            return await SubmitFinalizationAsync(id, workerId, request, submissionStore, cancellationToken);

        var result = await resultStore.CompleteAsync(
            id,
            workerId,
            request.LeaseToken!,
            request,
            cancellationToken);

        if (result.IsSuccess)
        {
            // Echo the completion version the worker spoke, so a 2.0 worker keeps
            // receiving exactly the 2.0 response it validates.
            return Results.Ok(new VisionJobCompleteResponse(
                request.SchemaVersion!,
                id,
                result.ProcessingRunId!.Value,
                result.TracksAccepted,
                result.CompletedAtUtc!.Value));
        }

        var status = result.ErrorCode switch
        {
            "vision_job_not_found" => 404,
            "vision_result_invalid" => 400,
            _ => 409,
        };
        return Problem(status, result.ErrorCode!, "The vision job completion was rejected.");
    }

    private static async Task<IResult> SubmitFinalizationAsync(
        Guid id,
        string workerId,
        VisionJobCompleteRequest request,
        IVisionFinalizationSubmissionStore submissionStore,
        CancellationToken cancellationToken)
    {
        var result = await submissionStore.SubmitAsync(id, workerId, request.LeaseToken!, request, cancellationToken);
        if (result.IsSuccess)
        {
            return Results.Ok(result.State == WorkerContractRules.FinalizationStateCompleted
                ? VisionJobFinalizationResponse.Completed(
                    id, result.ProcessingRunId!.Value, result.AcceptedAtUtc!.Value, result.TracksSubmitted, result.CompletedAtUtc!.Value)
                : VisionJobFinalizationResponse.Finalizing(
                    id, result.ProcessingRunId!.Value, result.AcceptedAtUtc!.Value, result.TracksSubmitted));
        }

        var status = result.ErrorCode switch
        {
            "vision_job_not_found" => 404,
            "vision_result_invalid" => 400,
            _ => 409,
        };
        return Problem(status, result.ErrorCode!, "The vision job completion was rejected.");
    }

    // Public mapping and safe errors
    private static VisionJobLeaseContract Map(VisionLeaseView lease) => new(WorkerContractRules.SchemaVersion, lease.JobId,
        lease.ProcessingRunId, lease.VideoAssetId, lease.CameraId, lease.WorkerId, lease.LeaseToken, lease.AttemptCount,
        lease.LeaseExpiresAtUtc, lease.Pipeline, lease.PipelineVersion, lease.SourceStorageKey, lease.SourceSha256,
        lease.SourceSizeBytes, lease.RecordingStartUtc, lease.RecordingEndUtc, lease.DurationMs, lease.Width, lease.Height,
        lease.FrameRateNumerator, lease.FrameRateDenominator, lease.RecordingTimeZoneId, lease.RecordingUtcOffsetMinutes);
    private static IResult VersionProblem() => Problem(400, "worker_contract_version_unsupported", "Worker contract version 2.0 is required.");
    private static IResult CompletionVersionProblem() => Problem(400, "worker_contract_version_unsupported",
        "Worker completion contract version 2.0 or 3.1 is required.");
    private static IResult WorkerProblem() => Problem(400, "worker_id_invalid", "A valid worker ID is required.");
    private static IResult Result(OrchestrationResult result) => result.IsSuccess ? Results.Ok() : Problem(
        result.ErrorCode == "vision_job_not_found" ? 404 : 409, result.ErrorCode!, "The vision job operation was rejected.");
    private static IResult Problem(int status, string code, string detail) => Results.Problem(statusCode: status,
        detail: detail, extensions: new Dictionary<string, object?> { ["code"] = code });
}
