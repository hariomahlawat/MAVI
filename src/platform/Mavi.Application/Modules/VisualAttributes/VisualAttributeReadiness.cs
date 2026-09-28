using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Modules.VisualAttributes;

/// <summary>Run-level readiness (ADR-013 §12). The states never overlap.</summary>
public enum VisualAttributeReadinessState
{
    NotConfigured,
    NotApplicable,
    Pending,
    Ready,
    Failed,
    Stale,
}

public sealed record VisualAttributeAnalysisFacts(
    Guid AnalysisId,
    string IdentityFingerprint,
    VisualAttributeAnalysisStatus Status,
    int AttemptCount,
    DateTimeOffset QueuedAtUtc,
    DateTimeOffset? CompletedAtUtc,
    string? FailureCode)
{
    public bool IsFactBearing => Status is VisualAttributeAnalysisStatus.Completed or VisualAttributeAnalysisStatus.Superseded;
}

/// <summary>What the database says about one run, for readiness.</summary>
public sealed record VisualAttributeRunFacts(
    bool IsCompletedAndVisible,
    DateTimeOffset? CompletedAtUtc,
    bool HasApplicableTracks,
    DateTimeOffset? CurrentActivationAtUtc,
    IReadOnlyList<VisualAttributeAnalysisFacts> Analyses);

public sealed record VisualAttributeAnalysisSummary(
    Guid AnalysisId,
    string IdentityFingerprint,
    string Status,
    int AttemptCount,
    DateTimeOffset QueuedAtUtc,
    DateTimeOffset? CompletedAtUtc,
    string? FailureCode,
    bool IsPreferredIdentity,
    bool IsDefault);

public sealed record VisualAttributeReadiness(
    Guid ProcessingRunId,
    VisualAttributeReadinessState State,
    string? Detail,
    string? PreferredIdentityFingerprint,
    Guid? DefaultAnalysisId,
    DateTimeOffset? LastReadyWorkerPollUtc,
    IReadOnlyList<VisualAttributeAnalysisSummary> Analyses);

public interface IVisualAttributeReadinessReader
{
    /// <summary>The run's facts, or <see langword="null"/> when no such run exists.</summary>
    Task<VisualAttributeRunFacts?> ReadAsync(Guid processingRunId, string? preferredFingerprint,
        IReadOnlyList<string> applicableObjectClasses, CancellationToken cancellationToken);
}

/// <summary>
/// The readiness rule (S2b plan §4, §5). The default is derived — the fact-bearing analysis
/// whose identity is the preferred one — so historical <c>Completed</c>/<c>Superseded</c>
/// labels never override the binding, and a rollback re-derives it.
/// </summary>
public static class VisualAttributeReadinessRule
{
    public const string NoReadyWorker = "no_ready_attributes_worker";

    public static VisualAttributeReadiness Evaluate(
        Guid processingRunId,
        string? preferredFingerprint,
        string? notConfiguredReason,
        VisualAttributeRunFacts facts,
        DateTimeOffset? lastReadyWorkerPollUtc)
    {
        ArgumentNullException.ThrowIfNull(facts);
        var defaultAnalysis = preferredFingerprint is null
            ? null
            : facts.Analyses.FirstOrDefault(item => item.IsFactBearing && item.IdentityFingerprint == preferredFingerprint);
        var summaries = facts.Analyses
            .OrderBy(item => item.QueuedAtUtc).ThenBy(item => item.AnalysisId)
            .Select(item => new VisualAttributeAnalysisSummary(
                item.AnalysisId, item.IdentityFingerprint, item.Status.ToString(), item.AttemptCount, item.QueuedAtUtc,
                item.CompletedAtUtc, item.FailureCode, item.IdentityFingerprint == preferredFingerprint,
                defaultAnalysis is not null && item.AnalysisId == defaultAnalysis.AnalysisId))
            .ToList();

        VisualAttributeReadiness Result(VisualAttributeReadinessState state, string? detail) =>
            new(processingRunId, state, detail, preferredFingerprint, defaultAnalysis?.AnalysisId, lastReadyWorkerPollUtc, summaries);

        if (preferredFingerprint is null)
            return Result(VisualAttributeReadinessState.NotConfigured, notConfiguredReason);
        if (!facts.IsCompletedAndVisible)
            return Result(VisualAttributeReadinessState.Pending, "run_not_visible");
        if (!facts.HasApplicableTracks)
            return Result(VisualAttributeReadinessState.NotApplicable, null);
        if (defaultAnalysis is not null)
            return Result(VisualAttributeReadinessState.Ready, null);

        var preferred = facts.Analyses.FirstOrDefault(item => item.IdentityFingerprint == preferredFingerprint);
        if (facts.Analyses.Any(item => item.IsFactBearing))
        {
            // Only obsolete identities have facts: nothing is current until the preferred
            // identity completes or re-analysis is requested.
            return Result(VisualAttributeReadinessState.Stale, preferred is null ? "preferred_identity_not_analysed" : $"preferred_{preferred.Status.ToString().ToLowerInvariant()}");
        }

        if (preferred is null)
        {
            return Result(VisualAttributeReadinessState.Pending,
                facts.CurrentActivationAtUtc is { } activated && facts.CompletedAtUtc >= activated
                    ? "awaiting_reconciliation"
                    : "historical_run_not_queued");
        }

        if (preferred.Status == VisualAttributeAnalysisStatus.Failed)
            return Result(VisualAttributeReadinessState.Failed, preferred.FailureCode);

        return Result(VisualAttributeReadinessState.Pending,
            lastReadyWorkerPollUtc is null ? NoReadyWorker : preferred.Status.ToString().ToLowerInvariant());
    }
}

public sealed class VisualAttributeReadinessService(
    IVisualAttributeRelease release,
    IVisualAttributeReadinessReader reader,
    VisualAttributeWorkerPresence presence,
    Microsoft.Extensions.Options.IOptions<VisualAttributeOptions> options)
{
    public async Task<VisualAttributeReadiness?> GetAsync(Guid processingRunId, CancellationToken cancellationToken)
    {
        var definition = release.Resolution.Definition;
        var fingerprint = definition?.Identity.Fingerprint;
        var classes = definition is null ? [] : definition.Schema.ApplicableObjectClasses();
        var facts = await reader.ReadAsync(processingRunId, fingerprint, classes, cancellationToken);
        if (facts is null) return null;
        var lastPoll = fingerprint is null
            ? null
            : presence.LastReadyPoll(fingerprint, TimeSpan.FromSeconds(options.Value.WorkerPresenceSeconds));
        return VisualAttributeReadinessRule.Evaluate(processingRunId, fingerprint, release.Resolution.NotConfiguredReason, facts, lastPoll);
    }
}
