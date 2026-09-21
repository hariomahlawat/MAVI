using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// The analysis unit's lifecycle against a real PostgreSQL server: what gets queued,
/// how a unit is claimed, reclaimed, exhausted, retried, completed and superseded.
/// </summary>
/// <remarks>
/// Nothing here is mocked and nothing waits on wall-clock time. Concurrency is exercised
/// with two lifecycles on two connections, exactly as two hosts would be, and every
/// deadline is moved by advancing the injected <see cref="TimeProvider"/>.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsLifecycleTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    // --- Reconciliation ----------------------------------------------------

    [Fact]
    public async Task AnEligibleRunIsQueuedExactlyOnce()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        Assert.Equal(1, await QueueAsync(lifecycle));

        // The second pass finds the unit it created and queues nothing.
        Assert.Equal(0, await QueueAsync(lifecycle));

        await using var reader = world.Read();
        var unit = await reader.SceneAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(world.RunId, unit.ProcessingRunId);
        Assert.Equal(world.RevisionId, unit.RevisionId);
        Assert.Equal(SceneAnalysisStatus.Queued, unit.Status);
        Assert.Equal(0, unit.AttemptCount);
        Assert.Null(unit.ClaimTokenHash);
    }

    /// <summary>
    /// An empty active revision is the only way to switch analytics off, so it must be
    /// the absence of a match rather than a flag the reconciler reads.
    /// </summary>
    [Fact]
    public async Task ACameraWhoseActiveRevisionEnablesNothingIsNeverQueued()
    {
        var world = await CreateAsync(analyticsEnabled: false);
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        Assert.Equal(0, await QueueAsync(lifecycle));
        Assert.Empty(await world.Read().SceneAnalyses.ToListAsync());
    }

    [Fact]
    public async Task ACameraWithNoSceneConfigurationIsNeverQueued()
    {
        var world = await CreateAsync();
        await using (var db = world.Read())
        {
            await db.Database.ExecuteSqlRawAsync(
                """
                UPDATE scene_configurations SET active_revision_id = NULL;
                DELETE FROM scene_configuration_revisions;
                DELETE FROM scene_configurations;
                """);
        }

        var (lifecycle, host) = world.Host();
        await using var _ = host;

        Assert.Equal(0, await QueueAsync(lifecycle));
    }

    /// <summary>
    /// Analytics are derived from evidence that is already visible; a run that has not
    /// been published cannot be analysed ahead of itself.
    /// </summary>
    [Fact]
    public async Task ARunWithNoVisibilitySequenceIsNeverQueued()
    {
        var world = await CreateAsync(runVisible: false);
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        Assert.Equal(0, await QueueAsync(lifecycle));
    }

    /// <summary>
    /// A geometry edit never silently reinterprets history: the new revision only picks
    /// up runs that complete after it was activated.
    /// </summary>
    [Fact]
    public async Task ANewRevisionDoesNotAutomaticallyReachBackwards()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        var newRevisionId = await world.ActivateNewRevisionAsync(Now.AddMinutes(5));

        Assert.Equal(0, await QueueAsync(lifecycle));
        Assert.DoesNotContain(
            await world.Read().SceneAnalyses.AsNoTracking().ToListAsync(),
            unit => unit.RevisionId == newRevisionId);

        // It is available on request, though, which is what re-analysis is for.
        var requested = await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(newRevisionId, SceneAnalyticsWorld.AlgorithmVersion),
            default);
        Assert.Equal(SceneAnalysisQueueOutcome.Created, requested.Outcome);
    }

    // --- Re-analysis requests ----------------------------------------------

    [Theory]
    [InlineData(SceneAnalysisStatus.Queued, SceneAnalysisQueueOutcome.AlreadyQueued)]
    [InlineData(SceneAnalysisStatus.Running, SceneAnalysisQueueOutcome.AlreadyRunning)]
    [InlineData(SceneAnalysisStatus.Completed, SceneAnalysisQueueOutcome.AlreadyAnalysed)]
    [InlineData(SceneAnalysisStatus.Failed, SceneAnalysisQueueOutcome.FailedRequiresRetry)]
    public async Task ARepeatedRequestCreatesNothingAndReportsWhatItFound(
        SceneAnalysisStatus state,
        SceneAnalysisQueueOutcome expected)
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        var created = await lifecycle.RequestAnalysisAsync(world.Identity, default);
        Assert.Equal(SceneAnalysisQueueOutcome.Created, created.Outcome);
        await DriveToAsync(world, lifecycle, created.AnalysisId, state);

        var repeated = await lifecycle.RequestAnalysisAsync(world.Identity, default);

        Assert.Equal(expected, repeated.Outcome);
        Assert.Equal(created.AnalysisId, repeated.AnalysisId);
        Assert.Equal(1, await world.Read().SceneAnalyses.CountAsync());
    }

    /// <summary>
    /// Two hosts requesting the same identity at once must produce one unit. The unique
    /// index decides it, not a check-then-insert, so there is no window between the two.
    /// </summary>
    [Fact]
    public async Task TwoConcurrentRequestsForOneIdentityCreateExactlyOneUnit()
    {
        var world = await CreateAsync();
        var (first, firstDb) = world.Host();
        var (second, secondDb) = world.Host();
        await using var _ = firstDb;
        await using var __ = secondDb;

        var results = await Task.WhenAll(
            first.RequestAnalysisAsync(world.Identity, default),
            second.RequestAnalysisAsync(world.Identity, default));

        Assert.Equal(1, results.Count(r => r.Outcome == SceneAnalysisQueueOutcome.Created));
        Assert.Equal(1, results.Count(r => r.Outcome == SceneAnalysisQueueOutcome.AlreadyQueued));
        Assert.Equal(results[0].AnalysisId, results[1].AnalysisId);
        Assert.Equal(1, await world.Read().SceneAnalyses.CountAsync());
    }

    // --- Claiming ----------------------------------------------------------

    [Fact]
    public async Task AClaimTakesTheUnitRunningAndPersistsOnlyTheTokenHash()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);

        Assert.NotNull(claim);
        Assert.Equal(1, claim.AttemptCount);
        Assert.Equal(SceneAnalysis.ClaimTokenByteLength, claim.ClaimToken.Length);
        Assert.Equal(Now.Add(Policy.LeaseDuration), claim.LeaseExpiresAtUtc);

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Running, unit.Status);
        Assert.Equal(1, unit.AttemptCount);
        Assert.NotNull(unit.ClaimTokenHash);
        Assert.Equal(32, unit.ClaimTokenHash.Length);
        Assert.NotEqual(claim.ClaimToken.ToArray(), unit.ClaimTokenHash);
        Assert.Equal(Now, unit.StartedAtUtc);
    }

    /// <summary>
    /// Two hosts claiming at the same instant must not both get the same unit. This is
    /// what <c>SKIP LOCKED</c> buys, and it is asserted against two real connections.
    /// </summary>
    [Fact]
    public async Task TwoHostsClaimingTogetherNeverGetTheSameUnit()
    {
        var world = await CreateAsync();
        var (setup, setupDb) = world.Host();
        await using var _ = setupDb;
        await QueueAsync(setup);

        var (first, firstDb) = world.Host();
        var (second, secondDb) = world.Host();
        await using var __ = firstDb;
        await using var ___ = secondDb;

        var claims = await Task.WhenAll(
            first.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default),
            second.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default));

        Assert.Single(claims, claim => claim is not null);
        var unit = await world.UnitAsync(claims.Single(c => c is not null)!.AnalysisId);
        Assert.Equal(1, unit.AttemptCount);
    }

    /// <summary>
    /// A host must step around a unit another host holds, not queue behind it.
    /// </summary>
    /// <remarks>
    /// Two hosts finishing with one claim each says nothing on its own: a claim that
    /// waited for the lock and a claim that skipped it look identical afterwards. So the
    /// first host holds a unit's row open, and the second is given a short command
    /// timeout — if it queues, it fails instead of quietly succeeding late.
    /// </remarks>
    [Fact]
    public async Task AHostSkipsPastAUnitAnotherHostHoldsRatherThanWaitingForIt()
    {
        var world = await CreateAsync();
        var (setup, setupDb) = world.Host();
        await using var _ = setupDb;
        await QueueAsync(setup);
        var secondRevisionId = await world.ActivateNewRevisionAsync(Now.AddMinutes(-24));
        await setup.RequestAnalysisAsync(
            world.IdentityFor(secondRevisionId, SceneAnalyticsWorld.AlgorithmVersion), default);

        var held = await world.Read().SceneAnalyses.AsNoTracking()
            .OrderBy(x => x.QueuedAtUtc).ThenBy(x => x.Id).Select(x => x.Id).FirstAsync();

        // One host takes the first unit's row and keeps it.
        await using var holder = world.Read();
        await using var holding = await holder.Database.BeginTransactionAsync();
        await holder.Database.ExecuteSqlInterpolatedAsync(
            $"SELECT id FROM scene_analyses WHERE id = {held} FOR UPDATE");

        var (impatient, impatientDb) = world.ImpatientHost();
        await using var __ = impatientDb;

        var claim = await impatient.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);

        Assert.NotNull(claim);
        Assert.NotEqual(held, claim.AnalysisId);
        await holding.RollbackAsync();
    }

    [Fact]
    public async Task NothingIsClaimableWhileTheLeaseAndItsGraceHold()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);

        // Past the lease, but still inside the grace.
        world.Clock.Advance(Policy.LeaseDuration + TimeSpan.FromSeconds(30));

        Assert.Null(await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default));
    }

    /// <summary>
    /// A reclaim is a claim of a running unit: a new attempt number and a new token, so
    /// the previous pair can never validate again.
    /// </summary>
    [Fact]
    public async Task AnAbandonedUnitIsReclaimedWithANewAttemptAndANewToken()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var first = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var firstHash = (await world.UnitAsync(first!.AnalysisId)).ClaimTokenHash;

        world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
        var second = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);

        Assert.NotNull(second);
        Assert.Equal(first.AnalysisId, second.AnalysisId);
        Assert.Equal(2, second.AttemptCount);
        Assert.NotEqual(first.ClaimToken.ToArray(), second.ClaimToken.ToArray());

        var unit = await world.UnitAsync(second.AnalysisId);
        Assert.Equal(2, unit.AttemptCount);
        Assert.NotEqual(firstHash, unit.ClaimTokenHash);
    }

    [Fact]
    public async Task AUnitWithNoAttemptsLeftIsNotClaimedAgain()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        for (var attempt = 1; attempt <= Policy.MaximumAttempts; attempt++)
        {
            var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
            Assert.Equal(attempt, claim!.AttemptCount);
            world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
        }

        Assert.Null(await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default));
    }

    // --- Terminal exhaustion -----------------------------------------------

    [Fact]
    public async Task TheLastAbandonedAttemptExhaustsTheUnitAndClearsItsToken()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        var claim = await ClaimLastAttemptAsync(world, lifecycle);

        world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
        Assert.Equal(1, await lifecycle.ExhaustAbandonedUnitsAsync(Policy, default));

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Failed, unit.Status);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptsExhausted, unit.FailureCode);
        Assert.Null(unit.ClaimTokenHash);
        Assert.Null(unit.LeaseExpiresAtUtc);
        Assert.Equal(world.Clock.GetUtcNow(), unit.CompletedAtUtc);
    }

    [Fact]
    public async Task ARunningUnitInsideItsGraceIsNotExhausted()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        var claim = await ClaimLastAttemptAsync(world, lifecycle);

        world.Clock.Advance(Policy.LeaseDuration + TimeSpan.FromSeconds(30));

        Assert.Equal(0, await lifecycle.ExhaustAbandonedUnitsAsync(Policy, default));
        Assert.Equal(SceneAnalysisStatus.Running, (await world.UnitAsync(claim.AnalysisId)).Status);
    }

    // --- Completion --------------------------------------------------------

    [Fact]
    public async Task CompletionWritesTheFactsAndTheUnitInOneCommit()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        world.Clock.Advance(TimeSpan.FromSeconds(30));

        var result = await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);

        Assert.True(result.IsSuccess);
        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Completed, unit.Status);
        Assert.Equal(1, unit.AnalysedTrackCount);
        Assert.Equal(0, unit.UnavailableTrackCount);
        Assert.NotNull(unit.VisibilitySequence);
        Assert.True(unit.VisibilitySequence > 0);
        Assert.Equal(world.Clock.GetUtcNow(), unit.CompletedAtUtc);

        // Ownership is surrendered on success, so no later write can claim to be this
        // attempt.
        Assert.Null(unit.ClaimTokenHash);
        Assert.Null(unit.LeaseExpiresAtUtc);

        await using var reader = world.Read();
        Assert.Single(await reader.TrackAnalysisOutcomes.ToListAsync());
        Assert.Single(await reader.TrackZoneVisits.ToListAsync());
        Assert.Single(await reader.TrackZoneSummaries.ToListAsync());
        Assert.Single(await reader.TrackLineCrossings.ToListAsync());
        Assert.Single(await reader.TrackMotionSummaries.ToListAsync());
    }

    /// <summary>
    /// The visibility sequence comes from the same database-owned counter that run
    /// completion uses, so a search snapshot gates analytics exactly as it gates runs,
    /// with no second mechanism.
    /// </summary>
    [Fact]
    public async Task TheVisibilitySequenceComesFromTheSharedProcessingCounter()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);

        await using var reader = world.Read();
        var unit = await reader.SceneAnalyses.AsNoTracking().SingleAsync();
        var next = await NextSequenceAsync(world);

        Assert.True(next > unit.VisibilitySequence);
    }

    /// <summary>
    /// A same-unit rewrite replaces that unit's facts wholesale. Nothing accumulates,
    /// and nothing belonging to another unit is touched.
    /// </summary>
    [Fact]
    public async Task ARepeatedAttemptReplacesOnlyItsOwnFacts()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        // A first, historical unit for a different revision, left completed.
        var otherRevisionId = await world.ActivateNewRevisionAsync(Now.AddMinutes(-20));
        var other = await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(otherRevisionId, SceneAnalyticsWorld.AlgorithmVersion), default);
        var otherClaim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.CommitFactsAsync(otherClaim!, world.Facts(other.AnalysisId, "N"), default);

        // Now the unit under test fails its first attempt and is reclaimed.
        var created = await lifecycle.RequestAnalysisAsync(world.Identity, default);
        var first = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(created.AnalysisId, first!.AnalysisId);
        Assert.True((await lifecycle.CommitFactsAsync(first, world.Facts(first.AnalysisId, "E"), default)).IsSuccess);

        await ForceFailedAsync(world, first.AnalysisId);
        Assert.True((await lifecycle.RetryAsync(first.AnalysisId, default)).IsSuccess);
        var second = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(created.AnalysisId, second!.AnalysisId);
        Assert.True((await lifecycle.CommitFactsAsync(second, world.Facts(second.AnalysisId, "SE"), default)).IsSuccess);

        await using var reader = world.Read();
        var mine = await reader.TrackMotionSummaries.AsNoTracking()
            .Where(x => x.AnalysisId == created.AnalysisId).ToListAsync();
        Assert.Equal("SE", Assert.Single(mine).Heading);

        // The other unit's facts are exactly as it committed them.
        var theirs = await reader.TrackMotionSummaries.AsNoTracking()
            .Where(x => x.AnalysisId == other.AnalysisId).ToListAsync();
        Assert.Equal("N", Assert.Single(theirs).Heading);
    }

    // --- Supersede ---------------------------------------------------------

    /// <summary>
    /// A later success for a different identity makes the earlier one historical. Only
    /// its currency changes: a query that pinned that identity must keep reading exactly
    /// what it read before.
    /// </summary>
    [Fact]
    public async Task ALaterSuccessSupersedesTheEarlierOneWithoutTouchingItsFacts()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;

        await QueueAsync(lifecycle);
        var firstClaim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.CommitFactsAsync(firstClaim!, world.Facts(firstClaim!.AnalysisId, "N"), default);
        var before = await world.UnitAsync(firstClaim.AnalysisId);

        var newRevisionId = await world.ActivateNewRevisionAsync(Now.AddMinutes(1));
        world.Clock.Advance(TimeSpan.FromMinutes(2));
        await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(newRevisionId, SceneAnalyticsWorld.AlgorithmVersion), default);
        var secondClaim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.CommitFactsAsync(secondClaim!, world.Facts(secondClaim!.AnalysisId, "S"), default);

        var superseded = await world.UnitAsync(firstClaim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Superseded, superseded.Status);

        // Everything except the state is byte-for-byte what it was.
        Assert.Equal(before.VisibilitySequence, superseded.VisibilitySequence);
        Assert.Equal(before.CompletedAtUtc, superseded.CompletedAtUtc);
        Assert.Equal(before.AnalysedTrackCount, superseded.AnalysedTrackCount);
        Assert.Equal(before.UnavailableTrackCount, superseded.UnavailableTrackCount);

        await using var reader = world.Read();
        var historical = await reader.TrackMotionSummaries.AsNoTracking()
            .SingleAsync(x => x.AnalysisId == firstClaim.AnalysisId);
        Assert.Equal("N", historical.Heading);
        Assert.Equal(SceneAnalysisStatus.Completed, (await world.UnitAsync(secondClaim.AnalysisId)).Status);
    }

    // --- Failure and retry -------------------------------------------------

    [Fact]
    public async Task AFailedAttemptReturnsTheUnitToTheQueueWhileAttemptsRemain()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);

        var result = await lifecycle.ReportFailureAsync(
            claim!, SceneAnalyticsErrorCodes.EngineFailed, "boom", Policy.MaximumAttempts, default);

        Assert.True(result.IsSuccess);
        var unit = await world.UnitAsync(claim!.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Queued, unit.Status);
        Assert.Equal(SceneAnalyticsErrorCodes.EngineFailed, unit.FailureCode);
        Assert.Null(unit.ClaimTokenHash);

        // Immediately claimable again: no grace applies, because the unit is queued.
        var next = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(2, next!.AttemptCount);
    }

    [Fact]
    public async Task TheLastFailedAttemptFailsTheUnit()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        var claim = await ClaimLastAttemptAsync(world, lifecycle);

        await lifecycle.ReportFailureAsync(
            claim, SceneAnalyticsErrorCodes.EngineFailed, null, Policy.MaximumAttempts, default);

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Failed, unit.Status);
        Assert.Null(await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default));
    }

    /// <summary>
    /// Retry is a new cycle on the same row, never a second unit for an identity that is
    /// unique by construction — and it deletes nothing.
    /// </summary>
    [Fact]
    public async Task RetryResetsTheCycleOnTheSameUnitAndKeepsItsFacts()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        // Complete once so there are facts, then drive the unit to Failed.
        var success = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.CommitFactsAsync(success!, world.Facts(success!.AnalysisId), default);
        await ForceFailedAsync(world, success.AnalysisId);

        world.Clock.Advance(TimeSpan.FromMinutes(5));
        var result = await lifecycle.RetryAsync(success.AnalysisId, default);

        Assert.True(result.IsSuccess);
        var unit = await world.UnitAsync(success.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Queued, unit.Status);
        Assert.Equal(0, unit.AttemptCount);
        Assert.Null(unit.ClaimTokenHash);
        Assert.Null(unit.LeaseExpiresAtUtc);
        Assert.Null(unit.FailureCode);
        Assert.Null(unit.StartedAtUtc);
        Assert.Null(unit.CompletedAtUtc);
        Assert.Equal(world.Clock.GetUtcNow(), unit.QueuedAtUtc);

        Assert.Equal(1, await world.Read().SceneAnalyses.CountAsync());
        Assert.Single(await world.Read().TrackMotionSummaries.ToListAsync());
    }

    [Theory]
    [InlineData(SceneAnalysisStatus.Queued)]
    [InlineData(SceneAnalysisStatus.Running)]
    [InlineData(SceneAnalysisStatus.Completed)]
    public async Task RetryIsRefusedFromEveryStateButFailed(SceneAnalysisStatus state)
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        var created = await lifecycle.RequestAnalysisAsync(world.Identity, default);
        await DriveToAsync(world, lifecycle, created.AnalysisId, state);

        var result = await lifecycle.RetryAsync(created.AnalysisId, default);

        Assert.False(result.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.TransitionInvalid, result.ErrorCode);
        Assert.Equal(state, (await world.UnitAsync(created.AnalysisId)).Status);
    }

    // --- Helpers -----------------------------------------------------------

    private Task<SceneAnalyticsWorld> CreateAsync(bool analyticsEnabled = true, bool runVisible = true) =>
        SceneAnalyticsWorld.CreateAsync(fixture, Now, analyticsEnabled, runVisible);

    private static Task<int> QueueAsync(SceneAnalysisLifecycle lifecycle) =>
        lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            sourceCommit: null,
            earliestRunCompletedAtUtc: Now.AddDays(-1),
            batchSize: 50,
            default);

    /// <summary>Claims until the unit is on its last permitted attempt.</summary>
    private static async Task<SceneAnalysisClaim> ClaimLastAttemptAsync(
        SceneAnalyticsWorld world,
        SceneAnalysisLifecycle lifecycle)
    {
        await QueueAsync(lifecycle);
        SceneAnalysisClaim? claim = null;
        for (var attempt = 1; attempt <= Policy.MaximumAttempts; attempt++)
        {
            claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
            if (attempt < Policy.MaximumAttempts)
            {
                world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
            }
        }

        return claim!;
    }

    private static async Task DriveToAsync(
        SceneAnalyticsWorld world,
        SceneAnalysisLifecycle lifecycle,
        Guid analysisId,
        SceneAnalysisStatus state)
    {
        if (state == SceneAnalysisStatus.Queued) return;

        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(analysisId, claim!.AnalysisId);
        switch (state)
        {
            case SceneAnalysisStatus.Running:
                return;
            case SceneAnalysisStatus.Completed:
                Assert.True((await lifecycle.CommitFactsAsync(claim, world.Facts(analysisId), default)).IsSuccess);
                return;
            case SceneAnalysisStatus.Failed:
                await lifecycle.ReportFailureAsync(
                    claim, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, default);
                return;
            default:
                throw new ArgumentOutOfRangeException(nameof(state), state, "Unsupported target state.");
        }
    }

    /// <summary>
    /// Puts a completed unit into <c>Failed</c> directly, which the lifecycle itself
    /// never does — the point of the test that uses it is that retry keeps the facts a
    /// completed attempt left behind.
    /// </summary>
    private static async Task ForceFailedAsync(SceneAnalyticsWorld world, Guid analysisId)
    {
        await using var db = world.Read();
        await db.Database.ExecuteSqlInterpolatedAsync($"""
            UPDATE scene_analyses
               SET status = 'Failed', failure_code = 'analytics_engine_failed'
             WHERE id = {analysisId}
            """);
    }

    private static async Task<long> NextSequenceAsync(SceneAnalyticsWorld world)
    {
        await using var db = world.Read();
        await using var transaction = await db.Database.BeginTransactionAsync();
        var sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, default);
        await transaction.CommitAsync();
        return sequence;
    }
}
