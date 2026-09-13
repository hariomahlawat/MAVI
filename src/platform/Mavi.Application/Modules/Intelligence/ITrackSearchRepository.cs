namespace Mavi.Application.Modules.Intelligence;

public sealed record TrackCursorPosition(
    DateTimeOffset SnapshotUtc,
    DateTimeOffset StartTimestampUtc,
    Guid TrackId,
    string FilterFingerprint);

public sealed record TrackSearchRepositoryPage(
    IReadOnlyList<TrackSearchRow> Items,
    DateTimeOffset SnapshotUtc);

public interface ITrackSearchRepository
{
    Task<TrackSearchRepositoryPage> SearchAsync(
        TrackSearchQuery query,
        TrackCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken);

    Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken);
}
