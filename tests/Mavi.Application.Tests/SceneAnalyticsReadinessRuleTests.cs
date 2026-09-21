using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Analytics;
using Mavi.Domain.SceneAnalytics;

namespace Mavi.Application.Tests;

/// <summary>
/// Readiness is derived, so it is a pure function of the camera's current scope and the
/// units that exist. These tests pin every branch of that function.
/// </summary>
/// <remarks>
/// The two distinctions that matter most are both here. "Never configured" and
/// "deliberately disabled" are separate answers, because an operator is owed the
/// difference between a gap and a switch-off. And a fact-bearing historical unit does not
/// make the active revision <c>Ready</c>: "are these facts readable?" and "is the current
/// geometry applied?" are different questions.
/// </remarks>
public sealed class SceneAnalyticsReadinessRuleTests
{
    private const string Version = "scene-analytics-v1";
    private static readonly Guid ActiveRevision = Guid.CreateVersion7();
    private static readonly Guid OldRevision = Guid.CreateVersion7();

    [Fact]
    public void ACameraWithNoActiveRevisionIsNotConfigured()
    {
        Assert.Equal(
            SceneAnalyticsReadinessRule.NotConfigured,
            SceneAnalyticsReadinessRule.Derive(NoRevisionScope(), [], Version));

        // A camera that does not resolve at all is the same answer, not an exception.
        Assert.Equal(
            SceneAnalyticsReadinessRule.NotConfigured,
            SceneAnalyticsReadinessRule.Derive(null, [], Version));
    }

    [Fact]
    public void ACameraWhoseActiveRevisionEnablesNothingIsDisabled() =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Disabled,
            SceneAnalyticsReadinessRule.Derive(Scope(enabled: false), [], Version));

    /// <summary>
    /// Disabled outranks any unit that happens to exist: the operator's current decision
    /// is that this camera produces no analytics.
    /// </summary>
    [Fact]
    public void DisabledOutranksAnExistingCompletedUnit() =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Disabled,
            SceneAnalyticsReadinessRule.Derive(
                Scope(enabled: false),
                [Unit(ActiveRevision, SceneAnalysisStatus.Completed)],
                Version));

    [Fact]
    public void ARunWithNoUnitYetIsPending() =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Pending,
            SceneAnalyticsReadinessRule.Derive(Scope(), [], Version));

    [Theory]
    [InlineData(SceneAnalysisStatus.Queued)]
    [InlineData(SceneAnalysisStatus.Running)]
    public void AUnitStillInFlightIsPending(SceneAnalysisStatus status) =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Pending,
            SceneAnalyticsReadinessRule.Derive(Scope(), [Unit(ActiveRevision, status)], Version));

    [Fact]
    public void ACompletedUnitForTheActiveIdentityIsReady() =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Ready,
            SceneAnalyticsReadinessRule.Derive(
                Scope(),
                [Unit(ActiveRevision, SceneAnalysisStatus.Completed)],
                Version));

    [Fact]
    public void AFailedUnitForTheActiveIdentityIsFailed() =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Failed,
            SceneAnalyticsReadinessRule.Derive(
                Scope(),
                [Unit(ActiveRevision, SceneAnalysisStatus.Failed)],
                Version));

    /// <summary>
    /// A failure on the current geometry is reported as a failure even though older facts
    /// are still readable. An operator whose current scene could not be applied needs the
    /// failure, not a reassuring note that something older worked.
    /// </summary>
    [Fact]
    public void AFailureOnTheActiveIdentityOutranksOlderFacts() =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Failed,
            SceneAnalyticsReadinessRule.Derive(
                Scope(),
                [
                    Unit(OldRevision, SceneAnalysisStatus.Superseded),
                    Unit(ActiveRevision, SceneAnalysisStatus.Failed),
                ],
                Version));

    [Theory]
    [InlineData(SceneAnalysisStatus.Completed)]
    [InlineData(SceneAnalysisStatus.Superseded)]
    public void FactsFromAnOlderRevisionAloneAreStale(SceneAnalysisStatus status) =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Stale,
            SceneAnalyticsReadinessRule.Derive(Scope(), [Unit(OldRevision, status)], Version));

    /// <summary>
    /// A new algorithm version makes existing facts stale without deleting them and
    /// without queueing anything: the identity changed, so the old unit is not the current
    /// one however successful it was.
    /// </summary>
    [Fact]
    public void FactsFromAnOlderAlgorithmVersionAreStale() =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Stale,
            SceneAnalyticsReadinessRule.Derive(
                Scope(),
                [Unit(ActiveRevision, SceneAnalysisStatus.Completed, "scene-analytics-v0")],
                Version));

    /// <summary>
    /// While the current geometry is being applied, history is still intact — so the
    /// honest word is stale, not pending.
    /// </summary>
    [Fact]
    public void AnInFlightCurrentUnitWithOlderFactsIsStaleRatherThanPending() =>
        Assert.Equal(
            SceneAnalyticsReadinessRule.Stale,
            SceneAnalyticsReadinessRule.Derive(
                Scope(),
                [
                    Unit(OldRevision, SceneAnalysisStatus.Superseded),
                    Unit(ActiveRevision, SceneAnalysisStatus.Running),
                ],
                Version));

    /// <summary>
    /// Every value this rule can produce must be one the contract admits; a readiness the
    /// wire vocabulary does not know is unrenderable.
    /// </summary>
    [Fact]
    public void EveryDerivableReadinessIsInTheContractVocabulary()
    {
        string[] derivable =
        [
            SceneAnalyticsReadinessRule.NotConfigured,
            SceneAnalyticsReadinessRule.Disabled,
            SceneAnalyticsReadinessRule.Pending,
            SceneAnalyticsReadinessRule.Ready,
            SceneAnalyticsReadinessRule.Failed,
            SceneAnalyticsReadinessRule.Stale,
        ];

        Assert.All(derivable, value => Assert.True(SceneAnalyticsContractRules.IsReadiness(value)));
        Assert.Equal([.. SceneAnalyticsContractRules.ReadinessValues.Order(StringComparer.Ordinal)],
            [.. derivable.Order(StringComparer.Ordinal)]);
    }

    /// <summary>
    /// The reconciliation floor is a function of host start, not of the current time.
    /// </summary>
    /// <remarks>
    /// A cutoff recomputed from "now" crawls forward, which turns a zero lookback from
    /// "do not backfill history" into "analyse nothing older than this instant".
    /// </remarks>
    [Theory]
    [InlineData(0)]
    [InlineData(7)]
    public void TheReconciliationFloorDependsOnlyOnHostStart(int lookbackDays)
    {
        var options = new SceneAnalyticsOptions { ReconcileLookbackDays = lookbackDays };
        var hostStart = new DateTimeOffset(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

        var floor = options.ReconcileFloor(hostStart);

        Assert.Equal(hostStart.AddDays(-lookbackDays), floor);
        Assert.Equal(floor, options.ReconcileFloor(hostStart));
    }

    private static SceneAnalyticsCameraScope Scope(bool enabled = true) =>
        new(Guid.CreateVersion7(), ActiveRevision, 4, enabled);

    private static SceneAnalyticsCameraScope NoRevisionScope() =>
        new(Guid.CreateVersion7(), null, null, false);

    private static SceneAnalysisUnitView Unit(
        Guid revisionId,
        SceneAnalysisStatus status,
        string algorithmVersion = Version) =>
        new(
            Guid.CreateVersion7(),
            Guid.CreateVersion7(),
            revisionId,
            revisionId == ActiveRevision ? 4 : 3,
            algorithmVersion,
            status,
            1,
            DateTimeOffset.UnixEpoch,
            null,
            null,
            null,
            0,
            0,
            status == SceneAnalysisStatus.Failed ? SceneAnalyticsErrorCodes.EngineFailed : null);
}
