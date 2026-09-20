import { ApiError } from '../../api/client';

/**
 * Operator-facing messages for the failure codes the scene API returns.
 *
 * Every code here is one the backend actually defines; none is invented. The
 * raw problem stays on the `ApiError` for diagnostics, and nothing from an
 * exception or a filesystem path is ever shown.
 */
const messages: Record<string, string> = {
  scene_zone_vertex_count: 'A zone needs between 3 and 64 vertices.',
  scene_zone_vertex_range: 'Every zone vertex must sit inside the frame.',
  scene_zone_self_intersecting: 'A zone boundary may not cross itself.',
  scene_zone_degenerate: 'A zone must enclose an area and may not repeat a vertex.',
  scene_zone_name_required: 'Every zone needs a name.',
  scene_zone_name_too_long: 'A zone name must not exceed 64 characters.',
  scene_zone_name_duplicate: 'Two zones share a name. Zone names must be unique within a revision.',
  scene_zone_kind_invalid: 'That zone kind is not one the platform recognises.',
  scene_zone_loitering_threshold_invalid: 'A loitering threshold must be between 1 and 86400 seconds.',
  scene_line_range: 'Every trip line endpoint must sit inside the frame.',
  scene_line_endpoints_identical: 'A trip line needs two clearly separated endpoints.',
  scene_line_name_required: 'Every trip line needs a name.',
  scene_line_name_too_long: 'A trip line name must not exceed 64 characters.',
  scene_line_name_duplicate: 'Two trip lines share a name. Trip line names must be unique within a revision.',
  scene_line_label_too_long: 'A direction label must not exceed 32 characters.',
  scene_geometry_count: 'A revision may carry at most 64 zones and 64 trip lines.',
  scene_geometry_missing: 'One of the submitted zones or trip lines was empty.',
  scene_identity_unknown: 'This scene changed since editing started, so one of its objects is no longer recognised. Reload the active revision.',
  scene_identity_duplicate: 'The same zone or trip line was submitted twice.',
  scene_note_too_long: 'A revision note must not exceed 500 characters.',
  scene_revision_invalid: 'The revision could not be created from this request.',
  scene_revision_conflict: 'This scene changed since you started editing.',
  scene_revision_not_found: 'That revision does not exist for this camera.',
  scene_reference_frame_incomplete: 'A reference frame needs both a video and an offset, or neither.',
  scene_reference_frame_camera_mismatch: 'The reference video belongs to another camera.',
  scene_reference_frame_offset_invalid: 'The reference frame offset falls outside that video.',
  scene_reference_frame_not_found: 'The reference video was not found.',
  scene_camera_inactive: 'This camera is not active, so its scene cannot be changed.',
  scene_configuration_mismatch: 'The scene configuration did not match this camera.',
  camera_not_found: 'Camera was not found.',
};

/** The message for a failure, falling back to the server's own detail. */
export function sceneErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  return messages[error.code] ?? `${error.detail} (${error.code})`;
}

/** True when a save failed because someone else saved first. */
export function isRevisionConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

/** True when the camera itself is missing, which is a page-level condition. */
export function isCameraMissing(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404 && error.code === 'camera_not_found';
}
