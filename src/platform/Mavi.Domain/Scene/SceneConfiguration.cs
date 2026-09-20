using Mavi.Domain.Common;

namespace Mavi.Domain.Scene;

/// <summary>
/// A camera's scene configuration: the anchor that names which of its immutable
/// revisions is currently active. Exactly one exists per camera, created on first save.
/// </summary>
public sealed class SceneConfiguration
{
    private SceneConfiguration() { }

    public static SceneConfiguration Create(Guid cameraId, DateTimeOffset createdAtUtc)
    {
        if (cameraId == Guid.Empty)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ConfigurationMismatch,
                "A scene configuration requires a camera.");
        }

        var now = createdAtUtc.ToUniversalTime();
        return new SceneConfiguration
        {
            Id = Guid.CreateVersion7(),
            CameraId = cameraId,
            ActiveRevisionId = null,
            CreatedAtUtc = now,
            UpdatedAtUtc = now,
        };
    }

    public Guid Id { get; private set; }

    /// <summary>Immutable once set: a configuration never moves to another camera.</summary>
    public Guid CameraId { get; private set; }

    public Guid? ActiveRevisionId { get; private set; }

    public DateTimeOffset CreatedAtUtc { get; private set; }

    public DateTimeOffset UpdatedAtUtc { get; private set; }

    /// <summary>
    /// Creates the next revision from the submitted geometry and activates it in the
    /// same step. The previously active revision is left untouched and stays readable.
    /// </summary>
    /// <param name="activeRevision">The currently active revision, or null on first save.</param>
    /// <param name="draft">The whole geometry the operator is saving.</param>
    /// <param name="expectedRevisionNumber">
    /// The revision number the editor was working from; 0 or null means "no
    /// configuration yet". A mismatch is a conflict, never a merge.
    /// </param>
    /// <param name="createdBy">Server-controlled actor.</param>
    /// <param name="now">Current time, supplied by the caller's clock.</param>
    /// <exception cref="SceneRevisionConflictException">Another save landed first.</exception>
    public SceneConfigurationRevision SaveRevision(
        SceneConfigurationRevision? activeRevision,
        SceneRevisionDraft draft,
        int? expectedRevisionNumber,
        string createdBy,
        DateTimeOffset now)
    {
        if (activeRevision is not null && activeRevision.SceneConfigurationId != Id)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ConfigurationMismatch,
                "The active revision does not belong to this scene configuration.");
        }

        if (activeRevision is not null && ActiveRevisionId != activeRevision.Id)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ConfigurationMismatch,
                "The supplied revision is not the active revision of this configuration.");
        }

        var currentNumber = activeRevision?.RevisionNumber ?? 0;
        var expected = expectedRevisionNumber ?? 0;
        if (expected != currentNumber)
        {
            throw new SceneRevisionConflictException(expected, currentNumber);
        }

        var revision = SceneConfigurationRevision.Create(
            Id,
            currentNumber + 1,
            createdBy,
            draft,
            SceneIdentitySet.FromRevision(activeRevision),
            now);

        ActiveRevisionId = revision.Id;
        UpdatedAtUtc = now.ToUniversalTime();
        return revision;
    }
}
