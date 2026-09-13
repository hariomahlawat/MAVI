using Mavi.Application.Modules.Evidence;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class ContentCatalog(MaviDbContext db) : IContentCatalog
{
    public Task<ContentDescriptor?> GetVideoContentAsync(
        Guid videoAssetId,
        CancellationToken cancellationToken) =>
        (
            from video in db.VideoAssets.AsNoTracking()
            join artifact in db.Artifacts.AsNoTracking()
                on video.SourceArtifactId equals artifact.Id
            where video.Id == videoAssetId &&
                  artifact.ArtifactType == ArtifactType.SourceVideo
            select new ContentDescriptor(
                artifact.Id,
                artifact.ArtifactType,
                artifact.StorageKey,
                artifact.MimeType,
                artifact.SizeBytes,
                artifact.Sha256,
                ContentStorageKind.ManagedMedia))
        .SingleOrDefaultAsync(cancellationToken);

    public Task<ContentDescriptor?> GetEvidenceContentAsync(
        Guid artifactId,
        CancellationToken cancellationToken)
    {
        var thumbnails =
            from artifact in db.Artifacts.AsNoTracking()
            join observation in db.Observations.AsNoTracking()
                on artifact.Id equals observation.ThumbnailArtifactId
            join track in db.Tracks.AsNoTracking()
                on observation.TrackId equals track.Id
            join run in db.ProcessingRuns.AsNoTracking()
                on track.ProcessingRunId equals run.Id
            where artifact.Id == artifactId &&
                  artifact.ArtifactType == ArtifactType.Thumbnail &&
                  run.Status == ProcessingRunStatus.Completed &&
                  run.CompletedAtUtc != null
            select new ContentDescriptor(
                artifact.Id,
                artifact.ArtifactType,
                artifact.StorageKey,
                artifact.MimeType,
                artifact.SizeBytes,
                artifact.Sha256,
                ContentStorageKind.AcceptedEvidence);

        var trajectories =
            from artifact in db.Artifacts.AsNoTracking()
            join track in db.Tracks.AsNoTracking()
                on artifact.Id equals track.TrajectoryArtifactId
            join run in db.ProcessingRuns.AsNoTracking()
                on track.ProcessingRunId equals run.Id
            where artifact.Id == artifactId &&
                  artifact.ArtifactType == ArtifactType.TrackTrajectory &&
                  run.Status == ProcessingRunStatus.Completed &&
                  run.CompletedAtUtc != null
            select new ContentDescriptor(
                artifact.Id,
                artifact.ArtifactType,
                artifact.StorageKey,
                artifact.MimeType,
                artifact.SizeBytes,
                artifact.Sha256,
                ContentStorageKind.AcceptedEvidence);

        return thumbnails.Concat(trajectories)
            .Distinct()
            .SingleOrDefaultAsync(cancellationToken);
    }
}
