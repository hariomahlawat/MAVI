namespace Mavi.Application.Modules.Intelligence;

public sealed record TrackSearchServiceResult(
    bool IsSuccess,
    TrackSearchPage? Page,
    string? ErrorCode)
{
    public static TrackSearchServiceResult Success(TrackSearchPage page) => new(true, page, null);
    public static TrackSearchServiceResult Invalid() => new(false, null, "track_search_invalid");
}

public sealed class TrackSearchService(ITrackSearchRepository repository)
{
    public async Task<TrackSearchServiceResult> SearchAsync(
        TrackSearchQuery query,
        CancellationToken cancellationToken)
    {
        if (!IsValid(query))
            return TrackSearchServiceResult.Invalid();

        TrackCursorPosition? cursor = null;
        if (query.Cursor is not null && !TrackCursorCodec.TryDecode(query.Cursor, out cursor))
            return TrackSearchServiceResult.Invalid();

        var rows = await repository.SearchAsync(
            query,
            cursor,
            checked(query.Limit + 1),
            cancellationToken);

        var hasMore = rows.Count > query.Limit;
        var items = hasMore ? rows.Take(query.Limit).ToArray() : rows;
        var nextCursor = hasMore && items.Count > 0
            ? TrackCursorCodec.Encode(new TrackCursorPosition(items[^1].StartTimestampUtc, items[^1].Id))
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
