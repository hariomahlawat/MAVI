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

        // The consequence the operator sees: history intact, current engine not applied.
        Assert.Equal(
            SceneAnalyticsReadinessRule.Stale,
            SceneAnalyticsReadinessRule.Derive(
                new SceneAnalyticsCameraScope(world.CameraId, world.RevisionId, 1, true),
                [.. (await reader.SceneAnalyses.AsNoTracking().ToListAsync()).Select(ToView)],
                NextAlgorithmVersion));

        // Explicit re-analysis is still able to create it.
        var requested = await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(world.RevisionId, NextAlgorithmVersion), default);
        Assert.Equal(SceneAnalysisQueueOutcome.Created, requested.Outcome);
    }

    /// <summary>
    /// Old-engine work that never produced facts must not strand the current engine.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The execution-identity fence means a v2 host cannot claim a v1 unit — correctly,
    /// because it cannot reproduce v1's facts. So if reconciliation also refused to
    /// create a v2 unit while any v1 row existed, a queued, running or failed v1 unit
    /// would deny the current engine automatic analytics indefinitely: nothing can
    /// execute the old row, and nothing may create a new one.
    /// </para>
    /// <para>
    /// The old row is left exactly as it is. Its lifecycle is its own, and algorithm
    /// version is part of the identity, so the current engine simply gets its own unit.
    /// </para>
    /// </remarks>
    [Fact]
    public async Task AQueuedOldEngineUnitDoesNotBlockTheCurrentEngine()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        Assert.Equal(1, await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion));
        var old = await world.Read().SceneAnalyses.AsNoTracking().SingleAsync();

        Assert.Equal(1, await QueueAsync(lifecycle, NextAlgorithmVersion));

        await AssertBothEnginesHaveAUnitAsync(world);
        var unchanged = await world.UnitAsync(old.Id);
        Assert.Equal(SceneAnalysisStatus.Queued, unchanged.Status);
        Assert.Equal(0, unchanged.AttemptCount);
        Assert.Equal(old.QueuedAtUtc, unchanged.QueuedAtUtc);
    }

    /// <summary>
    /// The in-flight case, which matters most: no surviving old host may exist to finish
    /// the v1 attempt, and the v2 host must not reclaim it. Ownership is untouched.
    /// </summary>
    [Fact]
    public async Task ARunningOldEngineUnitDoesNotBlockTheCurrentEngineOrLoseItsOwnership()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var before = await world.UnitAsync(claim!.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Running, before.Status);

        Assert.Equal(1, await QueueAsync(lifecycle, NextAlgorithmVersion));

        await AssertBothEnginesHaveAUnitAsync(world);

        // Lease expiry is still not ownership loss, and an engine upgrade is not either.
        var after = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Running, after.Status);
        Assert.Equal(before.AttemptCount, after.AttemptCount);
        Assert.Equal(before.ClaimTokenHash, after.ClaimTokenHash);
        Assert.Equal(before.LeaseExpiresAtUtc, after.LeaseExpiresAtUtc);
        Assert.Null(after.FailureCode);
    }

    [Fact]
    public async Task AFailedOldEngineUnitDoesNotBlockTheCurrentEngine()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.ReportFailureAsync(
            claim!, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, default);
        var before = await world.UnitAsync(claim!.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Failed, before.Status);

        Assert.Equal(1, await QueueAsync(lifecycle, NextAlgorithmVersion));

        await AssertBothEnginesHaveAUnitAsync(world);
        var after = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Failed, after.Status);
        Assert.Equal(before.FailureCode, after.FailureCode);
        Assert.Equal(before.AttemptCount, after.AttemptCount);
    }

    // --- The exact identity is never duplicated ----------------------------

    /// <summary>
    /// A failed unit for the current engine is recovered by explicit retry, never by a
    /// second unit for an identity that is unique by construction.
    /// </summary>
    [Fact]
    public async Task AFailedCurrentEngineUnitIsNeverDuplicated()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.ReportFailureAsync(
            claim!, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, default);

        Assert.Equal(0, await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion));

        var unit = await world.Read().SceneAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(SceneAnalysisStatus.Failed, unit.Status);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task APendingOrInFlightCurrentEngineUnitIsNeverDuplicated(bool claimIt)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);
        if (claimIt)
        {
            await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        }

        Assert.Equal(0, await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion));

        var unit = await world.Read().SceneAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(
            claimIt ? SceneAnalysisStatus.Running : SceneAnalysisStatus.Queued,
            unit.Status);
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

    /// <summary>Both engines hold a unit of their own for the same run and revision.</summary>
    private static async Task AssertBothEnginesHaveAUnitAsync(SceneAnalyticsWorld world)
    {
        await using var reader = world.Read();
        var units = await reader.SceneAnalyses.AsNoTracking().ToListAsync();

        Assert.Equal(2, units.Count);
        Assert.Contains(units, unit => unit.AlgorithmVersion == SceneAnalyticsWorld.AlgorithmVersion);
        var current = Assert.Single(units, unit => unit.AlgorithmVersion == NextAlgorithmVersion);
        Assert.Equal(SceneAnalysisStatus.Queued, current.Status);
        Assert.Equal(world.RevisionId, current.RevisionId);
    }

    private static SceneAnalysisUnitView ToView(SceneAnalysis unit) => new(
        unit.Id,
        unit.ProcessingRunId,
        unit.RevisionId,
        1,
        unit.AlgorithmVersion,
        unit.Status,
        unit.AttemptCount,
        unit.QueuedAtUtc,
        unit.StartedAtUtc,
        unit.CompletedAtUtc,
        unit.LeaseExpiresAtUtc,
        unit.AnalysedTrackCount,
        unit.UnavailableTrackCount,
        unit.FailureCode);

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
