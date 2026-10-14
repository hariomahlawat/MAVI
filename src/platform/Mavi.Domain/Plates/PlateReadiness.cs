namespace Mavi.Domain.Plates;

/// <summary>Run-level plate readiness (ADR-013 §12; implementation amendment 2026-10-13, item 15). The states never overlap.</summary>
public enum PlateReadinessState
{
    /// <summary>No plate capability is bound in the release: no analysis is expected.</summary>
    NotConfigured,
    /// <summary>Plates are bound, but the run has no Vehicle Track.</summary>
    NotApplicable,
    Pending,
    Ready,
    Failed,
    /// <summary>Only an obsolete identity has facts; the preferred identity has not completed.</summary>
    Stale,
}

/// <summary>What the database says about one plate analysis of a run.</summary>
public sealed record PlateAnalysisFacts(
    Guid AnalysisId,
    string IdentityFingerprint,
    PlateAnalysisStatus Status,
    int AttemptCount,
    DateTimeOffset QueuedAtUtc,
    DateTimeOffset? CompletedAtUtc,
    string? FailureCode)
{
    public bool IsFactBearing => Status is PlateAnalysisStatus.Completed or PlateAnalysisStatus.Superseded;
}

/// <summary>What the database says about one run, for plate readiness.</summary>
public sealed record PlateRunFacts(
    bool IsCompletedAndVisible,
    DateTimeOffset? CompletedAtUtc,
    bool HasVehicleTracks,
    DateTimeOffset? CurrentActivationAtUtc,
    IReadOnlyList<PlateAnalysisFacts> Analyses);

public sealed record PlateAnalysisSummary(
    Guid AnalysisId,
    string IdentityFingerprint,
    PlateAnalysisStatus Status,
    int AttemptCount,
    DateTimeOffset QueuedAtUtc,
    DateTimeOffset? CompletedAtUtc,
    string? FailureCode,
    bool IsPreferredIdentity,
    bool IsDefault);

public sealed record PlateReadiness(
    Guid ProcessingRunId,
    PlateReadinessState State,
    string? Detail,
    string? PreferredIdentityFingerprint,
    Guid? DefaultAnalysisId,
    DateTimeOffset? LastReadyWorkerPollUtc,
    IReadOnlyList<PlateAnalysisSummary> Analyses);

/// <summary>
/// The plate readiness rule. The default analysis is derived — the fact-bearing analysis whose identity
/// is the preferred one — so historical <c>Completed</c>/<c>Superseded</c> labels never override the
/// binding, and a rollback re-derives it (ADR-013 implementation amendment 2026-09-28, item 5).
/// </summary>
public static class PlateReadinessRule
{
    public const string NoReadyWorker = "no_ready_plates_worker";
    public const string RunNotVisible = "run_not_visible";
    public const string AwaitingReconciliation = "awaiting_reconciliation";
    public const string HistoricalRunNotQueued = "historical_run_not_queued";
    public const string PreferredIdentityNotAnalysed = "preferred_identity_not_analysed";

    public static PlateReadiness Evaluate(
        Guid processingRunId,
        string? preferredFingerprint,
        string? notConfiguredReason,
        PlateRunFacts facts,
        DateTimeOffset? lastReadyWorkerPollUtc)
    {
        ArgumentNullException.ThrowIfNull(facts);
        var defaultAnalysis = preferredFingerprint is null
            ? null
            : facts.Analyses.FirstOrDefault(item => item.IsFactBearing && item.IdentityFingerprint == preferredFingerprint);
        var summaries = facts.Analyses
            .OrderBy(item => item.QueuedAtUtc).ThenBy(item => item.AnalysisId)
            .Select(item => new PlateAnalysisSummary(
                item.AnalysisId, item.IdentityFingerprint, item.Status, item.AttemptCount, item.QueuedAtUtc,
                item.CompletedAtUtc, item.FailureCode, item.IdentityFingerprint == preferredFingerprint,
                defaultAnalysis is not null && item.AnalysisId == defaultAnalysis.AnalysisId))
            .ToList();

        PlateReadiness Result(PlateReadinessState state, string? detail) =>
            new(processingRunId, state, detail, preferredFingerprint, defaultAnalysis?.AnalysisId, lastReadyWorkerPollUtc, summaries);

        if (preferredFingerprint is null)
            return Result(PlateReadinessState.NotConfigured, notConfiguredReason);
        if (!facts.IsCompletedAndVisible)
            return Result(PlateReadinessState.Pending, RunNotVisible);
        if (!facts.HasVehicleTracks)
            return Result(PlateReadinessState.NotApplicable, null);
        if (defaultAnalysis is not null)
            return Result(PlateReadinessState.Ready, null);

        var preferred = facts.Analyses.FirstOrDefault(item => item.IdentityFingerprint == preferredFingerprint);
        if (facts.Analyses.Any(item => item.IsFactBearing))
        {
            // Only obsolete identities have facts: nothing is current until the preferred identity
            // completes or re-analysis is requested.
            return Result(PlateReadinessState.Stale,
                preferred is null ? PreferredIdentityNotAnalysed : $"preferred_{preferred.Status.ToString().ToLowerInvariant()}");
        }

        if (preferred is null)
        {
            return Result(PlateReadinessState.Pending,
                facts.CurrentActivationAtUtc is { } activated && facts.CompletedAtUtc >= activated
                    ? AwaitingReconciliation
                    : HistoricalRunNotQueued);
        }

        if (preferred.Status == PlateAnalysisStatus.Failed)
            return Result(PlateReadinessState.Failed, preferred.FailureCode);

        return Result(PlateReadinessState.Pending,
            lastReadyWorkerPollUtc is null ? NoReadyWorker : preferred.Status.ToString().ToLowerInvariant());
    }
}
