using Mavi.Domain.Scene.Geometry;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// One sample of a Track's path: where its reference point was, at a media-relative
/// offset into the source video.
/// </summary>
/// <remarks>
/// The reference point is the detection's bounding-box centre, which is what
/// trajectory format v1 persists. See <see cref="AnalysisReferencePoint"/>.
/// </remarks>
public readonly record struct TrajectorySample(long OffsetMs, NormalizedPoint Position);

/// <summary>The reference point a set of facts was derived from.</summary>
public static class AnalysisReferencePoint
{
    /// <summary>Trajectory v1: the centre of the detection's bounding box.</summary>
    public const string BoundingBoxCentre = "bbox-centre";
}

/// <summary>Why a Track could not be analysed.</summary>
public static class TrajectoryFailureReasons
{
    public const string Missing = "trajectory_missing";
    public const string IntegrityFailed = "trajectory_integrity_failed";
    public const string Invalid = "trajectory_invalid";
    public const string TooShort = "trajectory_too_short";
}

/// <summary>
/// Raised when a sealed trajectory artefact cannot be read as a valid v1 payload.
/// </summary>
/// <remarks>
/// <see cref="Reason"/> is one of <see cref="TrajectoryFailureReasons"/> and is the
/// value recorded against the Track; the message stays internal and never names a
/// filesystem path.
/// </remarks>
public sealed class TrajectoryFormatException(string reason, string message) : Exception(message)
{
    public string Reason { get; } = reason;
}
