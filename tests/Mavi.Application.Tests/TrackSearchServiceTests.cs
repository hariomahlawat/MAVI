using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

public sealed class TrackSearchServiceTests
{
    private static readonly DateTimeOffset FixedNow =
        new(2026, 9, 13, 11, 0, 0, TimeSpan.Zero);
    private static readonly TimeProvider FixedClock = new FixedTimeProvider(FixedNow);
    private static readonly TrackCursorSigningKey SigningKey =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(0, 32).Select(x => (byte)x).ToArray());
    [Fact]
    public async Task InvalidLimitIsRejectedBeforeRepositoryCall()
    {
        var repository = new FakeTrackSearchRepository([]);
        var service = new TrackSearchService(repository, FixedClock, SigningKey);
        var query = ValidQuery() with { Limit = 101 };

        var result = await service.SearchAsync(query, CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal("track_search_invalid", result.ErrorCode);
        Assert.Equal(0, repository.SearchCalls);
    }

    [Fact]
    public async Task InvalidConfidenceIsRejected()
    {
        var repository = new FakeTrackSearchRepository([]);
        var service = new TrackSearchService(repository, FixedClock, SigningKey);

        var result = await service.SearchAsync(
            ValidQuery() with { MinimumConfidence = double.NaN },
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(0, repository.SearchCalls);
    }

    [Fact]
    public async Task FromMustPrecedeTo()
    {
        var repository = new FakeTrackSearchRepository([]);
        var service = new TrackSearchService(repository, FixedClock, SigningKey);
        var instant = new DateTimeOffset(2026, 9, 13, 10, 0, 0, TimeSpan.Zero);

        var result = await service.SearchAsync(
            ValidQuery() with { FromUtc = instant, ToUtc = instant },
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(0, repository.SearchCalls);
    }

    [Fact]
    public async Task RequestsLimitPlusOneAndProducesNextCursor()
    {
        var rows = new[]
        {
            Row(new DateTimeOffset(2026, 9, 13, 10, 0, 3, TimeSpan.Zero)),
            Row(new DateTimeOffset(2026, 9, 13, 10, 0, 2, TimeSpan.Zero)),
            Row(new DateTimeOffset(2026, 9, 13, 10, 0, 1, TimeSpan.Zero)),
        };
        var repository = new FakeTrackSearchRepository(rows);
        var service = new TrackSearchService(repository, FixedClock, SigningKey);

        var result = await service.SearchAsync(
            ValidQuery() with { Limit = 2 },
            CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(3, repository.LastTake);
        Assert.Equal(2, result.Page!.Items.Count);
        Assert.NotNull(result.Page.NextCursor);
        Assert.True(TrackCursorCodec.TryDecode(result.Page.NextCursor, out var position));
        Assert.Equal(FixedNow, position!.SnapshotUtc);
        Assert.Equal(101, position.SnapshotVisibilitySequence);
        Assert.Equal(rows[1].Id, position.TrackId);
        Assert.Equal(rows[1].StartTimestampUtc, position.StartTimestampUtc);
    }

    [Fact]
    public async Task ValidCursorIsPassedAsSeekPosition()
    {
        var query = ValidQuery();
        var expected = new TrackCursorPosition(
            FixedNow,
            101,
            new DateTimeOffset(2026, 9, 13, 10, 0, 0, TimeSpan.Zero),
            Guid.CreateVersion7(),
            TrackCursorCodec.ComputeFilterFingerprint(query));
        var repository = new FakeTrackSearchRepository([]);
        var service = new TrackSearchService(repository, FixedClock, SigningKey);

        var result = await service.SearchAsync(
            query with { Cursor = TrackCursorCodec.Encode(expected) },
            CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(expected, repository.LastCursor);
    }

    [Fact]
    public async Task CursorCannotBeReusedWithDifferentFilters()
    {
        var repository = new FakeTrackSearchRepository([]);
        var service = new TrackSearchService(repository, FixedClock, SigningKey);
        var original = ValidQuery();
        var cursor = new TrackCursorPosition(
            FixedNow,
            101,
            FixedNow.AddMinutes(-1),
            Guid.CreateVersion7(),
            TrackCursorCodec.ComputeFilterFingerprint(original));

        var result = await service.SearchAsync(
            original with
            {
                MinimumConfidence = 0.9,
                Cursor = TrackCursorCodec.Encode(cursor),
            },
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(0, repository.SearchCalls);
    }

    [Theory]
    [InlineData(-61)]
    [InlineData(2)]
    public async Task CursorOutsideValidityWindowIsRejected(int minutesFromNow)
    {
        var repository = new FakeTrackSearchRepository([]);
        var service = new TrackSearchService(repository, FixedClock, SigningKey);
        var query = ValidQuery();
        var cursor = new TrackCursorPosition(
            FixedNow.AddMinutes(minutesFromNow),
            101,
            FixedNow.AddMinutes(-1),
            Guid.CreateVersion7(),
            TrackCursorCodec.ComputeFilterFingerprint(query));

        var result = await service.SearchAsync(
            query with { Cursor = TrackCursorCodec.Encode(cursor) },
            CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(0, repository.SearchCalls);
    }

    private static TrackSearchQuery ValidQuery() => new(
        CameraId: null,
        VideoAssetId: null,
        ProcessingRunId: null,
        ObjectClass: ObjectClass.Person,
        FromUtc: null,
        ToUtc: null,
        MinimumDurationMs: null,
        MinimumConfidence: null,
        Cursor: null,
        Limit: 50);

    private static TrackSearchRow Row(DateTimeOffset timestamp) => new(
        Guid.CreateVersion7(),
        Guid.CreateVersion7(),
        Guid.CreateVersion7(),
        Guid.CreateVersion7(),
        "CAM-01",
        "Gate",
        ObjectClass.Person,
        timestamp,
        timestamp.AddSeconds(1),
        0,
        1000,
        1000,
        5,
        0.8,
        0.9,
        ReviewStatus.Unreviewed,
        Guid.CreateVersion7());

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }

    private sealed class FakeTrackSearchRepository(IReadOnlyList<TrackSearchRow> rows)
        : ITrackSearchRepository
    {
        public int SearchCalls { get; private set; }
        public int LastTake { get; private set; }
        public DateTimeOffset LastSnapshotUtc { get; private set; }
        public TrackCursorPosition? LastCursor { get; private set; }

        public Task<TrackSearchRepositoryPage> SearchAsync(
            TrackSearchQuery query,
            TrackCursorPosition? cursor,
            int take,
            CancellationToken cancellationToken)
        {
            SearchCalls++;
            LastTake = take;
            LastSnapshotUtc = cursor?.SnapshotUtc ?? FixedNow;
            LastCursor = cursor;
            return Task.FromResult(
                new TrackSearchRepositoryPage(rows, LastSnapshotUtc, 101));
        }

        public Task<TrackDetailRow?> GetDetailAsync(
            Guid trackId,
            CancellationToken cancellationToken) =>
            Task.FromResult<TrackDetailRow?>(null);

        public Task<IReadOnlyList<TrackEvidenceObservationRow>> GetEvidenceSetAsync(
            Guid trackId,
            CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<TrackEvidenceObservationRow>>([]);

        public Task<TrackAnalyticsSearchRepositoryResult> SearchAnalyticsAsync(
            TrackSearchQuery query,
            TrackAnalyticsCursorPosition? cursor,
            int take,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException("The ordinary fake does not serve analytic searches.");

        public Task<TrackDetailAnalyticsResult?> GetDetailAnalyticsAsync(
            Guid trackId,
            TrackAnalyticsDetailRequest request,
            CancellationToken cancellationToken) =>
            Task.FromResult<TrackDetailAnalyticsResult?>(null);
    }
}
