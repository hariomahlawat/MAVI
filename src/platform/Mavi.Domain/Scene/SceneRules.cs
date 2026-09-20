namespace Mavi.Domain.Scene;

/// <summary>Transport-independent bounds and vocabularies of the scene model.</summary>
/// <remarks>
/// These mirror <c>Mavi.Contracts.Api.Scene.SceneContractRules</c> by value. Domain
/// carries no project reference, so the two are kept in step by a test rather than
/// by a shared constant.
/// </remarks>
public static class SceneRules
{
    /// <summary>
    /// The actor recorded for a scene mutation until operator identity exists.
    /// Never supplied by a caller.
    /// </summary>
    public const string UnattributedDevelopmentActor = "development-unattributed";

    public const int MinimumZoneVertices = 3;
    public const int MaximumZoneVertices = 64;
    public const int MaximumZonesPerRevision = 64;
    public const int MaximumTripLinesPerRevision = 64;
    public const int MaximumNameLength = 64;
    public const int MaximumDirectionLabelLength = 32;
    public const int MaximumNoteLength = 500;
    public const int MaximumCreatedByLength = 64;

    /// <summary>Endpoints closer than this are the same point for operator purposes.</summary>
    public const double MinimumLineEndpointSeparation = 0.005;

    /// <summary>Largest loitering threshold an operator may set on a zone, in seconds.</summary>
    public const int MaximumLoiteringThresholdSeconds = 86_400;

    /// <summary>
    /// Names are compared without regard to case so that "Gate" and "gate" collide,
    /// while the operator's own capitalisation is stored unchanged.
    /// </summary>
    public static readonly StringComparer NameComparer = StringComparer.OrdinalIgnoreCase;
}
