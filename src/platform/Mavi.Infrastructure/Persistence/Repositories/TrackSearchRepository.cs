using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class TrackSearchRepository(MaviDbContext db) : ITrackSearchRepository
{
    public async Task<IReadOnlyList<TrackSearchRow>> SearchAsync(
        TrackSearchQuery query,
        DateTimeOffset snapshotUtc,
        TrackCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken)
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
                  run.CompletedAtUtc <= snapshotUtc
            select new { track, run, video, camera, observation };

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
                    other.CompletedAtUtc <= snapshotUtc &&
                    (other.CompletedAtUtc > x.run.CompletedAtUtc ||
                     (other.CompletedAtUtc == x.run.CompletedAtUtc && other.Id.CompareTo(x.run.Id) > 0))));
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

        if (cursor is not null)
        {
            var timestamp = cursor.StartTimestampUtc;
            var trackId = cursor.TrackId;
            tracks = tracks.Where(x =>
                x.track.StartTimestampUtc < timestamp ||
                (x.track.StartTimestampUtc == timestamp && x.track.Id.CompareTo(trackId) < 0));
        }

        return await tracks
            .OrderByDescending(x => x.track.StartTimestampUtc)
            .ThenByDescending(x => x.track.Id)
            .Take(take)
            .Select(x => new TrackSearchRow(
                x.track.Id,
                x.track.ProcessingRunId,
                x.track.VideoAssetId,
                x.camera.Id,
                x.camera.Code,
                x.camera.Name,
                x.track.ObjectClass.ToString(),
                x.track.StartTimestampUtc,
                x.track.EndTimestampUtc,
                x.track.StartOffsetMs,
                x.track.EndOffsetMs,
                x.track.DurationMs,
                x.track.DetectionCount,
                x.track.MeanConfidence,
                x.track.MaxConfidence,
                x.track.ReviewStatus.ToString(),
                x.observation == null ? null : x.observation.ThumbnailArtifactId))
            .ToArrayAsync(cancellationToken);
    }

    public Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken) =>
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
                track.ObjectClass.ToString(),
                track.LocalTrackNumber,
                track.StartOffsetMs,
                track.EndOffsetMs,
                track.StartTimestampUtc,
                track.EndTimestampUtc,
                track.DurationMs,
                track.DetectionCount,
                track.MeanConfidence,
                track.MaxConfidence,
                track.ReviewStatus.ToString(),
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
}
