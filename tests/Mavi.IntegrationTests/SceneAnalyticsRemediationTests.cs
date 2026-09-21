using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// Cross-phase invariants an independent review found unprotected: which identity is
/// current after concurrent completions, and what an engine upgrade may do on its own.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsRemediationTests(PostgresFixture fixture)
{
    private const string NextAlgorithmVersion = "scene-analytics-v2";
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    // --- Supersession is identity recency, not completion order ------------

    /// <summary>The ordinary case: a newer revision completes after an older one.</summary>
    [Fact]
    public async Task ANewerRevisionCompletingSecondSupersedesTheOlderOne()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        var (first, second) = await ClaimBothRevisionsAsync(world, lifecycle);
        Assert.True((await lifecycle.CommitFactsAsync(first, world.Facts(first.AnalysisId, "N"), default)).IsSuccess);
        Assert.True((await lifecycle.CommitFactsAsync(second, world.Facts(second.AnalysisId, "S"), default)).IsSuccess);

        Assert.Equal(SceneAnalysisStatus.Superseded, (await world.UnitAsync(first.AnalysisId)).Status);
        Assert.Equal(SceneAnalysisStatus.Completed, (await world.UnitAsync(second.AnalysisId)).Status);
    }

    /// <summary>
    /// The case the review found: the newer revision finishes first, and the older one
    /// finishes late. The late finisher must not take currency from it.
    /// </summary>
    /// <remarks>
    /// Completion order is not identity order. If it were, a slow analysis of last week's
    /// geometry could demote today's, readiness would report <c>Stale</c>, and re-analysis
    /// could not repair it because the newer identity's unique row already exists and
    /// classifies as already analysed.
    /// </remarks>
    [Fact]
    public async Task AnOlderRevisionFinishingLateNeverSupersedesTheNewerOne()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        var (older, newer) = await ClaimBothRevisionsAsync(world, lifecycle);

        // The newer identity completes first.
        Assert.True((await lifecycle.CommitFactsAsync(newer, world.Facts(newer.AnalysisId, "S"), default)).IsSuccess);
        var newerAfterCompletion = await world.UnitAsync(newer.AnalysisId);

        // The older identity finishes late. Its facts are valid for its own pinned
        // identity, so it completes — but it is born historical.
        Assert.True((await lifecycle.CommitFactsAsync(older, world.Facts(older.AnalysisId, "N"), default)).IsSuccess);

        var newerNow = await world.UnitAsync(newer.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Completed, newerNow.Status);
        Assert.Equal(newerAfterCompletion.VisibilitySequence, newerNow.VisibilitySequence);
        Assert.Equal(newerAfterCompletion.CompletedAtUtc, newerNow.CompletedAtUtc);
        Assert.Equal(newerAfterCompletion.AnalysedTrackCount, newerNow.AnalysedTrackCount);

        Assert.Equal(SceneAnalysisStatus.Superseded, (await world.UnitAsync(older.AnalysisId)).Status);

        // The newer identity's facts are exactly what it committed.
        await using var reader = world.Read();
        var motion = await reader.TrackMotionSummaries.AsNoTracking()
            .SingleAsync(x => x.AnalysisId == newer.AnalysisId);
        Assert.Equal("S", motion.Heading);
    }

    /// <summary>
    /// The same rule across the algorithm dimension: for one revision, a newer engine
    /// that completed first is not demoted by an older engine finishing late.
    /// </summary>
    [Fact]
    public async Task AnOlderAlgorithmFinishingLateNeverSupersedesTheNewerOne()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        var older = await RequestAndClaimAsync(
            world, lifecycle, world.RevisionId, SceneAnalyticsWorld.AlgorithmVersion);
        var newer = await RequestAndClaimAsync(
            world, lifecycle, world.RevisionId, NextAlgorithmVersion);

        Assert.True((await lifecycle.CommitFactsAsync(newer, world.Facts(newer.AnalysisId, "S"), default)).IsSuccess);
        Assert.True((await lifecycle.CommitFactsAsync(older, world.Facts(older.AnalysisId, "N"), default)).IsSuccess);

        Assert.Equal(SceneAnalysisStatus.Completed, (await world.UnitAsync(newer.AnalysisId)).Status);
        Assert.Equal(SceneAnalysisStatus.Superseded, (await world.UnitAsync(older.AnalysisId)).Status);
    }

    // --- An engine upgrade does not re-analyse history ---------------------

    /// <summary>
    /// A new algorithm version makes existing facts stale for readiness; it does not
    /// queue work (ADR-011 decision 3, plan §R). Re-analysis is explicit operator work.
    /// </summary>
    [Fact]
    public async Task AnAlgorithmUpgradeDoesNotAutomaticallyReAnalyseAnAnalysedRun()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;

        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await executor.ExecuteAsync(claim!, SceneAnalyticsWorld.ExecutionIdentity, new SceneAnalyticsOptions(), default);
        Assert.Equal(SceneAnalysisStatus.Completed, (await world.UnitAsync(claim!.AnalysisId)).Status);

        // The binary is upgraded. Reconciliation runs under the new engine identity.
        var queued = await QueueAsync(lifecycle, NextAlgorithmVersion);

        Assert.Equal(0, queued);
        await using var reader = world.Read();
        Assert.Equal(1, await reader.SceneAnalyses.CountAsync());
        Assert.DoesNotContain(
            await reader.SceneAnalyses.AsNoTracking().ToListAsync(),
            unit => unit.AlgorithmVersion == NextAlgorithmVersion);

        // Explicit re-analysis is still able to create it.
        var requested = await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(world.RevisionId, NextAlgorithmVersion), default);
        Assert.Equal(SceneAnalysisQueueOutcome.Created, requested.Outcome);
    }

    /// <summary>
    /// The upgrade must not break the things reconciliation is for: a run that has never
    /// been analysed is still queued under the new engine.
    /// </summary>
    [Fact]
    public async Task AnAlgorithmUpgradeStillQueuesARunThatWasNeverAnalysed()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        Assert.Equal(1, await QueueAsync(lifecycle, NextAlgorithmVersion));

        await using var reader = world.Read();
        var unit = await reader.SceneAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(NextAlgorithmVersion, unit.AlgorithmVersion);
    }

    // --- Helpers -----------------------------------------------------------

    private static Task<int> QueueAsync(SceneAnalysisLifecycle lifecycle, string algorithmVersion) =>
        lifecycle.QueueEligibleUnitsAsync(
            algorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            null,
            Now.AddDays(-1),
            50,
            default);

    /// <summary>Queues a unit for the active revision and one for a newer revision, and claims both.</summary>
    private static async Task<(SceneAnalysisClaim Older, SceneAnalysisClaim Newer)> ClaimBothRevisionsAsync(
        SceneAnalyticsWorld world,
        SceneAnalysisLifecycle lifecycle)
    {
        var older = await RequestAndClaimAsync(
            world, lifecycle, world.RevisionId, SceneAnalyticsWorld.AlgorithmVersion);
        var newRevisionId = await world.ActivateNewRevisionAsync(Now.AddMinutes(1));
        var newer = await RequestAndClaimAsync(
            world, lifecycle, newRevisionId, SceneAnalyticsWorld.AlgorithmVersion);
        return (older, newer);
    }

    private static async Task<SceneAnalysisClaim> RequestAndClaimAsync(
        SceneAnalyticsWorld world,
        SceneAnalysisLifecycle lifecycle,
        Guid revisionId,
        string algorithmVersion)
    {
        var created = await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(revisionId, algorithmVersion), default);
        Assert.Equal(SceneAnalysisQueueOutcome.Created, created.Outcome);

        // Claimed as the host that owns that engine identity would: a host for another
        // version could not take this unit at all, which is the point of the fence.
        var claim = await lifecycle.ClaimNextAsync(
                SceneAnalyticsWorld.IdentityFor(algorithmVersion), Policy, default)
            ?? throw new InvalidOperationException("No unit was claimable.");
        Assert.Equal(created.AnalysisId, claim.AnalysisId);
        return claim;
    }
}
