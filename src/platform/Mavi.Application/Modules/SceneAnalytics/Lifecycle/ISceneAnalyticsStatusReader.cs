using Mavi.Domain.SceneAnalytics;

namespace Mavi.Application.Modules.SceneAnalytics.Lifecycle;

/// <summary>
/// What a camera's scene configuration means for analytics right now.
/// </summary>
/// <remarks>
/// The three states a camera can be in are distinguishable here on purpose: no
/// configuration at all, an active revision that enables nothing, and an active revision
/// with geometry. An operator is owed the difference between a gap and a switch-off, so
/// the projection must never collapse the first two into "no results".
/// </remarks>
public sealed record SceneAnalyticsCameraScope(
    Guid CameraId,
    Guid? ActiveRevisionId,
    int? ActiveRevisionNumber,
    bool AnalyticsEnabled);

/// <summary>One analysis unit, as an operator-facing projection.</summary>
/// <remarks>
/// The claim token and its hash are absent, and cannot be added: they are the secret that
/// fences an attempt. The attempt number and the lease expiry are <i>not</i> secrets and
/// are here deliberately — someone looking at a <c>Running</c> unit needs to tell a unit
/// that is progressing from one that has been abandoned.
/// </remarks>
public sealed record SceneAnalysisUnitView(
    Guid AnalysisId,
    Guid ProcessingRunId,
    Guid RevisionId,
    int RevisionNumber,
    string AlgorithmVersion,
    SceneAnalysisStatus Status,
    int AttemptCount,
    DateTimeOffset QueuedAtUtc,
    DateTimeOffset? StartedAtUtc,
    DateTimeOffset? CompletedAtUtc,
    DateTimeOffset? LeaseExpiresAtUtc,
    int AnalysedTrackCount,
    int UnavailableTrackCount,
    string? FailureCode);

/// <summary>Reads what the analytics projections need, without mutating anything.</summary>
public interface ISceneAnalyticsStatusReader
{
    /// <summary>The camera a completed run belongs to, or null if the run is unknown.</summary>
    Task<Guid?> GetRunCameraAsync(Guid processingRunId, CancellationToken cancellationToken);

    /// <summary>
    /// The camera's analytics scope, or null if the camera itself does not exist.
    /// </summary>
    /// <remarks>
    /// A camera that exists but has never been configured returns a scope with no active
    /// revision, which is not the same answer as null.
    /// </remarks>
    Task<SceneAnalyticsCameraScope?> GetCameraScopeAsync(Guid cameraId, CancellationToken cancellationToken);

    /// <summary>Every analysis unit of a run, newest identity last.</summary>
    Task<IReadOnlyList<SceneAnalysisUnitView>> ListRunUnitsAsync(
        Guid processingRunId,
        CancellationToken cancellationToken);

    /// <summary>
    /// The runs of a camera that can be analysed: completed and visible.
    /// </summary>
    /// <param name="allRuns">
    /// False for the latest analysable run of each video, which is what an operator means
    /// by "re-analyse this camera"; true for the camera's whole history.
    /// </param>
    Task<IReadOnlyList<Guid>> ListAnalysableRunsAsync(
        Guid cameraId,
        bool allRuns,
        CancellationToken cancellationToken);

    /// <summary>Readiness for several runs at once, for list and status projections.</summary>
    Task<IReadOnlyDictionary<Guid, IReadOnlyList<SceneAnalysisUnitView>>> ListUnitsForRunsAsync(
        IReadOnlyCollection<Guid> processingRunIds,
        CancellationToken cancellationToken);
}
