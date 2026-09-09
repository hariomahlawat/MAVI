using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;

namespace Mavi.Api.Endpoints;

public static class VisionJobEndpoints
{
    // Route registration
    public static IEndpointRouteBuilder MapVisionJobEndpoints(this IEndpointRouteBuilder endpoints)
    {
        var jobs = endpoints.MapGroup("/api/vision/jobs");
        jobs.MapPost("/lease", LeaseAsync);
        jobs.MapPost("/{id:guid}/heartbeat", HeartbeatAsync);
        jobs.MapPost("/{id:guid}/fail", FailAsync);
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
        return result.IsSuccess
            ? Results.Ok(new VisionJobHeartbeatResponse("2.0", result.ProgressPercent!.Value, result.LeaseExpiresAtUtc!.Value))
            : Result(result);
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

    // Public mapping and safe errors
    private static VisionJobLeaseContract Map(VisionLeaseView lease) => new(WorkerContractRules.SchemaVersion, lease.JobId,
        lease.ProcessingRunId, lease.VideoAssetId, lease.CameraId, lease.WorkerId, lease.LeaseToken, lease.AttemptCount,
        lease.LeaseExpiresAtUtc, lease.Pipeline, lease.PipelineVersion, lease.SourceStorageKey, lease.SourceSha256,
        lease.SourceSizeBytes, lease.RecordingStartUtc, lease.RecordingEndUtc, lease.DurationMs, lease.Width, lease.Height,
        lease.FrameRateNumerator, lease.FrameRateDenominator, lease.RecordingTimeZoneId, lease.RecordingUtcOffsetMinutes);
    private static IResult VersionProblem() => Problem(400, "worker_contract_version_unsupported", "Worker contract version 2.0 is required.");
    private static IResult WorkerProblem() => Problem(400, "worker_id_invalid", "A valid worker ID is required.");
    private static IResult Result(OrchestrationResult result) => result.IsSuccess ? Results.Ok() : Problem(
        result.ErrorCode == "vision_job_not_found" ? 404 : 409, result.ErrorCode!, "The vision job operation was rejected.");
    private static IResult Problem(int status, string code, string detail) => Results.Problem(statusCode: status,
        detail: detail, extensions: new Dictionary<string, object?> { ["code"] = code });
}
