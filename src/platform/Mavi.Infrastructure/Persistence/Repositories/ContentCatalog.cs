using Mavi.Application.Modules.Evidence;
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
        CancellationToken cancellationToken) =>
        db.Artifacts
            .AsNoTracking()
            .Where(artifact =>
                artifact.Id == artifactId &&
                (
                    (
                        artifact.ArtifactType == ArtifactType.Thumbnail &&
                        db.Observations.AsNoTracking().Any(observation =>
                            observation.ThumbnailArtifactId == artifact.Id &&
                            db.Tracks.AsNoTracking().Any(track =>
                                track.Id == observation.TrackId &&
                                db.ProcessingRuns.AsNoTracking().Any(run =>
                                    run.Id == track.ProcessingRunId &&
                                    run.Status == ProcessingRunStatus.Completed &&
                                    run.CompletedAtUtc != null)))
                    ) ||
                    (
                        artifact.ArtifactType == ArtifactType.TrackTrajectory &&
                        db.Tracks.AsNoTracking().Any(track =>
                            track.TrajectoryArtifactId == artifact.Id &&
                            db.ProcessingRuns.AsNoTracking().Any(run =>
                                run.Id == track.ProcessingRunId &&
                                run.Status == ProcessingRunStatus.Completed &&
                                run.CompletedAtUtc != null))
                    )
                ))
            .Select(artifact => new ContentDescriptor(
                artifact.Id,
                artifact.ArtifactType,
                artifact.StorageKey,
                artifact.MimeType,
                artifact.SizeBytes,
                artifact.Sha256,
                ContentStorageKind.AcceptedEvidence))
            .SingleOrDefaultAsync(cancellationToken);
}
