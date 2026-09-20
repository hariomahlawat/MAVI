namespace Mavi.Contracts.Api.Scene;

/// <summary>
/// The closed vocabularies and transport-level bounds of the scene-configuration
/// contract (ADR-011).
/// </summary>
/// <remarks>
/// These are wire-shape facts only. Geometric validity — self-intersection,
/// degeneracy, duplicate names, crossing and dwell semantics — is domain
/// behaviour and is intentionally not expressed here.
/// </remarks>
public static class SceneContractRules
{
    /// <summary>
    /// The server-controlled actor recorded for Development scene mutations.
    /// No request may supply an actor: attribution is not trustworthy until
    /// operator identity exists (ADR-011, and ADR-010 when written), and this
    /// constant says so rather than inventing a plausible name.
    /// </summary>
    public const string UnattributedDevelopmentActor = "development-unattributed";

    /// <summary>Operational meaning an operator may assign to a zone.</summary>
    public static readonly IReadOnlyList<string> ZoneKindValues =
        ["General", "Restricted", "Entrance", "Exit"];

    public const string DefaultZoneKind = "General";

    /// <summary>
    /// Normalised coordinates are relative to the source video frame: origin
    /// top-left, x right, y down, both in [0, 1], carried at fixed precision so
    /// equality and hashing are stable across hosts.
    /// </summary>
    public const int CoordinateDecimals = 6;

    public const int MinimumZoneVertices = 3;
    public const int MaximumZoneVertices = 64;
    public const int MaximumZonesPerRevision = 64;
    public const int MaximumTripLinesPerRevision = 64;
    public const int MaximumNameLength = 64;
    public const int MaximumDirectionLabelLength = 32;
    public const int MaximumNoteLength = 500;

    public static bool IsZoneKind(string? value)
    {
        if (value is null)
        {
            return false;
        }

        for (var index = 0; index < ZoneKindValues.Count; index++)
        {
            if (string.Equals(ZoneKindValues[index], value, StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>A coordinate component that can be carried on the wire at all.</summary>
    public static bool IsNormalizedCoordinate(double value) =>
        double.IsFinite(value) && value is >= 0 and <= 1;
}
