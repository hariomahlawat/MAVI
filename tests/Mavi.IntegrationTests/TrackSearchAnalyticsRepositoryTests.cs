using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Intelligence;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// The analytic search at the repository, over a real database: scope resolution, the
/// pinned identity, coverage over the base scope, the fact-bearing snapshot-gated join,
/// every predicate's SQL translation, bounded item explanations and identity-aware
/// detail (plan §H, §S). The HTTP surface over the same behaviour is in
/// <c>TrackSearchAnalyticsApiTests</c>.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackSearchAnalyticsRepositoryTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    private static TrackSearchQuery Query(SceneAnalyticsWorld world, TrackAnalyticsQuery analytics) => new(
        world.CameraId, null, null, null, null, null, null, null, null, 50, analytics);

    // --- Scope and identity -------------------------------------------------

    [Fact]
    public async Task FirstPageResolvesTheActiveRevisionAndCurrentEngine()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var repository = Repository(world);

        var result = await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { ZoneId = world.ZoneId }), null, 51, default);

        var page = Assert.IsType<TrackAnalyticsSearchRepositoryPage>(result.Page);
        Assert.Equal(new TrackAnalyticsPinnedIdentity(world.CameraId, world.RevisionId, SceneAnalyticsWorld.AlgorithmVersion), page.Identity);
        Assert.Equal(world.TrackId, Assert.Single(page.Items).Id);
        Assert.Equal(1, page.Coverage.EvaluatedRuns);
        Assert.True(page.Coverage.Complete);
        Assert.Equal(1, page.Coverage.AnalysedTracks);
        Assert.Equal(0, page.Coverage.UnavailableTracks);
    }

    [Fact]
    public async Task EverySuppliedScopeMustResolveToTheSameCamera()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var repository = Repository(world);
        var analytics = TrackAnalyticsQuery.Empty with { Loitering = true };

        // Camera and its own video agree.
        var agreeing = await repository.SearchAnalyticsAsync(
            Query(world, analytics) with { VideoAssetId = world.VideoId }, null, 51, default);
        Assert.True(agreeing.IsValid);

        // A visible run resolves through its video.
        var byRun = await repository.SearchAnalyticsAsync(
            new TrackSearchQuery(null, null, world.RunId, null, null, null, null, null, null, 50, analytics), null, 51, default);
        Assert.True(byRun.IsValid);

        // No scope at all, an unknown camera, and a video of a different camera are refused.
        Assert.False((await repository.SearchAnalyticsAsync(
            new TrackSearchQuery(null, null, null, null, null, null, null, null, null, 50, analytics), null, 51, default)).IsValid);
        Assert.False((await repository.SearchAnalyticsAsync(
            Query(world, analytics) with { CameraId = Guid.CreateVersion7() }, null, 51, default)).IsValid);
        Assert.False((await repository.SearchAnalyticsAsync(
            Query(world, analytics) with { VideoAssetId = Guid.CreateVersion7() }, null, 51, default)).IsValid);
    }

    [Fact]
    public async Task GeometryOutsideTheResolvedRevisionIsRefused()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var repository = Repository(world);

        Assert.False((await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { ZoneId = Guid.CreateVersion7() }), null, 51, default)).IsValid);
        Assert.False((await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { LineId = Guid.CreateVersion7() }), null, 51, default)).IsValid);
        Assert.False((await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { SceneRevisionId = Guid.CreateVersion7() }), null, 51, default)).IsValid);
    }

    // --- Coverage buckets ---------------------------------------------------

    [Fact]
    public async Task ARunWithNoUnitYetIsPendingAndEvaluatesNothing()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var repository = Repository(world);

        var page = (await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { Loitering = true }), null, 51, default)).Page!;

        Assert.Empty(page.Items);
        Assert.Equal(1, page.Coverage.PendingRuns);
        Assert.Equal(0, page.Coverage.EvaluatedRuns);
        Assert.False(page.Coverage.Complete);
    }

    [Fact]
    public async Task ADisabledCameraPinsItsRealRevisionAndReportsDisabledRuns()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, analyticsEnabled: false);
        var repository = Repository(world);

        var page = (await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { Loitering = true }), null, 51, default)).Page!;

        Assert.Equal(world.RevisionId, page.Identity.SceneRevisionId);
        Assert.Equal(world.RevisionId, page.Coverage.SceneRevisionId);
        Assert.Equal(1, page.Coverage.DisabledRuns);
        Assert.Equal(0, page.Coverage.NotConfiguredRuns);
        Assert.Empty(page.Items);
    }

    [Fact]
    public async Task ANeverConfiguredCameraPinsNullAndReportsNotConfiguredRuns()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using (var db = world.Read())
        {
            // Remove the configuration so the camera has never been configured, as far
            // as analytics can tell.
            await db.Database.ExecuteSqlInterpolatedAsync($"DELETE FROM scene_zones WHERE revision_id = {world.RevisionId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"DELETE FROM trip_lines WHERE revision_id = {world.RevisionId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE scene_configurations SET active_revision_id = NULL WHERE camera_id = {world.CameraId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"DELETE FROM scene_configuration_revisions WHERE id = {world.RevisionId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"DELETE FROM scene_configurations WHERE camera_id = {world.CameraId}");
        }
        var repository = Repository(world);

        var page = (await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { MotionDirection = "NE" }), null, 51, default)).Page!;

        Assert.Null(page.Identity.SceneRevisionId);
        Assert.Null(page.Coverage.SceneRevisionId);
        Assert.Equal(1, page.Coverage.NotConfiguredRuns);
        Assert.Empty(page.Items);

        // A zone predicate against no revision names geometry that cannot exist.
        Assert.False((await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { ZoneId = world.ZoneId }), null, 51, default)).IsValid);
    }

    [Fact]
    public async Task AFailedUnitIsAFailedRun()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        // One permitted attempt, so the failure is terminal rather than a re-queue.
        await lifecycle.ReportFailureAsync(claim!, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, default);

        var page = (await Repository(world).SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { Loitering = true }), null, 51, default)).Page!;

        Assert.Equal(1, page.Coverage.FailedRuns);
        Assert.Empty(page.Items);
    }

    [Fact]
    public async Task ActivatingANewRevisionMakesTheRunStaleForANewSearchButNotForThePinnedOne()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var repository = Repository(world);
        var query = Query(world, TrackAnalyticsQuery.Empty with { ZoneId = world.ZoneId });

        var first = (await repository.SearchAnalyticsAsync(query, null, 1, default)).Page!;
        Assert.Equal(world.RevisionId, first.Identity.SceneRevisionId);
        Assert.Equal(1, first.Coverage.EvaluatedRuns);

        var newRevision = await world.ActivateNewRevisionAsync(Now.AddMinutes(1));

        // A continuation stays pinned to revision 1 and carries its coverage verbatim.
        var cursor = new TrackAnalyticsCursorPosition(
            new TrackCursorPosition(first.SnapshotUtc, first.SnapshotVisibilitySequence,
                Now.AddHours(1), Guid.CreateVersion7(), new string('a', 64)),
            first.Identity,
            first.Coverage);
        var continuation = (await repository.SearchAnalyticsAsync(query, cursor, 51, default)).Page!;
        Assert.Equal(world.RevisionId, continuation.Identity.SceneRevisionId);
        Assert.Equal(first.Coverage, continuation.Coverage);
        Assert.Equal(world.TrackId, Assert.Single(continuation.Items).Id);

        // A new search resolves revision 2, where nothing has been evaluated yet. The
        // fixture's second revision mints new geometry ids, so revision 1's zone is now
        // geometry outside the resolved revision and a zone predicate is refused; a
        // predicate that names no geometry shows the stale run.
        Assert.False((await repository.SearchAnalyticsAsync(query, null, 51, default)).IsValid);
        var fresh = (await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { Loitering = true }), null, 51, default)).Page!;
        Assert.Equal(newRevision, fresh.Identity.SceneRevisionId);
        Assert.Equal(1, fresh.Coverage.StaleRuns);
        Assert.Equal(0, fresh.Coverage.EvaluatedRuns);
        Assert.Empty(fresh.Items);

        // And explicitly naming revision 1 still gets its facts.
        var historical = (await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { ZoneId = world.ZoneId, SceneRevisionId = world.RevisionId }),
            null, 51, default)).Page!;
        Assert.Equal(1, historical.Coverage.EvaluatedRuns);
        Assert.Equal(world.TrackId, Assert.Single(historical.Items).Id);
    }

    [Fact]
    public async Task AHistoricalEngineVersionWithNoUnitIsStaleNotPending()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var repository = Repository(world);

        var page = (await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with
            {
                SceneRevisionId = world.RevisionId,
                AnalyticsAlgorithmVersion = "scene-analytics-v9",
            }), null, 51, default)).Page!;

        Assert.Equal("scene-analytics-v9", page.Identity.AlgorithmVersion);
        Assert.Equal(1, page.Coverage.StaleRuns);
        Assert.Equal(0, page.Coverage.PendingRuns);
    }

    [Fact]
    public async Task APinnedRevisionOfAnotherCameraIsRefusedOnContinuation()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var repository = Repository(world);
        var cursor = new TrackAnalyticsCursorPosition(
            new TrackCursorPosition(Now, 1, Now, Guid.CreateVersion7(), new string('a', 64)),
            new TrackAnalyticsPinnedIdentity(world.CameraId, Guid.CreateVersion7(), SceneAnalyticsWorld.AlgorithmVersion),
            new TrackAnalyticsCoverage(null, SceneAnalyticsWorld.AlgorithmVersion, 0, 0, 0, 0, 0, 0, 0, 0));

        var result = await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { Loitering = true }), cursor, 51, default);

        Assert.False(result.IsValid);
    }

    // --- Predicates ---------------------------------------------------------

    [Fact]
    public async Task EveryPredicateTranslatesAndMatchesTheFixtureFacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var repository = Repository(world);

        async Task<int> Count(TrackAnalyticsQuery analytics) =>
            (await repository.SearchAnalyticsAsync(Query(world, analytics), null, 51, default)).Page!.Items.Count;

        var empty = TrackAnalyticsQuery.Empty;
        // Fixture facts: one visit of 4 000 ms that neither began nor ended inside, loitering
        // true, one AToB crossing at +2 s, heading NE, longest stationary 2 500 ms.
        Assert.Equal(1, await Count(empty with { ZoneId = world.ZoneId }));
        Assert.Equal(1, await Count(empty with { ZoneId = world.ZoneId, ZoneRelation = TrackZoneRelation.Entered }));
        Assert.Equal(1, await Count(empty with { ZoneId = world.ZoneId, ZoneRelation = TrackZoneRelation.Exited }));
        Assert.Equal(1, await Count(empty with { ZoneId = world.ZoneId, MinDwellMs = 4_000 }));
        Assert.Equal(0, await Count(empty with { ZoneId = world.ZoneId, MinDwellMs = 4_001 }));
        Assert.Equal(1, await Count(empty with { Loitering = true }));
        Assert.Equal(1, await Count(empty with { ZoneId = world.ZoneId, Loitering = true }));
        Assert.Equal(1, await Count(empty with { LineId = world.LineId }));
        Assert.Equal(1, await Count(empty with { LineId = world.LineId, CrossingDirection = TrackCrossingDirection.AToB }));
        Assert.Equal(0, await Count(empty with { LineId = world.LineId, CrossingDirection = TrackCrossingDirection.BToA }));
        Assert.Equal(1, await Count(empty with { MotionDirection = "NE" }));
        Assert.Equal(0, await Count(empty with { MotionDirection = "S" }));
        Assert.Equal(1, await Count(empty with { MinStationaryMs = 2_500 }));
        Assert.Equal(0, await Count(empty with { MinStationaryMs = 2_501 }));
        // AND across families.
        Assert.Equal(1, await Count(empty with { ZoneId = world.ZoneId, LineId = world.LineId, MotionDirection = "NE", MinStationaryMs = 1_000 }));
        Assert.Equal(0, await Count(empty with { ZoneId = world.ZoneId, MotionDirection = "S" }));
        // Identity alone evaluates every Track of the covered runs.
        Assert.Equal(1, await Count(empty with { SceneRevisionId = world.RevisionId }));
    }

    [Fact]
    public async Task ItemExplanationsAreBoundedToWhatMatched()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var repository = Repository(world);

        var page = (await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with
            {
                ZoneId = world.ZoneId,
                LineId = world.LineId,
                CrossingDirection = TrackCrossingDirection.AToB,
                MotionDirection = "NE",
            }), null, 51, default)).Page!;

        var explained = page.ItemAnalytics[world.TrackId];
        Assert.Equal(world.RevisionId, explained.SceneRevisionId);
        var zone = Assert.Single(explained.Zones);
        Assert.Equal((world.ZoneId, 1, 4_000L, true), (zone.ZoneId, zone.VisitCount, zone.TotalDwellMs, zone.Loitering));
        var line = Assert.Single(explained.Lines);
        Assert.Equal((world.LineId, 1, "AToB", world.RunCompletedAtUtc.AddSeconds(2)), (line.LineId, line.CrossingCount, line.MatchedDirection, line.FirstMatchedCrossingUtc));
        Assert.Equal(("NE", 2_500L), (explained.Motion!.Heading, explained.Motion.LongestStationaryMs));

        // Nothing asked about motion: nothing said about it.
        var zoneOnly = (await repository.SearchAnalyticsAsync(
            Query(world, TrackAnalyticsQuery.Empty with { ZoneId = world.ZoneId }), null, 51, default)).Page!;
        Assert.Null(zoneOnly.ItemAnalytics[world.TrackId].Motion);
        Assert.Empty(zoneOnly.ItemAnalytics[world.TrackId].Lines);
    }

    // --- Detail -------------------------------------------------------------

    [Fact]
    public async Task DetailReturnsTheFullFactsForTheResolvedIdentity()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var repository = Repository(world);

        var result = await repository.GetDetailAnalyticsAsync(world.TrackId, TrackAnalyticsDetailRequest.Current, default);

        var analytics = result!.Analytics!;
        Assert.Equal("Analysed", analytics.Status);
        Assert.Equal(world.RevisionId, analytics.SceneRevisionId);
        Assert.Equal(1, analytics.SceneRevisionNumber);
        Assert.Equal(TrackAnalysisOutcomeKind.Analysed, analytics.Outcome!.Outcome);
        Assert.Single(analytics.ZoneSummaries);
        Assert.Single(analytics.ZoneVisits);
        Assert.Single(analytics.LineCrossings);
        Assert.Equal("NE", analytics.MotionSummary!.Heading);
        Assert.Empty(analytics.OtherIdentities);
    }

    [Fact]
    public async Task DetailNeverSubstitutesTheActiveRevisionForAnExplicitOne()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var newRevision = await world.ActivateNewRevisionAsync(Now.AddMinutes(1));
        var repository = Repository(world);

        var current = (await repository.GetDetailAnalyticsAsync(world.TrackId, TrackAnalyticsDetailRequest.Current, default))!.Analytics!;
        Assert.Equal(newRevision, current.SceneRevisionId);
        Assert.Equal("Stale", current.Status);
        var other = Assert.Single(current.OtherIdentities);
        Assert.Equal((world.RevisionId, 1, TrackAnalysisOutcomeKind.Analysed), (other.SceneRevisionId, other.SceneRevisionNumber, other.Outcome));

        var historical = (await repository.GetDetailAnalyticsAsync(
            world.TrackId, new TrackAnalyticsDetailRequest(world.RevisionId, null), default))!.Analytics!;
        Assert.Equal("Analysed", historical.Status);
        Assert.Equal(world.RevisionId, historical.SceneRevisionId);

        var foreign = await repository.GetDetailAnalyticsAsync(
            world.TrackId, new TrackAnalyticsDetailRequest(Guid.CreateVersion7(), null), default);
        Assert.False(foreign!.IsValid);

        Assert.Null(await repository.GetDetailAnalyticsAsync(Guid.CreateVersion7(), TrackAnalyticsDetailRequest.Current, default));
    }

    // --- Helpers ------------------------------------------------------------

    private TrackSearchRepository Repository(SceneAnalyticsWorld world) =>
        new(fixture.CreateDbContext(), world.Clock);

    private static Task<int> QueueAsync(SceneAnalysisLifecycle lifecycle) =>
        lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            null,
            Now.AddDays(-1),
            50,
            default);

    private static async Task<Guid> CommitFactsAsync(SceneAnalyticsWorld world)
    {
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var result = await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);
        Assert.True(result.IsSuccess);
        return claim.AnalysisId;
    }
}
