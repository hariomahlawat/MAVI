using System.Text.Json.Serialization;

namespace Mavi.Contracts.Api.Scene;

// Per-camera scene geometry, versioned as immutable whole-configuration
// revisions (ADR-011). Coordinates are normalised to the source video frame:
// origin top-left, x right, y down, both in [0, 1]. Geometry validation
// (self-intersection, degeneracy, name collisions) is domain behaviour and is
// deliberately absent from this transport contract.

public sealed record ScenePointResponse(double X, double Y);

public sealed record SceneZoneResponse(
    Guid ZoneId,
    string Name,
    string Kind,
    bool Enabled,
    IReadOnlyList<ScenePointResponse> Vertices,
    int? LoiteringThresholdSeconds);

public sealed record SceneTripLineResponse(
    Guid LineId,
    string Name,
    bool Enabled,
    ScenePointResponse A,
    ScenePointResponse B,
    bool Directed,
    string AToBLabel,
    string BToALabel);

/// <summary>One immutable revision of a camera's scene configuration.</summary>
/// <remarks>
/// <paramref name="CreatedBy"/> is server-controlled; see
/// <see cref="SceneContractRules.UnattributedDevelopmentActor"/>.
/// </remarks>
public sealed record SceneRevisionResponse(
    Guid RevisionId,
    int RevisionNumber,
    Guid CameraId,
    DateTimeOffset CreatedAtUtc,
    string CreatedBy,
    string? Note,
    Guid? ReferenceFrameVideoAssetId,
    long? ReferenceFrameOffsetMs,
    IReadOnlyList<SceneZoneResponse> Zones,
    IReadOnlyList<SceneTripLineResponse> TripLines)
{
    /// <summary>
    /// False exactly when the revision carries no enabled zone and no enabled
    /// trip line: an empty active revision is how analytics are intentionally
    /// disabled for a camera (ADR-011). Computed from the geometry it describes,
    /// so it cannot contradict it.
    /// </summary>
    public bool AnalyticsEnabled =>
        Zones.Any(zone => zone.Enabled) || TripLines.Any(line => line.Enabled);
}

public sealed record SceneRevisionSummaryResponse(
    Guid RevisionId,
    int RevisionNumber,
    DateTimeOffset CreatedAtUtc,
    string CreatedBy,
    string? Note,
    bool AnalyticsEnabled,
    int ZoneCount,
    int TripLineCount);

/// <summary>A camera's current scene configuration and its revision history.</summary>
/// <remarks>
/// <paramref name="Configured"/> is false when the camera has never had a
/// revision; that is distinct from an active revision that disables analytics,
/// which is reported by <see cref="SceneRevisionResponse.AnalyticsEnabled"/>.
/// </remarks>
public sealed record CameraSceneResponse(
    Guid CameraId,
    bool Configured,
    SceneRevisionResponse? ActiveRevision,
    IReadOnlyList<SceneRevisionSummaryResponse> History);

// Requests reject unknown members so that a caller cannot smuggle a field the
// server owns. In particular there is deliberately no way to supply an actor,
// author or display name: scene mutations are recorded as unattributed
// Development actions until operator identity exists (ADR-011, ADR-010).

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record SaveSceneRequest(
    int? ExpectedRevisionNumber,
    string? Note,
    Guid? ReferenceFrameVideoAssetId,
    long? ReferenceFrameOffsetMs,
    IReadOnlyList<SaveSceneZoneRequest>? Zones,
    IReadOnlyList<SaveSceneTripLineRequest>? TripLines);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record SaveSceneZoneRequest(
    Guid? ZoneId,
    string? Name,
    string? Kind,
    bool? Enabled,
    IReadOnlyList<ScenePointRequest>? Vertices,
    int? LoiteringThresholdSeconds);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record SaveSceneTripLineRequest(
    Guid? LineId,
    string? Name,
    bool? Enabled,
    ScenePointRequest? A,
    ScenePointRequest? B,
    bool? Directed,
    string? AToBLabel,
    string? BToALabel);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record ScenePointRequest(double? X, double? Y);
