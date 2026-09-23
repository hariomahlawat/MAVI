using Mavi.Application.Modules.Evidence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class ContentCatalog(MaviDbContext db) : IContentCatalog
{
    public async Task<VideoContentLookup> GetVideoContentAsync(
        Guid videoAssetId,
        CancellationToken cancellationToken)
    {
        var row = await (
            from video in db.VideoAssets.AsNoTracking()
            where video.Id == videoAssetId
            join artifact in db.Artifacts.AsNoTracking()
                on video.SourceArtifactId equals artifact.Id into sourceArtifacts
            from artifact in sourceArtifacts.DefaultIfEmpty()
            select new
            {
                ArtifactId = artifact == null ? (Guid?)null : artifact.Id,
                ArtifactType = artifact == null ? (ArtifactType?)null : artifact.ArtifactType,
                StorageKey = artifact == null ? null : artifact.StorageKey,
                MimeType = artifact == null ? null : artifact.MimeType,
                SizeBytes = artifact == null ? (long?)null : artifact.SizeBytes,
                Sha256 = artifact == null ? null : artifact.Sha256,
            })
            .SingleOrDefaultAsync(cancellationToken);

        if (row is null)
            return new VideoContentLookup(false, null);

        if (row.ArtifactId is null ||
            row.ArtifactType != ArtifactType.SourceVideo ||
            row.StorageKey is null ||
            row.MimeType is null ||
            row.SizeBytes is null ||
            row.Sha256 is null)
        {
            return new VideoContentLookup(true, null);
        }

        return new VideoContentLookup(
            true,
            new ContentDescriptor(
                row.ArtifactId.Value,
                row.ArtifactType.Value,
                row.StorageKey,
                row.MimeType,
                row.SizeBytes.Value,
                row.Sha256,
                ContentStorageKind.ManagedMedia));
    }

    public Task<ContentDescriptor?> GetEvidenceContentAsync(
        Guid artifactId,
        CancellationToken cancellationToken) =>
        db.Artifacts
            .AsNoTracking()
            .Where(artifact =>
                artifact.Id == artifactId &&
                (
                    (
                        // A crop (v2 Thumbnail or v3 EvidenceCrop) is served only while an
                        // Observation of a Completed run references it.
                        (artifact.ArtifactType == ArtifactType.Thumbnail ||
                         artifact.ArtifactType == ArtifactType.EvidenceCrop) &&
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
