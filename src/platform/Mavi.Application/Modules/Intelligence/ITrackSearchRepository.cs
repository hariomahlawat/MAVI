namespace Mavi.Application.Modules.Intelligence;

public sealed record TrackCursorPosition(
    DateTimeOffset SnapshotUtc,
    DateTimeOffset StartTimestampUtc,
    Guid TrackId);

public interface ITrackSearchRepository
{
    Task<IReadOnlyList<TrackSearchRow>> SearchAsync(
        TrackSearchQuery query,
        DateTimeOffset snapshotUtc,
        TrackCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken);

    Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken);
}
