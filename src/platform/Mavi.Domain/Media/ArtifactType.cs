namespace Mavi.Domain.Media;

public enum ArtifactType
{
    SourceVideo,
    /// <summary>A completion 2.0 Representative crop. Historical rows keep this type.</summary>
    Thumbnail,
    TrackTrajectory,
    /// <summary>A completion 3.0 Evidence Set crop of any role.</summary>
    EvidenceCrop,
    /// <summary>One sealed <c>AttributePredictions</c> document per completed Visual Attribute analysis (ADR-013 §13).</summary>
    AttributePredictions,
}
