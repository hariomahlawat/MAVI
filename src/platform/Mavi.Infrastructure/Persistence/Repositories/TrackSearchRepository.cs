using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed partial class TrackSearchRepository(
    MaviDbContext db,
    TimeProvider timeProvider) : ITrackSearchRepository
{
    public async Task<TrackSearchRepositoryPage> SearchAsync(
        TrackSearchQuery query,
        TrackCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken)
    {
        if (cursor is not null)
        {
            var continuationRows = await BuildQuery(
                    query,
                    cursor.SnapshotVisibilitySequence,
                    cursor)
                .Take(take)
                .ToArrayAsync(cancellationToken);
            return new TrackSearchRepositoryPage(
                continuationRows,
                cursor.SnapshotUtc,
                cursor.SnapshotVisibilitySequence);
        }

        await using var transaction =
            await db.Database.BeginTransactionAsync(cancellationToken);

        // Concurrent readers share the visibility barrier. While this transaction
        // holds the shared lock, completion cannot acquire the exclusive counterpart
        // and therefore cannot allocate a completion sequence. Allocating the
        // snapshot sequence from PostgreSQL gives pagination a monotonic,
        // clock-independent commit boundary.
        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(
            db,
            cancellationToken);
        var snapshotVisibilitySequence =
            await ProcessingVisibilityBarrier.AllocateSequenceAsync(
                db,
                cancellationToken);
        var snapshotUtc = timeProvider.GetUtcNow().ToUniversalTime();

        var rows = await BuildQuery(
                query,
                snapshotVisibilitySequence,
                cursor: null)
            .Take(take)
            .ToArrayAsync(cancellationToken);

        await transaction.CommitAsync(cancellationToken);
        return new TrackSearchRepositoryPage(
            rows,
            snapshotUtc,
            snapshotVisibilitySequence);
    }

    public Task<TrackDetailRow?> GetDetailAsync(
        Guid trackId,
        CancellationToken cancellationToken) =>
        (
            from track in db.Tracks.AsNoTracking()
            join run in db.ProcessingRuns.AsNoTracking() on track.ProcessingRunId equals run.Id
            join video in db.VideoAssets.AsNoTracking() on track.VideoAssetId equals video.Id
            join camera in db.Cameras.AsNoTracking() on video.CameraId equals camera.Id
            join observation in db.Observations.AsNoTracking()
                on track.RepresentativeObservationId equals observation.Id into observations
            from observation in observations.DefaultIfEmpty()
            where track.Id == trackId &&
                  run.Status == ProcessingRunStatus.Completed &&
                  run.CompletedAtUtc != null
            select new TrackDetailRow(
                track.Id,
                track.ProcessingRunId,
                track.VideoAssetId,
                camera.Id,
                camera.Code,
                camera.Name,
                track.ObjectClass,
                track.LocalTrackNumber,
                track.StartOffsetMs,
                track.EndOffsetMs,
                track.StartTimestampUtc,
                track.EndTimestampUtc,
                track.DurationMs,
                track.DetectionCount,
                track.MeanConfidence,
                track.MaxConfidence,
                track.ReviewStatus,
                run.PipelineVersion,
                run.DetectorName,
                run.DetectorVersion,
                run.TrackerName,
                run.TrackerVersion,
                run.CompletedAtUtc!.Value,
                video.RecordingStartUtc,
                video.RecordingEndUtc,
                video.DurationMs,
                video.Width,
                video.Height,
                video.FrameRateNumerator,
                video.FrameRateDenominator,
                observation == null ? null : observation.Id,
                observation == null ? null : observation.SourceFrameNumber,
                observation == null ? null : observation.VideoOffsetMs,
                observation == null ? null : observation.TimestampUtc,
                observation == null ? null : observation.Confidence,
                observation == null ? null : observation.QualityScore,
                observation == null ? null : observation.BoundingBoxX,
                observation == null ? null : observation.BoundingBoxY,
                observation == null ? null : observation.BoundingBoxWidth,
                observation == null ? null : observation.BoundingBoxHeight,
                observation == null ? null : observation.ThumbnailArtifactId,
                track.TrajectoryArtifactId))
        .SingleOrDefaultAsync(cancellationToken);

    private IQueryable<TrackSearchRow> BuildQuery(
        TrackSearchQuery query,
        long snapshotVisibilitySequence,
        TrackCursorPosition? cursor)
    {
        var tracks = BaseCandidates(query, snapshotVisibilitySequence);

        if (cursor is not null)
        {
            var timestamp = cursor.StartTimestampUtc;
            var trackId = cursor.TrackId;
            tracks = tracks.Where(x =>
                x.track.StartTimestampUtc < timestamp ||
                (x.track.StartTimestampUtc == timestamp &&
                 x.track.Id.CompareTo(trackId) < 0));
        }

        return tracks
            .OrderByDescending(x => x.track.StartTimestampUtc)
            .ThenByDescending(x => x.track.Id)
            .Select(x => new TrackSearchRow(
                x.track.Id,
                x.track.ProcessingRunId,
                x.track.VideoAssetId,
                x.camera.Id,
                x.camera.Code,
                x.camera.Name,
                x.track.ObjectClass,
                x.track.StartTimestampUtc,
                x.track.EndTimestampUtc,
                x.track.StartOffsetMs,
                x.track.EndOffsetMs,
                x.track.DurationMs,
                x.track.DetectionCount,
                x.track.MeanConfidence,
                x.track.MaxConfidence,
                x.track.ReviewStatus,
                x.observation == null ? null : x.observation.ThumbnailArtifactId));
    }

    /// <summary>
    /// The non-analytic base candidate set: every existing Track filter and the latest-run
    /// scope, before any analytic predicate, keyset or ordering. Ordinary search orders and
    /// pages it directly; analytic search takes its coverage denominator from it (plan §H)
    /// and then narrows it.
    /// </summary>
    private IQueryable<TrackCandidate> BaseCandidates(
        TrackSearchQuery query,
        long snapshotVisibilitySequence)
    {
        var tracks =
            from track in db.Tracks.AsNoTracking()
            join run in db.ProcessingRuns.AsNoTracking() on track.ProcessingRunId equals run.Id
            join video in db.VideoAssets.AsNoTracking() on track.VideoAssetId equals video.Id
            join camera in db.Cameras.AsNoTracking() on video.CameraId equals camera.Id
            join observation in db.Observations.AsNoTracking()
                on track.RepresentativeObservationId equals observation.Id into observations
            from observation in observations.DefaultIfEmpty()
            where run.Status == ProcessingRunStatus.Completed &&
                  run.CompletedAtUtc != null &&
                  run.VisibilitySequence != null &&
                  run.VisibilitySequence <= snapshotVisibilitySequence
            select new TrackCandidate { track = track, run = run, video = video, camera = camera, observation = observation };

        if (query.ProcessingRunId is { } runId)
        {
            tracks = tracks.Where(x => x.run.Id == runId);
        }
        else
        {
            tracks = tracks.Where(x =>
                !db.ProcessingRuns.AsNoTracking().Any(other =>
                    other.VideoAssetId == x.video.Id &&
                    other.Status == ProcessingRunStatus.Completed &&
                    other.CompletedAtUtc != null &&
                    other.VisibilitySequence != null &&
                    other.VisibilitySequence <= snapshotVisibilitySequence &&
                    other.VisibilitySequence > x.run.VisibilitySequence));
        }

        if (query.CameraId is { } cameraId)
            tracks = tracks.Where(x => x.camera.Id == cameraId);
        if (query.VideoAssetId is { } videoId)
            tracks = tracks.Where(x => x.video.Id == videoId);
        if (query.ObjectClass is { } objectClass)
            tracks = tracks.Where(x => x.track.ObjectClass == objectClass);
        if (query.FromUtc is { } fromUtc)
            tracks = tracks.Where(x => x.track.EndTimestampUtc >= fromUtc);
        if (query.ToUtc is { } toUtc)
            tracks = tracks.Where(x => x.track.StartTimestampUtc < toUtc);
        if (query.MinimumDurationMs is { } minimumDurationMs)
            tracks = tracks.Where(x => x.track.DurationMs >= minimumDurationMs);
        if (query.MinimumConfidence is { } minimumConfidence)
            tracks = tracks.Where(x => x.track.MeanConfidence >= minimumConfidence);

        return tracks;
    }

    /// <summary>
    /// One candidate row of the base chain, named so both search paths can share it.
    /// Member-initialised rather than constructed: EF Core inlines an object initialiser
    /// into later correlated subqueries the way it does an anonymous type, and does not
    /// do the same for a constructor call.
    /// </summary>
#pragma warning disable IDE1006 // Lower-case members keep the query text identical to the anonymous type it replaces.
    private sealed class TrackCandidate
    {
        public required Domain.Intelligence.Track track { get; init; }
        public required ProcessingRun run { get; init; }
        public required Domain.Media.VideoAsset video { get; init; }
        public required Domain.Cameras.Camera camera { get; init; }
        public Domain.Intelligence.Observation? observation { get; init; }
    }
#pragma warning restore IDE1006
}
