using Mavi.Application.Modules.VisualAttributes;
using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Tests.VisualAttributes;

/// <summary>
/// Run-level readiness (ADR-013 §12; S2b plan §4, §5): derived default selection, Stale when
/// only obsolete identities have facts, rollback re-derivation, and the operator signal that
/// distinguishes "no READY attributes worker" from ordinary pending work.
/// </summary>
public sealed class VisualAttributeReadinessRuleTests
{
    private static readonly Guid Run = Guid.CreateVersion7();
    private static readonly string A = new('a', 64);
    private static readonly string B = new('b', 64);
    private static readonly DateTimeOffset T0 = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);

    private static VisualAttributeAnalysisFacts Unit(string fingerprint, VisualAttributeAnalysisStatus status, string? failure = null) =>
        new(Guid.CreateVersion7(), fingerprint, status, 1, T0, status is VisualAttributeAnalysisStatus.Queued or VisualAttributeAnalysisStatus.Running ? null : T0, failure);

    private static VisualAttributeRunFacts Facts(params VisualAttributeAnalysisFacts[] analyses) =>
        new(IsCompletedAndVisible: true, CompletedAtUtc: T0, HasApplicableTracks: true, CurrentActivationAtUtc: T0.AddMinutes(-1), analyses);

    private static VisualAttributeReadiness Evaluate(string? preferred, VisualAttributeRunFacts facts, DateTimeOffset? poll = null) =>
        VisualAttributeReadinessRule.Evaluate(Run, preferred, preferred is null ? "attribute_role_not_bound" : null, facts, poll);

    [Fact]
    public void NoPreferredIdentityIsNotConfigured()
    {
        var readiness = Evaluate(null, Facts(Unit(A, VisualAttributeAnalysisStatus.Completed)));
        Assert.Equal(VisualAttributeReadinessState.NotConfigured, readiness.State);
        Assert.Equal("attribute_role_not_bound", readiness.Detail);
        Assert.Null(readiness.DefaultAnalysisId);
    }

    [Fact]
    public void NotApplicableIsDistinctFromNotConfigured()
    {
        var facts = Facts() with { HasApplicableTracks = false };
        Assert.Equal(VisualAttributeReadinessState.NotApplicable, Evaluate(A, facts).State);
    }

    [Fact]
    public void TheDefaultIsThePreferredIdentitysFactBearingAnalysis()
    {
        var a = Unit(A, VisualAttributeAnalysisStatus.Completed);
        var readiness = Evaluate(A, Facts(a, Unit(B, VisualAttributeAnalysisStatus.Superseded)));
        Assert.Equal(VisualAttributeReadinessState.Ready, readiness.State);
        Assert.Equal(a.AnalysisId, readiness.DefaultAnalysisId);
        Assert.Single(readiness.Analyses, item => item.IsDefault);
    }

    [Fact]
    public void ALateObsoleteCompletionDoesNotBecomeTheDefault()
    {
        // B is preferred and completed; A finished later and landed as history.
        var b = Unit(B, VisualAttributeAnalysisStatus.Completed);
        var lateA = Unit(A, VisualAttributeAnalysisStatus.Superseded);
        var readiness = Evaluate(B, Facts(b, lateA));
        Assert.Equal(b.AnalysisId, readiness.DefaultAnalysisId);
    }

    [Fact]
    public void RollbackReDerivesTheDefaultFromTheExistingSuccessfulAnalysis()
    {
        // A was superseded by B; the binding is rolled back to A. No new unit, no rewritten
        // label: the existing successful A is the default again.
        var a = Unit(A, VisualAttributeAnalysisStatus.Superseded);
        var b = Unit(B, VisualAttributeAnalysisStatus.Completed);
        var readiness = Evaluate(A, Facts(a, b));
        Assert.Equal(VisualAttributeReadinessState.Ready, readiness.State);
        Assert.Equal(a.AnalysisId, readiness.DefaultAnalysisId);
    }

    [Fact]
    public void OnlyObsoleteCompletionsAreStaleWithNoDefault()
    {
        var readiness = Evaluate(B, Facts(Unit(A, VisualAttributeAnalysisStatus.Completed)));
        Assert.Equal(VisualAttributeReadinessState.Stale, readiness.State);
        Assert.Null(readiness.DefaultAnalysisId);
        Assert.Equal("preferred_identity_not_analysed", readiness.Detail);

        var running = Evaluate(B, Facts(Unit(A, VisualAttributeAnalysisStatus.Completed), Unit(B, VisualAttributeAnalysisStatus.Running)));
        Assert.Equal(VisualAttributeReadinessState.Stale, running.State);
        Assert.Equal("preferred_running", running.Detail);
    }

    [Fact]
    public void AFailedReplacementLeavesThePriorSuccessCurrentForItsOwnIdentity()
    {
        var a = Unit(A, VisualAttributeAnalysisStatus.Completed);
        Assert.Equal(VisualAttributeReadinessState.Ready, Evaluate(A, Facts(a, Unit(B, VisualAttributeAnalysisStatus.Failed))).State);
        // Under B the failed replacement is Stale, not Failed: facts exist, just not current.
        Assert.Equal(VisualAttributeReadinessState.Stale, Evaluate(B, Facts(a, Unit(B, VisualAttributeAnalysisStatus.Failed))).State);
    }

    [Fact]
    public void FailedOnlyWhenThePreferredUnitFailedAndNothingElseHasFacts()
    {
        var readiness = Evaluate(A, Facts(Unit(A, VisualAttributeAnalysisStatus.Failed, "visual_attribute_deadline_exceeded")));
        Assert.Equal(VisualAttributeReadinessState.Failed, readiness.State);
        Assert.Equal("visual_attribute_deadline_exceeded", readiness.Detail);
    }

    [Fact]
    public void PendingSaysWhetherAReadyWorkerIsPresent()
    {
        var facts = Facts(Unit(A, VisualAttributeAnalysisStatus.Queued));
        var none = Evaluate(A, facts, poll: null);
        Assert.Equal(VisualAttributeReadinessState.Pending, none.State);
        Assert.Equal(VisualAttributeReadinessRule.NoReadyWorker, none.Detail);

        var present = Evaluate(A, facts, poll: T0);
        Assert.Equal(VisualAttributeReadinessState.Pending, present.State);
        Assert.Equal("queued", present.Detail);
    }

    [Fact]
    public void AHistoricalRunIsNotReportedAsAwaitingWork()
    {
        var facts = Facts() with { CompletedAtUtc = T0.AddDays(-1) };
        Assert.Equal("historical_run_not_queued", Evaluate(A, facts).Detail);
        Assert.Equal("awaiting_reconciliation", Evaluate(A, Facts()).Detail);
    }

    [Fact]
    public void AnInvisibleRunIsPendingNotApplicable()
    {
        var facts = Facts() with { IsCompletedAndVisible = false, HasApplicableTracks = false };
        Assert.Equal(VisualAttributeReadinessState.Pending, Evaluate(A, facts).State);
    }
}
