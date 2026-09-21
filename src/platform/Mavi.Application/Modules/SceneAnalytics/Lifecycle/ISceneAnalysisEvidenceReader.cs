using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.SceneAnalytics.Lifecycle;

/// <summary>
/// One Track of a run, as far as analytics is concerned: what it is, when its media
/// started, and where its sealed trajectory lives.
/// </summary>
/// <remarks>
/// <see cref="TrajectoryStorageKey"/> is null when the worker produced no trajectory for
/// the Track. That is a fact about the evidence, not an error: the Track still gets an
/// outcome row saying its trajectory is missing.
/// </remarks>
public sealed record SceneAnalysisTrackEvidence(
    Guid TrackId,
    ObjectClass ObjectClass,
    DateTimeOffset RecordingStartUtc,
    string? TrajectoryStorageKey,
    string? TrajectorySha256);

/// <summary>Reads the sealed evidence one analysis unit is derived from.</summary>
public interface ISceneAnalysisEvidenceReader
{
    /// <summary>
    /// Every Track of a run, in a stable order, so that two executions of the same unit
    /// process the same Tracks in the same sequence.
    /// </summary>
    Task<IReadOnlyList<SceneAnalysisTrackEvidence>> ListRunTracksAsync(
        Guid processingRunId,
        CancellationToken cancellationToken);

    /// <summary>Reads a sealed trajectory artefact whole.</summary>
    /// <remarks>
    /// Returns null when the artefact is not there. Any other failure is an I/O fault and
    /// is raised, because it says nothing about the evidence and everything about the
    /// host: the attempt should be retried rather than the Track written off.
    /// </remarks>
    Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken);
}
