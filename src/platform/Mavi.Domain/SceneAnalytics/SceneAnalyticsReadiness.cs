namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// Analytics readiness for one processing run, derived on read and never stored.
/// </summary>
/// <remarks>
/// Readiness answers "is the camera's <i>current</i> geometry applied to this run?".
/// <see cref="SceneAnalysisStatus"/> answers "what happened to this unit?". Keeping
/// them apart is deliberate: a <see cref="SceneAnalysisStatus.Superseded"/> unit is
/// fact-bearing and queryable, and still leaves the run <see cref="Stale"/>.
/// </remarks>
public enum SceneAnalyticsReadiness
{
    /// <summary>The camera has never had a scene revision; no unit exists.</summary>
    NotConfigured = 0,

    /// <summary>The active revision has no enabled geometry: analytics are switched off.</summary>
    Disabled = 1,

    /// <summary>A unit for the active identity is queued or running, or does not exist yet.</summary>
    Pending = 2,

    /// <summary>A completed unit exists for the active revision and current algorithm version.</summary>
    Ready = 3,

    /// <summary>The unit for the active identity failed.</summary>
    Failed = 4,

    /// <summary>Facts exist only for an older revision or algorithm version.</summary>
    Stale = 5
}
