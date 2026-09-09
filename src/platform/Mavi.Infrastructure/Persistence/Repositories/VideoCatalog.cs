using Mavi.Application.Modules.Media;
using Mavi.Domain.Media;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class VideoCatalog(MaviDbContext dbContext) : IVideoCatalog
{
    // Queries
    public Task<VideoAsset?> GetAsync(Guid id, CancellationToken cancellationToken) =>
        dbContext.VideoAssets.AsNoTracking().SingleOrDefaultAsync(video => video.Id == id, cancellationToken);

    public async Task<IReadOnlyList<VideoAsset>> ListAsync(CancellationToken cancellationToken) =>
        await dbContext.VideoAssets.AsNoTracking()
            .OrderByDescending(video => video.RecordingStartUtc).ThenBy(video => video.Id)
            .ToArrayAsync(cancellationToken);

    public Task<VideoAsset?> FindSourceVideoBySha256Async(string sha256, CancellationToken cancellationToken) =>
        (from video in dbContext.VideoAssets.AsNoTracking()
         join artifact in dbContext.Artifacts.AsNoTracking() on video.SourceArtifactId equals artifact.Id
         where artifact.ArtifactType == ArtifactType.SourceVideo && artifact.Sha256 == sha256
         select video).SingleOrDefaultAsync(cancellationToken);

    // Atomic persistence
    public async Task AddAsync(Artifact artifact, VideoAsset video, CancellationToken cancellationToken)
    {
        await dbContext.Artifacts.AddAsync(artifact, cancellationToken);
        await dbContext.VideoAssets.AddAsync(video, cancellationToken);
    }

    public async Task SaveChangesAsync(CancellationToken cancellationToken)
    {
        try
        {
            await dbContext.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateException exception) when (exception.InnerException is PostgresException
        {
            SqlState: PostgresErrorCodes.UniqueViolation,
            ConstraintName: "ux_artifacts_source_video_sha256",
        })
        {
            throw new DuplicateSourceVideoException(exception);
        }
    }
}
