using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

public sealed class TrackSearchServiceTests
{
    private static readonly DateTimeOffset FixedNow =
        new(2026, 9, 13, 11, 0, 0, TimeSpan.Zero);
    private static readonly TimeProvider FixedClock = new FixedTimeProvider(FixedNow);
    [Fact]
    public async Task InvalidLimitIsRejectedBeforeRepositoryCall()
    {
        var repository = new FakeTrackSearchRepository([]);
        var service = new TrackSearchService(repository, FixedClock);
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
        var service = new TrackSearchService(repository, FixedClock);

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
        var service = new TrackSearchService(repository, FixedClock);
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
        var service = new TrackSearchService(repository, FixedClock);

        var result = await service.SearchAsync(
            ValidQuery() with { Limit = 2 },
            CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(3, repository.LastTake);
        Assert.Equal(2, result.Page!.Items.Count);
        Assert.NotNull(result.Page.NextCursor);
        Assert.True(TrackCursorCodec.TryDecode(result.Page.NextCursor, out var position));
        Assert.Equal(FixedNow, position!.SnapshotUtc);
        Assert.Equal(rows[1].Id, position.TrackId);
        Assert.Equal(rows[1].StartTimestampUtc, position.StartTimestampUtc);
    }

    [Fact]
    public async Task ValidCursorIsPassedAsSeekPosition()
    {
        var expected = new TrackCursorPosition(
            FixedNow,
            new DateTimeOffset(2026, 9, 13, 10, 0, 0, TimeSpan.Zero),
            Guid.CreateVersion7());
        var repository = new FakeTrackSearchRepository([]);
        var service = new TrackSearchService(repository, FixedClock);

        var result = await service.SearchAsync(
            ValidQuery() with { Cursor = TrackCursorCodec.Encode(expected) },
            CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(expected, repository.LastCursor);
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

        public Task<IReadOnlyList<TrackSearchRow>> SearchAsync(
            TrackSearchQuery query,
            DateTimeOffset snapshotUtc,
            TrackCursorPosition? cursor,
            int take,
            CancellationToken cancellationToken)
        {
            SearchCalls++;
            LastTake = take;
            LastSnapshotUtc = snapshotUtc;
            LastCursor = cursor;
            return Task.FromResult(rows);
        }

        public Task<TrackDetailRow?> GetDetailAsync(
            Guid trackId,
            CancellationToken cancellationToken) =>
            Task.FromResult<TrackDetailRow?>(null);
    }
}
