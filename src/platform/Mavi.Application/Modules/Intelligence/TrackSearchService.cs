namespace Mavi.Application.Modules.Intelligence;

public sealed record TrackSearchServiceResult(
    bool IsSuccess,
    TrackSearchPage? Page,
    string? ErrorCode)
{
    public static TrackSearchServiceResult Success(TrackSearchPage page) => new(true, page, null);
    public static TrackSearchServiceResult Invalid() => new(false, null, "track_search_invalid");
}

public sealed class TrackSearchService(
    ITrackSearchRepository repository,
    TimeProvider timeProvider)
{
    private static readonly TimeSpan MaximumCursorAge = TimeSpan.FromHours(1);
    private static readonly TimeSpan MaximumFutureSkew = TimeSpan.FromMinutes(1);
    public async Task<TrackSearchServiceResult> SearchAsync(
        TrackSearchQuery query,
        CancellationToken cancellationToken)
    {
        if (!IsValid(query))
            return TrackSearchServiceResult.Invalid();

        var nowUtc = timeProvider.GetUtcNow().ToUniversalTime();
        var filterFingerprint = TrackCursorCodec.ComputeFilterFingerprint(query);

        TrackCursorPosition? cursor = null;
        if (query.Cursor is not null)
        {
            if (!TrackCursorCodec.TryDecode(query.Cursor, out cursor) ||
                cursor is null ||
                !string.Equals(
                    cursor.FilterFingerprint,
                    filterFingerprint,
                    StringComparison.Ordinal) ||
                cursor.SnapshotUtc < nowUtc - MaximumCursorAge ||
                cursor.SnapshotUtc > nowUtc + MaximumFutureSkew)
            {
                return TrackSearchServiceResult.Invalid();
            }
        }

        var snapshotUtc = cursor?.SnapshotUtc ?? nowUtc;
        var rows = await repository.SearchAsync(
            query,
            snapshotUtc,
            cursor,
            checked(query.Limit + 1),
            cancellationToken);

        var hasMore = rows.Count > query.Limit;
        var items = hasMore ? rows.Take(query.Limit).ToArray() : rows;
        var nextCursor = hasMore && items.Count > 0
            ? TrackCursorCodec.Encode(new TrackCursorPosition(
                snapshotUtc,
                items[^1].StartTimestampUtc,
                items[^1].Id,
                filterFingerprint))
            : null;

        return TrackSearchServiceResult.Success(new TrackSearchPage(items, nextCursor));
    }

    public Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken) =>
        trackId == Guid.Empty
            ? Task.FromResult<TrackDetailRow?>(null)
            : repository.GetDetailAsync(trackId, cancellationToken);

    private static bool IsValid(TrackSearchQuery query)
    {
        if (query.Limit is < 1 or > 100 ||
            query.CameraId == Guid.Empty ||
            query.VideoAssetId == Guid.Empty ||
            query.ProcessingRunId == Guid.Empty ||
            query.MinimumDurationMs is < 0)
            return false;

        if (query.MinimumConfidence is { } confidence &&
            (!double.IsFinite(confidence) || confidence is < 0 or > 1))
            return false;

        if ((query.FromUtc is { } fromValue && fromValue.Offset != TimeSpan.Zero) ||
            (query.ToUtc is { } toValue && toValue.Offset != TimeSpan.Zero))
            return false;

        if (query.FromUtc is { } from &&
            query.ToUtc is { } to &&
            from >= to)
            return false;

        return true;
    }
}
