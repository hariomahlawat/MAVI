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
                track.RepresentativeObservationId,
                track.TrajectoryArtifactId))
        .SingleOrDefaultAsync(cancellationToken);

    public async Task<IReadOnlyList<TrackEvidenceObservationRow>> GetEvidenceSetAsync(
        Guid trackId,
        CancellationToken cancellationToken) =>
        await db.Observations
            .AsNoTracking()
            .Where(observation => observation.TrackId == trackId)
            .OrderBy(observation => observation.EvidenceRank)
            .ThenBy(observation => observation.Id)
            // One more than a full set, so an over-full set is seen and refused by the
            // read seam rather than silently truncated to look valid.
            .Take(TrackEvidenceSet.MaximumCount + 1)
            .Select(observation => new TrackEvidenceObservationRow(
                observation.Id,
                observation.ObservationType,
                observation.EvidenceRank,
                observation.SourceFrameNumber,
                observation.VideoOffsetMs,
                observation.TimestampUtc,
                observation.Confidence,
                observation.QualityScore,
                observation.SelectionScore,
                observation.BoundingBoxX,
                observation.BoundingBoxY,
                observation.BoundingBoxWidth,
                observation.BoundingBoxHeight,
                observation.ThumbnailArtifactId))
            .ToArrayAsync(cancellationToken);

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
    /// The non-analytic base candidate set, from the one shared implementation.
    /// </summary>
    /// <remarks>
    /// The chain itself lives in <see cref="AnalyticsScopeQuery"/> because the Slice-6
    /// aggregate and heatmap queries need exactly this denominator. Keeping one
    /// implementation is what stops an aggregate and an Investigation search disagreeing
    /// about the same camera and window.
    /// </remarks>
    private IQueryable<TrackCandidate> BaseCandidates(
        TrackSearchQuery query,
        long snapshotVisibilitySequence) =>
        AnalyticsScopeQuery.BaseCandidates(
            db,
            AnalyticsScopeRequest.From(query),
            snapshotVisibilitySequence);

}
