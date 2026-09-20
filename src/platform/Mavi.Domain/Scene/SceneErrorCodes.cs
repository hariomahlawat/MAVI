namespace Mavi.Domain.Scene;

/// <summary>
/// Stable failure codes for scene configuration, surfaced unchanged as the
/// <c>code</c> member of an RFC 7807 problem response.
/// </summary>
public static class SceneErrorCodes
{
    // Zones
    public const string ZoneVertexCount = "scene_zone_vertex_count";
    public const string ZoneVertexRange = "scene_zone_vertex_range";
    public const string ZoneSelfIntersecting = "scene_zone_self_intersecting";
    public const string ZoneDegenerate = "scene_zone_degenerate";
    public const string ZoneNameRequired = "scene_zone_name_required";
    public const string ZoneNameTooLong = "scene_zone_name_too_long";
    public const string ZoneNameDuplicate = "scene_zone_name_duplicate";
    public const string ZoneKindInvalid = "scene_zone_kind_invalid";
    public const string ZoneLoiteringThresholdInvalid = "scene_zone_loitering_threshold_invalid";

    // Trip lines
    public const string LineRange = "scene_line_range";
    public const string LineEndpointsIdentical = "scene_line_endpoints_identical";
    public const string LineNameRequired = "scene_line_name_required";
    public const string LineNameTooLong = "scene_line_name_too_long";
    public const string LineNameDuplicate = "scene_line_name_duplicate";
    public const string LineLabelTooLong = "scene_line_label_too_long";

    // Revision
    public const string GeometryCount = "scene_geometry_count";
    public const string IdentityUnknown = "scene_identity_unknown";
    public const string IdentityDuplicate = "scene_identity_duplicate";
    public const string NoteTooLong = "scene_note_too_long";
    public const string RevisionInvalid = "scene_revision_invalid";
    public const string RevisionConflict = "scene_revision_conflict";
    public const string RevisionNotFound = "scene_revision_not_found";
    public const string ReferenceFrameIncomplete = "scene_reference_frame_incomplete";
    public const string ReferenceFrameCameraMismatch = "scene_reference_frame_camera_mismatch";
    public const string ReferenceFrameOffsetInvalid = "scene_reference_frame_offset_invalid";
    public const string ReferenceFrameNotFound = "scene_reference_frame_not_found";

    // Configuration
    public const string CameraInactive = "scene_camera_inactive";
    public const string ConfigurationMismatch = "scene_configuration_mismatch";
}
