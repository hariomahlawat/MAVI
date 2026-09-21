using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// A host may execute only a unit whose persisted analytics identity it can actually
/// reproduce.
/// </summary>
/// <remarks>
/// <para>
/// <c>AlgorithmVersion</c> and <c>ParametersSha256</c> record what a unit's facts were
/// computed under, and that record is worth nothing unless no host can compute under a
/// different one. The platform runs multiple hosts by design — <c>SKIP LOCKED</c> exists
/// for that — so a deployment boundary really does put a v1 unit and a v2 host in one
/// database, in both directions.
/// </para>
/// <para>
/// The fence lives in the claim predicate rather than in a check afterwards, because
/// claiming consumes an attempt and hides the unit from the host that could have run it.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsExecutionIdentityTests(PostgresFixture fixture)
{
    private const string NextAlgorithmVersion = "scene-analytics-v2";
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    /// <summary>An upgraded host must leave the previous engine's queued work alone.</summary>
    [Fact]
    public async Task AHostForANewEngineCannotClaimAUnitPinnedToTheOldOne()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);

        var claim = await lifecycle.ClaimNextAsync(
            SceneAnalyticsWorld.IdentityFor(NextAlgorithmVersion), Policy, default);

        Assert.Null(claim);

        // The unit is untouched: not failed, not superseded, not started.
        var unit = await world.Read().SceneAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(SceneAnalysisStatus.Queued, unit.Status);
        Assert.Equal(0, unit.AttemptCount);
        Assert.Null(unit.StartedAtUtc);
    }

    /// <summary>
    /// The rolling-upgrade direction: a surviving old host must not run new-engine work.
    /// </summary>
    [Fact]
    public async Task AHostForTheOldEngineCannotClaimAUnitPinnedToTheNewOne()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(world.RevisionId, NextAlgorithmVersion), default);

        var claim = await lifecycle.ClaimNextAsync(
            SceneAnalyticsWorld.ExecutionIdentity, Policy, default);

        Assert.Null(claim);
        Assert.Equal(SceneAnalysisStatus.Queued, (await world.Read().SceneAnalyses.AsNoTracking().SingleAsync()).Status);
    }

    /// <summary>
    /// The parameter set is half the identity. A host on the same engine version whose
    /// parameters differ would produce different facts under a digest that says otherwise.
    /// </summary>
    [Fact]
    public async Task AMatchingVersionWithDifferentParametersCannotBeClaimed()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);

        var claim = await lifecycle.ClaimNextAsync(
            SceneAnalyticsWorld.IdentityFor(SceneAnalyticsWorld.AlgorithmVersion, new string('e', 64)),
            Policy,
            default);

        Assert.Null(claim);
    }

    /// <summary>The fence must not block the ordinary case it exists to protect.</summary>
    [Fact]
    public async Task AMatchingHostClaimsAndCompletesNormally()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;
        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);

        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.NotNull(claim);

        var result = await executor.ExecuteAsync(
            claim, SceneAnalyticsWorld.ExecutionIdentity, new SceneAnalyticsOptions(), default);

        Assert.True(result.IsSuccess);
        Assert.Equal(SceneAnalysisStatus.Completed, (await world.UnitAsync(claim.AnalysisId)).Status);
    }

    /// <summary>
    /// The executor's own guard, behind the claim predicate. If a mismatched claim ever
    /// reaches it, it must write nothing rather than compute under the wrong identity —
    /// and in particular must not fail the unit, which would burn a historical unit's
    /// attempts merely because a newer binary is running.
    /// </summary>
    [Fact]
    public async Task TheExecutorRefusesAMismatchedClaimWithoutTouchingTheUnit()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;
        await QueueAsync(lifecycle, SceneAnalyticsWorld.AlgorithmVersion);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var before = await world.UnitAsync(claim!.AnalysisId);

        var result = await executor.ExecuteAsync(
            claim, SceneAnalyticsWorld.IdentityFor(NextAlgorithmVersion), new SceneAnalyticsOptions(), default);

        Assert.False(result.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.EngineIdentityMismatch, result.FailureCode);

        var after = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(before.Status, after.Status);
        Assert.Equal(before.AttemptCount, after.AttemptCount);
        Assert.Null(after.FailureCode);
        Assert.Equal(before.ClaimTokenHash, after.ClaimTokenHash);
        Assert.Empty(await world.Read().TrackAnalysisOutcomes.ToListAsync());
    }

    private static Task<int> QueueAsync(SceneAnalysisLifecycle lifecycle, string algorithmVersion) =>
        lifecycle.QueueEligibleUnitsAsync(
            algorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            null,
            Now.AddDays(-1),
            50,
            default);
}
