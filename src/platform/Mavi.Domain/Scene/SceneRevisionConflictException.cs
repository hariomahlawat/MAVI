namespace Mavi.Domain.Scene;

/// <summary>
/// Raised when a save is based on a revision that is no longer the active one.
/// </summary>
/// <remarks>
/// Distinct from <see cref="Mavi.Domain.Common.DomainValidationException"/> because the
/// request is well formed: another operator simply got there first, which is a conflict
/// rather than a validation failure. The submitted geometry is never merged into theirs.
/// </remarks>
public sealed class SceneRevisionConflictException(int expectedRevisionNumber, int actualRevisionNumber)
    : Exception(
        $"The scene was last saved as revision {actualRevisionNumber}, not {expectedRevisionNumber}.")
{
    public static string Code => SceneErrorCodes.RevisionConflict;

    public int ExpectedRevisionNumber { get; } = expectedRevisionNumber;

    public int ActualRevisionNumber { get; } = actualRevisionNumber;
}
