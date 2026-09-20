using Mavi.Domain.Scene;

namespace Mavi.Application.Modules.SceneAnalytics.Configuration;

/// <summary>Storage port for a camera's scene configuration and its revisions.</summary>
public interface ISceneConfigurationRepository
{
    Task<SceneConfiguration?> GetByCameraAsync(Guid cameraId, CancellationToken cancellationToken);

    /// <summary>Loads one revision with its zones and trip lines.</summary>
    Task<SceneConfigurationRevision?> GetRevisionAsync(Guid revisionId, CancellationToken cancellationToken);

    Task<SceneConfigurationRevision?> GetRevisionByNumberAsync(
        Guid sceneConfigurationId,
        int revisionNumber,
        CancellationToken cancellationToken);

    /// <summary>Every revision of a configuration, oldest first, with its geometry.</summary>
    Task<IReadOnlyList<SceneConfigurationRevision>> ListRevisionsAsync(
        Guid sceneConfigurationId,
        CancellationToken cancellationToken);

    Task AddAsync(SceneConfiguration configuration, CancellationToken cancellationToken);

    Task AddRevisionAsync(SceneConfigurationRevision revision, CancellationToken cancellationToken);

    /// <summary>
    /// Commits the new revision and the activation together.
    /// </summary>
    /// <exception cref="SceneConcurrentSaveException">
    /// Another save for the same camera committed first.
    /// </exception>
    Task SaveChangesAsync(CancellationToken cancellationToken);
}

/// <summary>
/// Raised when the database refuses a save because a competing save for the same
/// camera got there first.
/// </summary>
/// <remarks>
/// The read-then-write conflict check cannot see a transaction that commits between
/// the two, so the uniqueness constraints are the last word; this turns their
/// violation into the same conflict the caller would have seen a moment earlier.
/// </remarks>
public sealed class SceneConcurrentSaveException(Exception innerException)
    : Exception("The scene was saved by another request.", innerException);
