using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Domain.Scene;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class SceneConfigurationRepository(MaviDbContext dbContext) : ISceneConfigurationRepository
{
    /// <summary>
    /// Constraints whose violation means a competing save for the same camera
    /// committed between this request's read and its write.
    /// </summary>
    private static readonly string[] ConcurrentSaveConstraints =
    [
        "ux_scene_configurations_camera",
        "ux_scene_revisions_configuration_number",
    ];

    // Queries
    public Task<SceneConfiguration?> GetByCameraAsync(Guid cameraId, CancellationToken cancellationToken) =>
        dbContext.SceneConfigurations
            .SingleOrDefaultAsync(configuration => configuration.CameraId == cameraId, cancellationToken);

    public Task<SceneConfigurationRevision?> GetRevisionAsync(Guid revisionId, CancellationToken cancellationToken) =>
        WithGeometry(dbContext.SceneConfigurationRevisions.AsNoTracking())
            .SingleOrDefaultAsync(revision => revision.Id == revisionId, cancellationToken);

    public Task<SceneConfigurationRevision?> GetRevisionByNumberAsync(
        Guid sceneConfigurationId,
        int revisionNumber,
        CancellationToken cancellationToken) =>
        WithGeometry(dbContext.SceneConfigurationRevisions.AsNoTracking())
            .SingleOrDefaultAsync(
                revision => revision.SceneConfigurationId == sceneConfigurationId &&
                    revision.RevisionNumber == revisionNumber,
                cancellationToken);

    public async Task<IReadOnlyList<SceneConfigurationRevision>> ListRevisionsAsync(
        Guid sceneConfigurationId,
        CancellationToken cancellationToken) =>
        await WithGeometry(dbContext.SceneConfigurationRevisions.AsNoTracking())
            .Where(revision => revision.SceneConfigurationId == sceneConfigurationId)
            .OrderBy(revision => revision.RevisionNumber)
            .ToArrayAsync(cancellationToken);

    // Commands
    public async Task AddAsync(SceneConfiguration configuration, CancellationToken cancellationToken) =>
        await dbContext.SceneConfigurations.AddAsync(configuration, cancellationToken);

    public async Task AddRevisionAsync(SceneConfigurationRevision revision, CancellationToken cancellationToken) =>
        await dbContext.SceneConfigurationRevisions.AddAsync(revision, cancellationToken);

    public async Task SaveChangesAsync(CancellationToken cancellationToken)
    {
        try
        {
            await dbContext.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateException exception) when (IsConcurrentSave(exception))
        {
            throw new SceneConcurrentSaveException(exception);
        }
    }

    /// <summary>
    /// Loads a revision together with its geometry as one query per collection, so a
    /// revision with many zones and lines does not multiply its own rows.
    /// </summary>
    private static IQueryable<SceneConfigurationRevision> WithGeometry(IQueryable<SceneConfigurationRevision> query) =>
        query.Include(revision => revision.Zones).Include(revision => revision.TripLines).AsSplitQuery();

    private static bool IsConcurrentSave(DbUpdateException exception) =>
        exception.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation } postgres &&
        Array.Exists(ConcurrentSaveConstraints, name =>
            string.Equals(name, postgres.ConstraintName, StringComparison.Ordinal));
}
