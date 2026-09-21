using Mavi.Domain.SceneAnalytics;

namespace Mavi.Application.Modules.SceneAnalytics.Lifecycle;

/// <summary>
/// Derives a run's analytics readiness from the camera's current scene scope and the
/// units that exist for that run.
/// </summary>
/// <remarks>
/// <para>
/// Readiness is <b>derived, never stored</b>. It answers one question — "is the
/// <i>current</i> geometry applied to this run?" — and the answer changes the moment a
/// new revision is activated, without any row being rewritten. Storing it would mean
/// updating every run of a camera on every scene save, and the stored value would be
/// wrong in between.
/// </para>
/// <para>
/// It is a different question from "are these facts readable?", which is what a
/// fact-bearing state answers. A <c>Superseded</c> unit is fact-bearing and still
/// queryable for its own pinned identity, and it still does not make the active revision
/// <c>Ready</c>. Conflating the two is what produced the contradiction the plan's §G now
/// resolves, so they are kept apart here too.
/// </para>
/// </remarks>
public static class SceneAnalyticsReadinessRule
{
    public const string NotConfigured = "NotConfigured";
    public const string Disabled = "Disabled";
    public const string Pending = "Pending";
    public const string Ready = "Ready";
    public const string Failed = "Failed";
    public const string Stale = "Stale";

    public static string Derive(
        SceneAnalyticsCameraScope? scope,
        IReadOnlyList<SceneAnalysisUnitView> runUnits,
        string algorithmVersion)
    {
        ArgumentNullException.ThrowIfNull(runUnits);

        // A camera that was never configured and one whose active revision enables
        // nothing are reported separately: the first is a gap, the second is a decision.
        if (scope?.ActiveRevisionId is not { } activeRevisionId)
        {
            return NotConfigured;
        }

        if (!scope.AnalyticsEnabled)
        {
            return Disabled;
        }

        var current = runUnits.FirstOrDefault(unit =>
            unit.RevisionId == activeRevisionId
            && string.Equals(unit.AlgorithmVersion, algorithmVersion, StringComparison.Ordinal));

        switch (current?.Status)
        {
            case SceneAnalysisStatus.Completed:
                return Ready;
            case SceneAnalysisStatus.Failed:
                // Reported as failed even when older facts exist. An operator whose
                // current geometry could not be applied needs the failure, not a
                // reassuring note that something older worked.
                return Failed;
            default:
                break;
        }

        // No current unit, or one that is queued, running, or itself already superseded.
        // If some earlier identity did produce facts, the honest word is "stale": history
        // is intact and the current geometry has simply not been applied yet.
        return runUnits.Any(unit => unit.Status is SceneAnalysisStatus.Completed or SceneAnalysisStatus.Superseded)
            ? Stale
            : Pending;
    }
}
