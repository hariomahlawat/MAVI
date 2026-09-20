using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.Media;
using Mavi.Domain.Common;
using Mavi.Domain.Scene;

namespace Mavi.Application.Modules.SceneAnalytics.Configuration;

/// <summary>What a camera's scene looks like right now, plus the revisions behind it.</summary>
public sealed record CameraSceneView(
    Guid CameraId,
    bool Configured,
    SceneConfigurationRevision? ActiveRevision,
    IReadOnlyList<SceneConfigurationRevision> History);

/// <summary>A request to save the whole scene and activate it.</summary>
public sealed record SaveSceneCommand(Guid CameraId, int? ExpectedRevisionNumber, SceneRevisionDraft Draft);

/// <summary>
/// The application boundary for scene configuration: reads a camera's scene, its
/// history and a single past revision, and saves the next one.
/// </summary>
/// <remarks>
/// The actor on a revision is server-controlled. A caller cannot supply one, because
/// there is nothing yet to verify it against; every mutation is recorded as
/// <see cref="SceneRules.UnattributedDevelopmentActor"/> until operator identity
/// exists.
/// </remarks>
public sealed class SceneConfigurationService(
    ISceneConfigurationRepository repository,
    ICameraRepository cameras,
    IVideoCatalog videos,
    TimeProvider timeProvider)
{
    // Queries
    public async Task<CameraSceneView?> GetAsync(Guid cameraId, CancellationToken cancellationToken)
    {
        if (await cameras.GetAsync(cameraId, cancellationToken) is null)
        {
            return null;
        }

        var configuration = await repository.GetByCameraAsync(cameraId, cancellationToken);
        if (configuration is null)
        {
            return new CameraSceneView(cameraId, Configured: false, ActiveRevision: null, History: []);
        }

        var history = await repository.ListRevisionsAsync(configuration.Id, cancellationToken);
        var active = configuration.ActiveRevisionId is { } activeId
            ? history.FirstOrDefault(revision => revision.Id == activeId)
            : null;

        return new CameraSceneView(cameraId, Configured: true, active, history);
    }

    /// <summary>One historical revision by its number, or null when it does not exist.</summary>
    public async Task<SceneConfigurationRevision?> GetRevisionAsync(
        Guid cameraId,
        int revisionNumber,
        CancellationToken cancellationToken)
    {
        var configuration = await repository.GetByCameraAsync(cameraId, cancellationToken);
        return configuration is null
            ? null
            : await repository.GetRevisionByNumberAsync(configuration.Id, revisionNumber, cancellationToken);
    }

    // Commands
    /// <summary>
    /// Creates the next revision from the submitted geometry and activates it.
    /// </summary>
    /// <returns>The activated revision, or null when the camera does not exist.</returns>
    /// <exception cref="DomainValidationException">The geometry or the request is invalid.</exception>
    /// <exception cref="SceneRevisionConflictException">The editor was working from an older revision.</exception>
    /// <exception cref="SceneConcurrentSaveException">A competing save committed first.</exception>
    public async Task<SceneConfigurationRevision?> SaveAsync(
        SaveSceneCommand command,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(command);

        var camera = await cameras.GetAsync(command.CameraId, cancellationToken);
        if (camera is null)
        {
            return null;
        }

        if (!camera.IsActive)
        {
            throw new DomainValidationException(
                SceneErrorCodes.CameraInactive,
                "The camera is not active, so its scene cannot be changed.");
        }

        await ValidateReferenceFrameAsync(camera.Id, command.Draft, cancellationToken);

        var now = timeProvider.GetUtcNow();
        var configuration = await repository.GetByCameraAsync(command.CameraId, cancellationToken);
        var isNew = configuration is null;
        configuration ??= SceneConfiguration.Create(command.CameraId, now);

        var activeRevision = configuration.ActiveRevisionId is { } activeId
            ? await repository.GetRevisionAsync(activeId, cancellationToken)
            : null;

        var revision = configuration.SaveRevision(
            activeRevision,
            command.Draft,
            command.ExpectedRevisionNumber,
            SceneRules.UnattributedDevelopmentActor,
            now);

        if (isNew)
        {
            await repository.AddAsync(configuration, cancellationToken);
        }

        await repository.AddRevisionAsync(revision, cancellationToken);
        await repository.SaveChangesAsync(cancellationToken);
        return revision;
    }

    /// <summary>
    /// Checks that a reference frame, if one was given, names a video of this camera
    /// at an instant that video actually contains.
    /// </summary>
    private async Task ValidateReferenceFrameAsync(
        Guid cameraId,
        SceneRevisionDraft draft,
        CancellationToken cancellationToken)
    {
        if (draft.ReferenceFrameVideoAssetId is not { } videoAssetId)
        {
            return;
        }

        var video = await videos.GetAsync(videoAssetId, cancellationToken);
        if (video is null)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ReferenceFrameNotFound,
                "The reference frame video was not found.");
        }

        if (video.CameraId != cameraId)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ReferenceFrameCameraMismatch,
                "The reference frame video belongs to another camera.");
        }

        // The offset is media-relative, so it must fall inside this video's duration.
        if (draft.ReferenceFrameOffsetMs is { } offsetMs && (offsetMs < 0 || offsetMs > video.DurationMs))
        {
            throw new DomainValidationException(
                SceneErrorCodes.ReferenceFrameOffsetInvalid,
                "The reference frame offset falls outside the video.");
        }
    }
}
