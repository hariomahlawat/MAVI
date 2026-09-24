using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

/// <summary>
/// The analytic search path of the service: what it hands the repository, what it pins
/// into the v3 cursor, and when it refuses (plan §S, ADR-011 decision 6).
/// </summary>
public sealed class TrackSearchServiceAnalyticsTests
{
    private static readonly DateTimeOffset FixedNow = new(2026, 9, 21, 11, 0, 0, TimeSpan.Zero);
    private static readonly TimeProvider FixedClock = new FixedTimeProvider(FixedNow);
    private static readonly TrackCursorSigningKey Key =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(0, 32).Select(x => (byte)x).ToArray());
    private static readonly TrackCursorSigningKey OtherKey =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(50, 32).Select(x => (byte)x).ToArray());

    private static readonly Guid Camera = Guid.Parse("0199a1f0-0000-7000-8000-00000000c001");
    private static readonly Guid Revision = Guid.Parse("0199a1f0-0000-7000-8000-00000000b001");
    private static readonly Guid Zone = Guid.Parse("0199a1f0-0000-7000-8000-00000000d001");

    private static readonly TrackAnalyticsPinnedIdentity Identity = new(Camera, Revision, "scene-analytics-v1");
    private static readonly TrackAnalyticsCoverage Partial = new(Revision, "scene-analytics-v1", 2, 1, 0, 0, 0, 0, 9, 1);
    private static readonly TrackAnalyticsCoverage Complete = new(Revision, "scene-analytics-v1", 3, 0, 0, 0, 0, 0, 12, 0);

    private static TrackSearchQuery Query(int limit = 50) => new(
        Camera, null, null, ObjectClass.Person, null, null, null, null, null, limit,
        TrackAnalyticsQuery.Empty with { ZoneId = Zone });

    [Fact]
    public async Task FirstPageFingerprintsTheResolvedIdentityIntoAV3Cursor()
    {
        var rows = new[] { Row(FixedNow.AddMinutes(-1)), Row(FixedNow.AddMinutes(-2)), Row(FixedNow.AddMinutes(-3)) };
        var repository = new FakeAnalyticsRepository(rows, Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);

        var result = await service.SearchAsync(Query(limit: 2), CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Null(repository.LastCursor);
        Assert.Equal(3, repository.LastTake);
        Assert.Equal(2, result.Page!.Items.Count);
        Assert.Equal(Partial, result.Page.Coverage);
        Assert.NotNull(result.Page.ItemAnalytics);

        Assert.NotNull(result.Page.NextCursor);
        Assert.False(TrackCursorCodec.TryDecode(result.Page.NextCursor, out _), "an analytic search never issues a v2 cursor");
        Assert.True(TrackCursorCodec.TryDecodeAnalytic(result.Page.NextCursor, Key, out var cursor));
        Assert.Equal(Identity, cursor!.Identity);
        Assert.Equal(Partial, cursor.Coverage);
        Assert.Equal(rows[1].Id, cursor.Position.TrackId);
        Assert.Equal(101, cursor.Position.SnapshotVisibilitySequence);
        Assert.Equal(
            TrackCursorCodec.ComputeAnalyticFilterFingerprint(Query(limit: 2), Identity),
            cursor.Position.FilterFingerprint);
    }

    [Fact]
    public async Task ContinuationPassesThePinnedIdentityAndKeepsItsCoverage()
    {
        var repository = new FakeAnalyticsRepository([Row(FixedNow.AddMinutes(-5))], Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);
        var pinned = Cursor(Query(), Identity, Partial);

        var result = await service.SearchAsync(
            Query() with { Cursor = TrackCursorCodec.EncodeAnalytic(pinned, Key) },
            CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(pinned, repository.LastCursor);
        Assert.Equal(Partial, result.Page!.Coverage);
    }

    [Fact]
    public async Task ACursorIsRefusedWhenTheFiltersChanged()
    {
        var repository = new FakeAnalyticsRepository([], Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);
        var pinned = Cursor(Query(), Identity, Partial);
        var changed = Query() with { Analytics = Query().Analytics! with { MinDwellMs = 5_000 } };

        var result = await service.SearchAsync(
            changed with { Cursor = TrackCursorCodec.EncodeAnalytic(pinned, Key) },
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal("track_search_invalid", result.ErrorCode);
        Assert.Equal(0, repository.Calls);
    }

    [Fact]
    public async Task ACursorMintedUnderAnotherKeyIsRefusedBeforeTheRepository()
    {
        var repository = new FakeAnalyticsRepository([], Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);
        var foreign = TrackCursorCodec.EncodeAnalytic(Cursor(Query(), Identity, Partial), OtherKey);

        var result = await service.SearchAsync(Query() with { Cursor = foreign }, CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(0, repository.Calls);
    }

    [Fact]
    public async Task AnOrdinaryCursorIsNotAcceptedByAnAnalyticSearch()
    {
        var repository = new FakeAnalyticsRepository([], Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);
        var ordinary = TrackCursorCodec.Encode(new TrackCursorPosition(
            FixedNow, 101, FixedNow.AddMinutes(-1), Guid.CreateVersion7(),
            TrackCursorCodec.ComputeFilterFingerprint(Query())));

        var result = await service.SearchAsync(Query() with { Cursor = ordinary }, CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(0, repository.Calls);
    }

    [Theory]
    [InlineData(-61)]
    [InlineData(2)]
    public async Task AnAnalyticCursorHasTheSameOneHourLife(int minutesFromNow)
    {
        var repository = new FakeAnalyticsRepository([], Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);
        var pinned = Cursor(Query(), Identity, Partial, snapshotUtc: FixedNow.AddMinutes(minutesFromNow));

        var result = await service.SearchAsync(
            Query() with { Cursor = TrackCursorCodec.EncodeAnalytic(pinned, Key) },
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(0, repository.Calls);
    }

    [Fact]
    public async Task ARepositoryRefusalIsAnInvalidSearch()
    {
        var repository = new FakeAnalyticsRepository([], Identity, Partial) { Refuse = true };
        var service = new TrackSearchService(repository, FixedClock, Key);

        var result = await service.SearchAsync(Query(), CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal("track_search_invalid", result.ErrorCode);
    }

    [Fact]
    public async Task DemandingCompleteCoverageOverIncompleteScopeIsAStructuredConflict()
    {
        var repository = new FakeAnalyticsRepository([Row(FixedNow)], Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);
        var demanding = Query() with { Analytics = Query().Analytics! with { RequireCompleteCoverage = true } };

        var result = await service.SearchAsync(demanding, CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal("track_analytics_incomplete", result.ErrorCode);
        Assert.Equal(Partial, result.Coverage);
        Assert.Null(result.Page);
    }

    [Fact]
    public async Task DemandingCompleteCoverageOverCompleteScopeSucceeds()
    {
        var repository = new FakeAnalyticsRepository([Row(FixedNow)], Identity, Complete);
        var service = new TrackSearchService(repository, FixedClock, Key);
        var demanding = Query() with { Analytics = Query().Analytics! with { RequireCompleteCoverage = true } };

        var result = await service.SearchAsync(demanding, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.True(result.Page!.Coverage!.Complete);
    }

    [Fact]
    public async Task AnInvalidDependencyNeverReachesTheRepository()
    {
        var repository = new FakeAnalyticsRepository([], Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);
        var broken = Query() with { Analytics = TrackAnalyticsQuery.Empty with { CrossingDirection = TrackCrossingDirection.AToB } };

        var result = await service.SearchAsync(broken, CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(0, repository.Calls);
    }

    [Fact]
    public async Task DetailRefusesAnEngineVersionWithoutItsRevision()
    {
        var repository = new FakeAnalyticsRepository([], Identity, Partial);
        var service = new TrackSearchService(repository, FixedClock, Key);

        var result = await service.GetDetailAsync(
            Guid.CreateVersion7(),
            new TrackAnalyticsDetailRequest(null, "scene-analytics-v1"),
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal("track_search_invalid", result.ErrorCode);
    }

    private static TrackAnalyticsCursorPosition Cursor(
        TrackSearchQuery query,
        TrackAnalyticsPinnedIdentity identity,
        TrackAnalyticsCoverage coverage,
        DateTimeOffset? snapshotUtc = null) =>
        new(
            new TrackCursorPosition(
                snapshotUtc ?? FixedNow,
                101,
                FixedNow.AddMinutes(-1),
                Guid.CreateVersion7(),
                TrackCursorCodec.ComputeAnalyticFilterFingerprint(query, identity)),
            identity,
            coverage);

    private static TrackSearchRow Row(DateTimeOffset timestamp) => new(
        Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7(), Camera,
        "CAM-01", "Gate", ObjectClass.Person, timestamp, timestamp.AddSeconds(1),
        0, 1000, 1000, 5, 0.8, 0.9, ReviewStatus.Unreviewed, null);

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }

    private sealed class FakeAnalyticsRepository(
        IReadOnlyList<TrackSearchRow> rows,
        TrackAnalyticsPinnedIdentity identity,
        TrackAnalyticsCoverage coverage) : ITrackSearchRepository
    {
        public int Calls { get; private set; }
        public int LastTake { get; private set; }
        public TrackAnalyticsCursorPosition? LastCursor { get; private set; }
        public bool Refuse { get; init; }

        public Task<TrackSearchRepositoryPage> SearchAsync(
            TrackSearchQuery query, TrackCursorPosition? cursor, int take, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("An analytic query must not take the ordinary path.");

        public Task<TrackAnalyticsSearchRepositoryResult> SearchAnalyticsAsync(
            TrackSearchQuery query, TrackAnalyticsCursorPosition? cursor, int take, CancellationToken cancellationToken)
        {
            Calls++;
            LastTake = take;
            LastCursor = cursor;
            if (Refuse)
                return Task.FromResult(TrackAnalyticsSearchRepositoryResult.Invalid);
            var explained = rows.ToDictionary(
                row => row.Id,
                _ => new TrackItemAnalytics(identity.SceneRevisionId!.Value, identity.AlgorithmVersion, [], [], null));
            return Task.FromResult(new TrackAnalyticsSearchRepositoryResult(new TrackAnalyticsSearchRepositoryPage(
                rows, cursor?.Position.SnapshotUtc ?? FixedNow, cursor?.Position.SnapshotVisibilitySequence ?? 101,
                cursor?.Identity ?? identity, cursor?.Coverage ?? coverage, explained)));
        }

        public Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");

        public Task<IReadOnlyList<TrackEvidenceObservationRow>> GetEvidenceSetAsync(
            Guid trackId, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");

        public Task<TrackDetailAnalyticsResult?> GetDetailAnalyticsAsync(
            Guid trackId, TrackAnalyticsDetailRequest request, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");
    }
}
