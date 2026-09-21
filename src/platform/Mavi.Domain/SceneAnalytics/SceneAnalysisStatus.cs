namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// Lifecycle of one analysis unit (ADR-011 decision 3).
/// </summary>
/// <remarks>
/// <para>
/// <see cref="Completed"/> and <see cref="Superseded"/> are <b>both fact-bearing</b>:
/// they differ in currency, not validity. A unit is superseded when a later
/// analysis succeeds for a different identity of the same run, which says nothing
/// about whether this unit's facts are still correct for <i>its</i> identity — they
/// are, and they are immutable. Only <see cref="Failed"/> bears no facts.
/// </para>
/// <para>
/// Readiness is a separate, derived question (<see cref="SceneAnalyticsReadiness"/>)
/// and must never be inferred from this enum alone: a fact-bearing historical unit
/// does not make the camera's active revision ready.
/// </para>
/// </remarks>
public enum SceneAnalysisStatus
{
    /// <summary>Waiting to be claimed.</summary>
    Queued = 0,

    /// <summary>One fenced attempt currently owns the unit.</summary>
    Running = 1,

    /// <summary>Successful and current for its identity. Fact-bearing.</summary>
    Completed = 2,

    /// <summary>No currently successful attempt. Explicit retry starts a new cycle.</summary>
    Failed = 3,

    /// <summary>Successful and historical. Fact-bearing, immutable, still queryable.</summary>
    Superseded = 4
}
