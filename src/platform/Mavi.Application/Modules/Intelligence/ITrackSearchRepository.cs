namespace Mavi.Application.Modules.Intelligence;

public sealed record TrackCursorPosition(
    DateTimeOffset SnapshotUtc,
    long SnapshotVisibilitySequence,
    DateTimeOffset StartTimestampUtc,
    Guid TrackId,
    string FilterFingerprint);

public sealed record TrackSearchRepositoryPage(
    IReadOnlyList<TrackSearchRow> Items,
    DateTimeOffset SnapshotUtc,
    long SnapshotVisibilitySequence);

public interface ITrackSearchRepository
{
    Task<TrackSearchRepositoryPage> SearchAsync(
        TrackSearchQuery query,
        TrackCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken);

    Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken);
}
