namespace Mavi.Contracts.Api.Analytics;

/// <summary>
/// The closed vocabularies and transport-level bounds of the scene-analytics
/// contract (ADR-011). Geometry, temporal and lifecycle behaviour live in the
/// domain; only the values that cross the wire are fixed here.
/// </summary>
public static class SceneAnalyticsContractRules
{
    /// <summary>Lifecycle of one analysis unit.</summary>
    public static readonly IReadOnlyList<string> StatusValues =
        ["Queued", "Running", "Completed", "Failed", "Superseded"];

    /// <summary>Analytics readiness derived for a processing run.</summary>
    public static readonly IReadOnlyList<string> ReadinessValues =
        ["NotConfigured", "Disabled", "Pending", "Ready", "Failed", "Stale"];

    /// <summary>Scopes accepted when re-analysing a camera's existing runs.</summary>
    public static readonly IReadOnlyList<string> ReanalysisScopeValues =
        ["latestRuns", "allRuns"];

    public const string DefaultReanalysisScope = "latestRuns";

    /// <summary>
    /// Returned to an attempt whose ownership no longer holds. A stale attempt
    /// writes nothing: no facts, no completion, no failure, no supersede and no
    /// visibility sequence.
    /// </summary>
    public const string StaleAttemptCode = "analytics_attempt_stale";

    /// <summary>
    /// Returned when a caller demanded complete coverage and the query could not
    /// evaluate every run in its scope.
    /// </summary>
    public const string IncompleteCoverageCode = "track_analytics_incomplete";

    public static bool IsStatus(string? value) => Contains(StatusValues, value);

    public static bool IsReadiness(string? value) => Contains(ReadinessValues, value);

    public static bool IsReanalysisScope(string? value) => Contains(ReanalysisScopeValues, value);

    private static bool Contains(IReadOnlyList<string> allowed, string? value)
    {
        if (value is null)
        {
            return false;
        }

        for (var index = 0; index < allowed.Count; index++)
        {
            if (string.Equals(allowed[index], value, StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }
}
