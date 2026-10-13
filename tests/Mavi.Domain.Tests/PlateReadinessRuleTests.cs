using Mavi.Domain.Plates;

namespace Mavi.Domain.Tests;

/// <summary>
/// Run-level plate readiness, ported from the Visual Attribute readiness tests (ADR-013 §12; implementation amendment 2026-10-13, items 11 and 15): derived default selection, Stale when
/// only obsolete identities have facts, rollback re-derivation, and the operator signal that
/// distinguishes "no READY plates worker" from ordinary pending work.
/// </summary>
public sealed class PlateReadinessRuleTests
{
    private static readonly Guid Run = Guid.CreateVersion7();
    private static readonly string A = new('a', 64);
    private static readonly string B = new('b', 64);
    private static readonly DateTimeOffset T0 = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);

    private static PlateAnalysisFacts Unit(string fingerprint, PlateAnalysisStatus status, string? failure = null) =>
        new(Guid.CreateVersion7(), fingerprint, status, 1, T0, status is PlateAnalysisStatus.Queued or PlateAnalysisStatus.Running ? null : T0, failure);

    private static PlateRunFacts Facts(params PlateAnalysisFacts[] analyses) =>
        new(IsCompletedAndVisible: true, CompletedAtUtc: T0, HasVehicleTracks: true, CurrentActivationAtUtc: T0.AddMinutes(-1), analyses);

    private static PlateReadiness Evaluate(string? preferred, PlateRunFacts facts, DateTimeOffset? poll = null) =>
        PlateReadinessRule.Evaluate(Run, preferred, preferred is null ? "plate_role_not_bound" : null, facts, poll);

    [Fact]
    public void NoPreferredIdentityIsNotConfigured()
    {
        var readiness = Evaluate(null, Facts(Unit(A, PlateAnalysisStatus.Completed)));
        Assert.Equal(PlateReadinessState.NotConfigured, readiness.State);
        Assert.Equal("plate_role_not_bound", readiness.Detail);
        Assert.Null(readiness.DefaultAnalysisId);
    }

    [Fact]
    public void NotApplicableIsDistinctFromNotConfigured()
    {
        var facts = Facts() with { HasVehicleTracks = false };
        Assert.Equal(PlateReadinessState.NotApplicable, Evaluate(A, facts).State);
    }

    [Fact]
    public void TheDefaultIsThePreferredIdentitysFactBearingAnalysis()
    {
        var a = Unit(A, PlateAnalysisStatus.Completed);
        var readiness = Evaluate(A, Facts(a, Unit(B, PlateAnalysisStatus.Superseded)));
        Assert.Equal(PlateReadinessState.Ready, readiness.State);
        Assert.Equal(a.AnalysisId, readiness.DefaultAnalysisId);
        Assert.Single(readiness.Analyses, item => item.IsDefault);
    }

    [Fact]
    public void ALateObsoleteCompletionDoesNotBecomeTheDefault()
    {
        // B is preferred and completed; A finished later and landed as history.
        var b = Unit(B, PlateAnalysisStatus.Completed);
        var lateA = Unit(A, PlateAnalysisStatus.Superseded);
        var readiness = Evaluate(B, Facts(b, lateA));
        Assert.Equal(b.AnalysisId, readiness.DefaultAnalysisId);
    }

    [Fact]
    public void RollbackReDerivesTheDefaultFromTheExistingSuccessfulAnalysis()
    {
        // A was superseded by B; the binding is rolled back to A. No new unit, no rewritten
        // label: the existing successful A is the default again.
        var a = Unit(A, PlateAnalysisStatus.Superseded);
        var b = Unit(B, PlateAnalysisStatus.Completed);
        var readiness = Evaluate(A, Facts(a, b));
        Assert.Equal(PlateReadinessState.Ready, readiness.State);
        Assert.Equal(a.AnalysisId, readiness.DefaultAnalysisId);
    }

    [Fact]
    public void OnlyObsoleteCompletionsAreStaleWithNoDefault()
    {
        var readiness = Evaluate(B, Facts(Unit(A, PlateAnalysisStatus.Completed)));
        Assert.Equal(PlateReadinessState.Stale, readiness.State);
        Assert.Null(readiness.DefaultAnalysisId);
        Assert.Equal("preferred_identity_not_analysed", readiness.Detail);

        var running = Evaluate(B, Facts(Unit(A, PlateAnalysisStatus.Completed), Unit(B, PlateAnalysisStatus.Running)));
        Assert.Equal(PlateReadinessState.Stale, running.State);
        Assert.Equal("preferred_running", running.Detail);
    }

    [Fact]
    public void AFailedReplacementLeavesThePriorSuccessCurrentForItsOwnIdentity()
    {
        var a = Unit(A, PlateAnalysisStatus.Completed);
        Assert.Equal(PlateReadinessState.Ready, Evaluate(A, Facts(a, Unit(B, PlateAnalysisStatus.Failed))).State);
        // Under B the failed replacement is Stale, not Failed: facts exist, just not current.
        Assert.Equal(PlateReadinessState.Stale, Evaluate(B, Facts(a, Unit(B, PlateAnalysisStatus.Failed))).State);
    }

    [Fact]
    public void FailedOnlyWhenThePreferredUnitFailedAndNothingElseHasFacts()
    {
        var readiness = Evaluate(A, Facts(Unit(A, PlateAnalysisStatus.Failed, "plate_deadline_exceeded")));
        Assert.Equal(PlateReadinessState.Failed, readiness.State);
        Assert.Equal("plate_deadline_exceeded", readiness.Detail);
    }

    [Fact]
    public void PendingSaysWhetherAReadyWorkerIsPresent()
    {
        var facts = Facts(Unit(A, PlateAnalysisStatus.Queued));
        var none = Evaluate(A, facts, poll: null);
        Assert.Equal(PlateReadinessState.Pending, none.State);
        Assert.Equal(PlateReadinessRule.NoReadyWorker, none.Detail);

        var present = Evaluate(A, facts, poll: T0);
        Assert.Equal(PlateReadinessState.Pending, present.State);
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
        var facts = Facts() with { IsCompletedAndVisible = false, HasVehicleTracks = false };
        Assert.Equal(PlateReadinessState.Pending, Evaluate(A, facts).State);
    }
}
