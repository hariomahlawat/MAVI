using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.SceneAnalytics;

namespace Mavi.Application.Modules.SceneAnalytics.Lifecycle;

/// <summary>Analytics readiness for one run, with the units behind it.</summary>
public sealed record RunAnalyticsView(
    Guid ProcessingRunId,
    string Readiness,
    Guid? ActiveRevisionId,
    string AlgorithmVersion,
    IReadOnlyList<SceneAnalysisUnitView> Units);

/// <summary>How a re-analysis request landed, broken down per identity.</summary>
/// <remarks>
/// The breakdown is the point. A single "queued" count cannot distinguish work that was
/// created from a request that found everything already done, so a second click would
/// look identical to the first and appear to have achieved something.
/// </remarks>
public sealed record ReanalysisOutcome(
    Guid CameraId,
    Guid SceneRevisionId,
    string AlgorithmVersion,
    string Scope,
    int Created,
    int AlreadyQueued,
    int AlreadyRunning,
    int AlreadyReady,
    int FailedRequiresRetry);

/// <summary>Why a request could not be served, in the caller's terms.</summary>
public enum SceneAnalyticsRequestOutcome
{
    Ok,

    /// <summary>The run, or the camera, does not exist.</summary>
    NotFound,

    /// <summary>The camera has no active scene revision to analyse against.</summary>
    NotConfigured,

    /// <summary>The camera's active revision enables no geometry, so analytics are off.</summary>
    Disabled,

    /// <summary>There is no unit for the current identity to act on.</summary>
    NoCurrentAnalysis,

    /// <summary>The unit exists but is not in a state the request is legal from.</summary>
    Conflict,
}

public sealed record SceneAnalyticsRequestResult<T>(SceneAnalyticsRequestOutcome Outcome, T? Value, string? ErrorCode);

/// <summary>Constructors for <see cref="SceneAnalyticsRequestResult{T}"/>.</summary>
public static class SceneAnalyticsRequestResult
{
    public static SceneAnalyticsRequestResult<T> Ok<T>(T value) =>
        new(SceneAnalyticsRequestOutcome.Ok, value, null);

    public static SceneAnalyticsRequestResult<T> Failure<T>(
        SceneAnalyticsRequestOutcome outcome,
        string? code = null) =>
        new(outcome, default, code);
}

/// <summary>
/// The operator-facing side of the analytics lifecycle: what state a run is in, and the
/// two things an operator may ask for — retry a failed unit, or re-analyse a camera.
/// </summary>
/// <remarks>
/// Every mutation here goes through <see cref="ISceneAnalysisLifecycle"/> rather than
/// touching rows itself, so an operator's request is fenced by exactly the same
/// transactions the background host uses. There is no second, more convenient path.
/// </remarks>
public sealed class SceneAnalyticsStatusService(
    ISceneAnalyticsStatusReader reader,
    ISceneAnalysisLifecycle lifecycle)
{
    private static string AlgorithmVersion => SceneAnalyticsAlgorithm.Version;

    // --- Status ------------------------------------------------------------

    public async Task<SceneAnalyticsRequestResult<RunAnalyticsView>> GetRunAnalyticsAsync(
        Guid processingRunId,
        CancellationToken cancellationToken)
    {
        if (await reader.GetRunCameraAsync(processingRunId, cancellationToken) is not { } cameraId)
        {
            return SceneAnalyticsRequestResult.Failure<RunAnalyticsView>(SceneAnalyticsRequestOutcome.NotFound);
        }

        var scope = await reader.GetCameraScopeAsync(cameraId, cancellationToken);
        var units = await reader.ListRunUnitsAsync(processingRunId, cancellationToken);

        return SceneAnalyticsRequestResult.Ok<RunAnalyticsView>(new RunAnalyticsView(
            processingRunId,
            SceneAnalyticsReadinessRule.Derive(scope, units, AlgorithmVersion),
            scope?.ActiveRevisionId,
            AlgorithmVersion,
            units));
    }

    /// <summary>Readiness alone, for a run embedded in another projection.</summary>
    public async Task<string?> GetReadinessAsync(Guid processingRunId, CancellationToken cancellationToken)
    {
        if (await reader.GetRunCameraAsync(processingRunId, cancellationToken) is not { } cameraId)
        {
            return null;
        }

        var scope = await reader.GetCameraScopeAsync(cameraId, cancellationToken);
        var units = await reader.ListRunUnitsAsync(processingRunId, cancellationToken);
        return SceneAnalyticsReadinessRule.Derive(scope, units, AlgorithmVersion);
    }

    // --- Retry -------------------------------------------------------------

    /// <summary>
    /// Retries the failed unit for the run's current identity, starting a new retry cycle
    /// on the same row.
    /// </summary>
    /// <remarks>
    /// No fact is deleted here. A unit's facts are replaced only inside a later
    /// successful commit, after ownership has been revalidated, so a retry that never
    /// succeeds leaves the last good answer exactly where it was.
    /// </remarks>
    public async Task<SceneAnalyticsRequestResult<SceneAnalysisUnitView>> RetryAsync(
        Guid processingRunId,
        CancellationToken cancellationToken)
    {
        if (await reader.GetRunCameraAsync(processingRunId, cancellationToken) is not { } cameraId)
        {
            return SceneAnalyticsRequestResult.Failure<SceneAnalysisUnitView>(SceneAnalyticsRequestOutcome.NotFound);
        }

        var scope = await reader.GetCameraScopeAsync(cameraId, cancellationToken);
        if (scope?.ActiveRevisionId is not { } activeRevisionId)
        {
            return SceneAnalyticsRequestResult.Failure<SceneAnalysisUnitView>(
                SceneAnalyticsRequestOutcome.NotConfigured);
        }

        var units = await reader.ListRunUnitsAsync(processingRunId, cancellationToken);
        var current = units.FirstOrDefault(unit =>
            unit.RevisionId == activeRevisionId
            && string.Equals(unit.AlgorithmVersion, AlgorithmVersion, StringComparison.Ordinal));
        if (current is null)
        {
            return SceneAnalyticsRequestResult.Failure<SceneAnalysisUnitView>(
                SceneAnalyticsRequestOutcome.NoCurrentAnalysis);
        }

        var result = await lifecycle.RetryAsync(current.AnalysisId, cancellationToken);
        if (!result.IsSuccess)
        {
            // The lifecycle refuses a retry from anything but Failed, and it re-reads the
            // row under a lock — so this also covers a unit that someone else moved on
            // between our read and the transition.
            return SceneAnalyticsRequestResult.Failure<SceneAnalysisUnitView>(
                SceneAnalyticsRequestOutcome.Conflict,
                result.ErrorCode);
        }

        var refreshed = await reader.ListRunUnitsAsync(processingRunId, cancellationToken);
        return SceneAnalyticsRequestResult.Ok<SceneAnalysisUnitView>(
            refreshed.Single(unit => unit.AnalysisId == current.AnalysisId));
    }

    // --- Re-analysis -------------------------------------------------------

    /// <summary>
    /// Queues analysis of a camera's runs against its active revision.
    /// </summary>
    /// <remarks>
    /// Idempotent per identity: a run that already has a unit for the active revision and
    /// current algorithm version gets nothing new, and is counted under whichever state it
    /// is already in. Creation goes through the unique index rather than a check-then-
    /// insert, so two concurrent requests still produce one unit per run.
    /// </remarks>
    public async Task<SceneAnalyticsRequestResult<ReanalysisOutcome>> RequestReanalysisAsync(
        Guid cameraId,
        bool allRuns,
        CancellationToken cancellationToken)
    {
        var scope = await reader.GetCameraScopeAsync(cameraId, cancellationToken);
        if (scope is null)
        {
            return SceneAnalyticsRequestResult.Failure<ReanalysisOutcome>(SceneAnalyticsRequestOutcome.NotFound);
        }

        if (scope.ActiveRevisionId is not { } revisionId)
        {
            return SceneAnalyticsRequestResult.Failure<ReanalysisOutcome>(SceneAnalyticsRequestOutcome.NotConfigured);
        }

        if (!scope.AnalyticsEnabled)
        {
            // Re-analysing against a revision that enables nothing would manufacture empty
            // units for a camera whose operator switched analytics off.
            return SceneAnalyticsRequestResult.Failure<ReanalysisOutcome>(SceneAnalyticsRequestOutcome.Disabled);
        }

        var runs = await reader.ListAnalysableRunsAsync(cameraId, allRuns, cancellationToken);
        var parametersSha256 = SceneAnalyticsParameters.Default.ParametersSha256();
        var counts = new Dictionary<SceneAnalysisQueueOutcome, int>();

        foreach (var runId in runs)
        {
            var result = await lifecycle.RequestAnalysisAsync(
                new SceneAnalysisIdentity(runId, revisionId, AlgorithmVersion, parametersSha256, null),
                cancellationToken);
            counts[result.Outcome] = counts.GetValueOrDefault(result.Outcome) + 1;
        }

        return SceneAnalyticsRequestResult.Ok<ReanalysisOutcome>(new ReanalysisOutcome(
            cameraId,
            revisionId,
            AlgorithmVersion,
            allRuns ? "allRuns" : "latestRuns",
            counts.GetValueOrDefault(SceneAnalysisQueueOutcome.Created),
            counts.GetValueOrDefault(SceneAnalysisQueueOutcome.AlreadyQueued),
            counts.GetValueOrDefault(SceneAnalysisQueueOutcome.AlreadyRunning),
            // A superseded unit for the active identity would be unusual, but it is
            // fact-bearing all the same, so it counts as analysed rather than as nothing.
            counts.GetValueOrDefault(SceneAnalysisQueueOutcome.AlreadyAnalysed)
                + counts.GetValueOrDefault(SceneAnalysisQueueOutcome.AlreadySuperseded),
            counts.GetValueOrDefault(SceneAnalysisQueueOutcome.FailedRequiresRetry)));
    }
}
