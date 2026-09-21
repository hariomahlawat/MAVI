using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Analytics;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The analytics lifecycle as an operator sees it: what state a run is in, and the two
/// things they may ask for — retry a failed unit, or re-analyse a camera.
/// </summary>
/// <remarks>
/// <para>
/// Both mutations go through the same fenced transactions the background host uses. An
/// operator's request is not a shortcut past the lifecycle, and there is no endpoint that
/// deletes facts: a unit's facts are replaced only inside a later successful commit,
/// after ownership has been revalidated.
/// </para>
/// <para>
/// No request may supply an identity, and none of these responses carries one. Attribution
/// in this increment is server-controlled and explicitly unattributed (ADR-011, §AG).
/// </para>
/// </remarks>
public static class SceneAnalyticsEndpoints
{
    public static IEndpointRouteBuilder MapSceneAnalyticsEndpoints(this IEndpointRouteBuilder endpoints)
    {
        var runs = endpoints.MapGroup("/api/processing/runs/{processingRunId:guid}/analytics");
        runs.MapGet("/", GetRunAnalyticsAsync).WithName("GetRunAnalytics");
        runs.MapPost("/retry", RetryAsync);

        endpoints.MapPost("/api/cameras/{cameraId:guid}/scene/analyses", ReanalyseAsync);
        return endpoints;
    }

    // Handlers
    private static async Task<IResult> GetRunAnalyticsAsync(
        Guid processingRunId,
        SceneAnalyticsStatusService analytics,
        CancellationToken cancellationToken)
    {
        var result = await analytics.GetRunAnalyticsAsync(processingRunId, cancellationToken);
        if (result.Outcome != SceneAnalyticsRequestOutcome.Ok)
        {
            return RunNotFound();
        }

        var view = result.Value!;
        return Results.Ok(new ProcessingRunAnalyticsResponse(
            view.ProcessingRunId,
            view.Readiness,
            view.ActiveRevisionId,
            view.AlgorithmVersion,
            [.. view.Units.Select(ToResponse)]));
    }

    private static async Task<IResult> RetryAsync(
        Guid processingRunId,
        SceneAnalyticsStatusService analytics,
        CancellationToken cancellationToken)
    {
        var result = await analytics.RetryAsync(processingRunId, cancellationToken);
        return result.Outcome switch
        {
            SceneAnalyticsRequestOutcome.Ok => Results.Ok(ToResponse(result.Value!)),
            SceneAnalyticsRequestOutcome.NotFound => RunNotFound(),
            SceneAnalyticsRequestOutcome.NotConfigured => Problem(
                StatusCodes.Status409Conflict,
                "analytics_not_configured",
                "The camera has no active scene revision to analyse against."),
            SceneAnalyticsRequestOutcome.NoCurrentAnalysis => Problem(
                StatusCodes.Status404NotFound,
                "analytics_not_found",
                "The run has no analysis for the active scene revision."),
            // The unit exists but is not Failed. Retrying a queued, running or successful
            // unit is not a no-op to be absorbed silently — it means the caller is acting
            // on a state they have not seen.
            _ => Problem(
                StatusCodes.Status409Conflict,
                result.ErrorCode ?? "analytics_transition_invalid",
                "The analysis is not in a state that can be retried."),
        };
    }

    private static async Task<IResult> ReanalyseAsync(
        Guid cameraId,
        SceneReanalysisRequest? request,
        SceneAnalyticsStatusService analytics,
        CancellationToken cancellationToken)
    {
        var scope = request?.Scope ?? SceneAnalyticsContractRules.DefaultReanalysisScope;
        if (!SceneAnalyticsContractRules.IsReanalysisScope(scope))
        {
            return Problem(
                StatusCodes.Status400BadRequest,
                "analytics_scope_invalid",
                "Scope must be 'latestRuns' or 'allRuns'.");
        }

        var result = await analytics.RequestReanalysisAsync(
            cameraId,
            allRuns: string.Equals(scope, "allRuns", StringComparison.Ordinal),
            cancellationToken);

        return result.Outcome switch
        {
            SceneAnalyticsRequestOutcome.Ok => Results.Accepted(
                $"/api/cameras/{cameraId}/scene",
                ToResponse(result.Value!)),
            SceneAnalyticsRequestOutcome.NotFound => Problem(
                StatusCodes.Status404NotFound,
                CameraErrorCodes.NotFound,
                "Camera was not found."),
            SceneAnalyticsRequestOutcome.NotConfigured => Problem(
                StatusCodes.Status409Conflict,
                "analytics_not_configured",
                "The camera has no active scene revision to analyse against."),
            // Analytics are switched off for this camera. Queueing units anyway would
            // manufacture empty results for an operator who deliberately turned them off.
            _ => Problem(
                StatusCodes.Status409Conflict,
                "analytics_disabled",
                "The camera's active scene revision enables no zones or trip lines."),
        };
    }

    // Response mapping
    private static SceneAnalysisStatusResponse ToResponse(SceneAnalysisUnitView unit) => new(
        unit.AnalysisId,
        unit.ProcessingRunId,
        unit.RevisionId,
        unit.RevisionNumber,
        unit.AlgorithmVersion,
        unit.Status.ToString(),
        unit.AttemptCount,
        unit.QueuedAtUtc,
        unit.StartedAtUtc,
        unit.CompletedAtUtc,
        // The lease expiry is not a secret and is projected deliberately: it is how an
        // operator tells a Running unit that is progressing from one that was abandoned.
        // The claim token and its hash are the secret, and neither has a field here.
        unit.LeaseExpiresAtUtc,
        unit.AnalysedTrackCount,
        unit.UnavailableTrackCount,
        unit.FailureCode);

    private static SceneReanalysisAcceptedResponse ToResponse(ReanalysisOutcome outcome) => new(
        outcome.CameraId,
        outcome.SceneRevisionId,
        outcome.AlgorithmVersion,
        outcome.Scope,
        outcome.Created,
        outcome.AlreadyQueued,
        outcome.AlreadyRunning,
        outcome.AlreadyReady,
        outcome.FailedRequiresRetry);

    // A run that does not exist and one that is not visible share the same answer, as the
    // attestation endpoint already does: a 404 must not confirm that a hidden run exists.
    private static IResult RunNotFound() =>
        Problem(StatusCodes.Status404NotFound, "processing_run_not_found", "The processing run was not found.");

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(
            statusCode: statusCode,
            detail: detail,
            extensions: new Dictionary<string, object?> { ["code"] = code });
}
