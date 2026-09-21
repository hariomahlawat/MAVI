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

    /// <summary>
    /// Commits the new revision and the activation as one publication.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Activation is a publication event, not an ordinary write: it changes which
    /// revision an analytic search without an explicit revision pins its identity to,
    /// and which revision coverage calls "current" when it decides whether a missing
    /// analysis unit is Pending or Stale. So it takes the exclusive
    /// processing-visibility barrier before writing and holds it through commit, exactly
    /// as a processing run's completion does. A first-page search holds the shared
    /// counterpart across its whole scope resolution, so it sees this activation either
    /// wholly or not at all.
    /// </para>
    /// <para>
    /// Without this the search side could only pretend to be safe: a lock one party
    /// never takes orders nothing.
    /// </para>
    /// </remarks>
    public async Task SaveChangesAsync(CancellationToken cancellationToken)
    {
        // An ambient transaction means a caller already owns the boundary; take the
        // barrier inside it rather than starting a second one.
        if (dbContext.Database.CurrentTransaction is not null)
        {
            await ProcessingVisibilityBarrier.AcquireSceneActivationExclusiveAsync(dbContext, cancellationToken);
            await SaveAsync(cancellationToken);
            return;
        }

        await using var transaction = await dbContext.Database.BeginTransactionAsync(cancellationToken);
        await ProcessingVisibilityBarrier.AcquireSceneActivationExclusiveAsync(dbContext, cancellationToken);
        await SaveAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
    }

    private async Task SaveAsync(CancellationToken cancellationToken)
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
