using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Intelligence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// The Slice-6 aggregate read side over a real database: one snapshot, coverage that
/// keeps empty and uncovered apart, historical fact-bearing units, and geometry that
/// only appears when the resolved revision enabled it (plan §13.2).
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class AnalyticsAggregateRepositoryTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    /// <summary>A window wide enough to contain the world's single Track and its facts.</summary>
    private static AnalyticsAggregateQuery Query(
        SceneAnalyticsWorld world,
        int bucketSeconds = 3600,
        ObjectClass? objectClass = null) =>
        new(world.CameraId, Now.AddHours(-2), Now.AddHours(1), bucketSeconds, objectClass);

    private AnalyticsAggregateRepository Repository() => new(fixture.CreateDbContext());

    // --- Identity and snapshot ---------------------------------------------

    [Fact]
    public async Task EveryResponseCarriesTheIdentityItWasResolvedAgainst()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);

        var result = await Repository().AggregateAsync(Query(world), default);

        Assert.True(result.IsSuccess);
        Assert.Equal(world.CameraId, result.Identity!.CameraId);
        Assert.Equal(world.RevisionId, result.Identity.SceneRevisionId);
        Assert.Equal(SceneAnalyticsWorld.AlgorithmVersion, result.Identity.AlgorithmVersion);
        // A real allocated sequence, not a placeholder.
        Assert.True(result.Identity.SnapshotVisibilitySequence > 0);
    }

    [Fact]
    public async Task TwoRequestsTakeDistinctMonotonicSnapshots()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);

        var first = await Repository().AggregateAsync(Query(world), default);
        var second = await Repository().AggregateAsync(Query(world), default);

        Assert.True(second.Identity!.SnapshotVisibilitySequence > first.Identity!.SnapshotVisibilitySequence);
    }

    [Fact]
    public async Task FactsPublishedAfterTheSnapshotAreNotInTheAnswer()
    {
        // The run itself is not visible yet, so its Tracks are not even candidates.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, runVisible: false);

        var result = await Repository().AggregateAsync(Query(world), default);

        Assert.True(result.IsSuccess);
        Assert.Empty(result.Facts!.ZoneVisits);
        // No run in scope at all: the genuinely-empty observation.
        Assert.Equal(0, result.Coverage!.EvaluatedRuns);
        Assert.True(result.Coverage.Complete);
    }

    // --- Coverage -----------------------------------------------------------

    [Fact]
    public async Task ACoveredScopeReportsCompleteCoverageAndItsFacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);

        var result = await Repository().AggregateAsync(Query(world), default);

        Assert.True(result.Coverage!.Complete);
        Assert.Equal(1, result.Coverage.EvaluatedRuns);
        Assert.Equal(1, result.Coverage.AnalysedTracks);
        Assert.Single(result.Facts!.ZoneVisits);
        Assert.Single(result.Facts.TrackIntervals);
    }

    [Fact]
    public async Task AnEmptyDenominatorAndAnUncoveredDenominatorAreDifferentStates()
    {
        // (a) Genuinely empty: a window with no Tracks at all. Complete, everything
        // zero, and no synthetic run invented to explain the emptiness.
        var empty = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(empty);
        var emptyResult = await Repository().AggregateAsync(
            new AnalyticsAggregateQuery(empty.CameraId, Now.AddDays(-5), Now.AddDays(-4), 3600, null),
            default);

        Assert.True(emptyResult.Coverage!.Complete);
        Assert.Equal(0, emptyResult.Coverage.EvaluatedRuns);
        Assert.Equal(0, emptyResult.Coverage.PendingRuns);
        Assert.Empty(emptyResult.Facts!.ZoneVisits);

        // (b) Uncovered: the run is in scope but was never analysed. Not complete,
        // and the denominator says so.
        var uncovered = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var uncoveredResult = await Repository().AggregateAsync(Query(uncovered), default);

        Assert.False(uncoveredResult.Coverage!.Complete);
        Assert.Equal(0, uncoveredResult.Coverage.EvaluatedRuns);
        Assert.Equal(1, uncoveredResult.Coverage.PendingRuns);
        Assert.Empty(uncoveredResult.Facts!.ZoneVisits);

        // Both have no facts. Only coverage tells them apart, which is exactly why
        // the UI is forbidden from rendering them the same way.
        Assert.Equal(emptyResult.Facts.ZoneVisits.Count, uncoveredResult.Facts.ZoneVisits.Count);
        Assert.NotEqual(emptyResult.Coverage.Complete, uncoveredResult.Coverage.Complete);
    }

    [Fact]
    public async Task ADisabledRevisionIsASwitchOffRatherThanAGap()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, analyticsEnabled: false);

        var result = await Repository().AggregateAsync(Query(world), default);

        Assert.Equal(1, result.Coverage!.DisabledRuns);
        Assert.Equal(0, result.Coverage.PendingRuns);
        Assert.False(result.Coverage.Complete);
        Assert.Empty(result.Facts!.Zones);
    }

    // --- Fact-bearing history ----------------------------------------------

    [Fact]
    public async Task SupersededFactsRemainReadableForTheirOwnIdentity()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var analysisId = await CommitFactsAsync(world);

        // Supersede the unit without changing the active revision, so the aggregate
        // still resolves this identity and must still read its facts. Currency is not
        // validity.
        await using (var db = fixture.CreateDbContext())
        {
            await db.SceneAnalyses
                .Where(unit => unit.Id == analysisId)
                .ExecuteUpdateAsync(set => set.SetProperty(
                    unit => unit.Status,
                    Mavi.Domain.SceneAnalytics.SceneAnalysisStatus.Superseded));
        }

        var result = await Repository().AggregateAsync(Query(world), default);

        Assert.Equal(1, result.Coverage!.EvaluatedRuns);
        Assert.True(result.Coverage.Complete);
        Assert.Single(result.Facts!.ZoneVisits);
    }

    // --- Geometry and filters ----------------------------------------------

    [Fact]
    public async Task OnlyGeometryEnabledInTheResolvedRevisionAppears()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);

        var result = await Repository().AggregateAsync(Query(world), default);

        // The world's revision enables one zone and one line.
        Assert.Equal(world.ZoneId, Assert.Single(result.Facts!.Zones).ZoneId);
        Assert.Equal(world.LineId, Assert.Single(result.Facts.Lines).LineId);
    }

    [Fact]
    public async Task TheClassFilterNarrowsTheDenominatorAndTheFacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);

        // The world's only Track is a Person.
        var person = await Repository().AggregateAsync(Query(world, objectClass: ObjectClass.Person), default);
        var vehicle = await Repository().AggregateAsync(Query(world, objectClass: ObjectClass.Vehicle), default);

        Assert.Single(person.Facts!.TrackIntervals);
        Assert.Equal(1, person.Coverage!.EvaluatedRuns);

        // No Vehicle Track means no run in the denominator either: an empty scope,
        // complete and honest, not an incomplete one.
        Assert.Empty(vehicle.Facts!.TrackIntervals);
        Assert.Equal(0, vehicle.Coverage!.EvaluatedRuns);
        Assert.True(vehicle.Coverage.Complete);
    }

    [Fact]
    public async Task AnUnknownCameraIsNotFound()
    {
        await SceneAnalyticsWorld.CreateAsync(fixture, Now);

        var result = await Repository().AggregateAsync(
            new AnalyticsAggregateQuery(Guid.CreateVersion7(), Now.AddHours(-1), Now, 3600, null),
            default);

        Assert.Equal(AnalyticsFailure.NotFound, result.Failure);
    }

    // --- Helpers ------------------------------------------------------------

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
