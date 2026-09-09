using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Processing;

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
    private static async Task<IResult> LeaseAsync(LeaseVisionJobRequest request, IProcessingOrchestrator orchestrator,
        CancellationToken cancellationToken)
    {
        if (!ValidWorker(request.WorkerId)) return Problem(400, "vision_worker_id_invalid", "A valid worker ID is required.");
        var lease = await orchestrator.LeaseAsync(request.WorkerId!.Trim(), cancellationToken);
        return lease is null ? Results.NoContent() : Results.Ok(lease);
    }

    private static async Task<IResult> HeartbeatAsync(Guid id, VisionJobHeartbeatRequest request,
        IProcessingOrchestrator orchestrator, CancellationToken cancellationToken)
    {
        if (!ValidWorker(request.WorkerId) || !double.IsFinite(request.ProgressPercent) || request.ProgressPercent is < 0 or > 100)
            return Problem(400, "vision_job_heartbeat_invalid", "Heartbeat input is invalid.");
        var result = await orchestrator.HeartbeatAsync(id, request.WorkerId!.Trim(), request.ProgressPercent, cancellationToken);
        return Result(result);
    }

    private static async Task<IResult> FailAsync(Guid id, FailVisionJobRequest request,
        IProcessingOrchestrator orchestrator, CancellationToken cancellationToken)
    {
        if (!ValidWorker(request.WorkerId) || string.IsNullOrWhiteSpace(request.FailureCode) ||
            request.FailureCode.Trim().Length > 64 || request.FailureMessage?.Length > 4000)
            return Problem(400, "vision_job_failure_invalid", "Failure input is invalid.");
        var result = await orchestrator.FailAsync(id, request.WorkerId!.Trim(), request.FailureCode.Trim(), request.FailureMessage, cancellationToken);
        return Result(result);
    }

    // Safe errors
    private static bool ValidWorker(string? workerId) => !string.IsNullOrWhiteSpace(workerId) && workerId.Trim().Length <= 128;
    private static IResult Result(OrchestrationResult result) => result.IsSuccess ? Results.Ok() : Problem(
        result.ErrorCode == "vision_job_not_found" ? 404 : 409, result.ErrorCode!, "The vision job operation was rejected.");
    private static IResult Problem(int status, string code, string detail) => Results.Problem(statusCode: status,
        detail: detail, extensions: new Dictionary<string, object?> { ["code"] = code });
}
