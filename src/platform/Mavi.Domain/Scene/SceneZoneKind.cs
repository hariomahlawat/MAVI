namespace Mavi.Domain.Scene;

/// <summary>The operational meaning an operator assigns to a zone.</summary>
/// <remarks>Persisted as its name so that adding a member never renumbers stored rows.</remarks>
public enum SceneZoneKind
{
    General,
    Restricted,
    Entrance,
    Exit,
}
