import { SCENE_LIMITS } from '../../api/scene';
import type { SceneDraft } from './sceneDraft';

/**
 * The problems the browser can see for itself.
 *
 * This is feedback, not authority: the backend decides degeneracy,
 * self-intersection, identity and concurrency, and its answer always wins.
 * What is checked here is only what is obvious without reimplementing the
 * geometry engine, so that an operator is told about an empty name before they
 * press Save rather than after.
 */

export type SceneIssue = {
  /** The local key of the object the issue belongs to, or null for the scene. */
  key: string | null;
  message: string;
};

export function validateDraft(draft: SceneDraft): SceneIssue[] {
  const issues: SceneIssue[] = [];
  const zoneNames = new Map<string, number>();
  const lineNames = new Map<string, number>();

  for (const zone of draft.zones) {
    const name = zone.name.trim();
    if (!name) issues.push({ key: zone.key, message: 'This zone needs a name.' });
    else if (name.length > SCENE_LIMITS.maximumNameLength) {
      issues.push({ key: zone.key, message: `A name must not exceed ${SCENE_LIMITS.maximumNameLength} characters.` });
    }
    zoneNames.set(name.toLowerCase(), (zoneNames.get(name.toLowerCase()) ?? 0) + 1);

    if (zone.vertices.length < SCENE_LIMITS.minimumZoneVertices) {
      issues.push({ key: zone.key, message: `A zone needs at least ${SCENE_LIMITS.minimumZoneVertices} vertices.` });
    }
    if (zone.vertices.length > SCENE_LIMITS.maximumZoneVertices) {
      issues.push({ key: zone.key, message: `A zone may not exceed ${SCENE_LIMITS.maximumZoneVertices} vertices.` });
    }
    if (zone.loiteringThresholdSeconds !== null
      && (zone.loiteringThresholdSeconds < 1
        || zone.loiteringThresholdSeconds > SCENE_LIMITS.maximumLoiteringThresholdSeconds)) {
      issues.push({
        key: zone.key,
        message: `A loitering threshold must be between 1 and ${SCENE_LIMITS.maximumLoiteringThresholdSeconds} seconds.`,
      });
    }
  }

  for (const zone of draft.zones) {
    const name = zone.name.trim().toLowerCase();
    if (name && (zoneNames.get(name) ?? 0) > 1) {
      issues.push({ key: zone.key, message: 'Another zone already uses this name.' });
    }
  }

  for (const line of draft.tripLines) {
    const name = line.name.trim();
    if (!name) issues.push({ key: line.key, message: 'This trip line needs a name.' });
    else if (name.length > SCENE_LIMITS.maximumNameLength) {
      issues.push({ key: line.key, message: `A name must not exceed ${SCENE_LIMITS.maximumNameLength} characters.` });
    }
    lineNames.set(name.toLowerCase(), (lineNames.get(name.toLowerCase()) ?? 0) + 1);

    if (Math.hypot(line.a.x - line.b.x, line.a.y - line.b.y) < SCENE_LIMITS.minimumLineEndpointSeparation) {
      issues.push({ key: line.key, message: 'The endpoints are too close together to give the line a direction.' });
    }
    if (line.aToBLabel.trim().length > SCENE_LIMITS.maximumDirectionLabelLength
      || line.bToALabel.trim().length > SCENE_LIMITS.maximumDirectionLabelLength) {
      issues.push({
        key: line.key,
        message: `A direction label must not exceed ${SCENE_LIMITS.maximumDirectionLabelLength} characters.`,
      });
    }
  }

  for (const line of draft.tripLines) {
    const name = line.name.trim().toLowerCase();
    if (name && (lineNames.get(name) ?? 0) > 1) {
      issues.push({ key: line.key, message: 'Another trip line already uses this name.' });
    }
  }

  if (draft.zones.length > SCENE_LIMITS.maximumZonesPerRevision) {
    issues.push({ key: null, message: `A revision may carry at most ${SCENE_LIMITS.maximumZonesPerRevision} zones.` });
  }
  if (draft.tripLines.length > SCENE_LIMITS.maximumTripLinesPerRevision) {
    issues.push({
      key: null,
      message: `A revision may carry at most ${SCENE_LIMITS.maximumTripLinesPerRevision} trip lines.`,
    });
  }
  if (draft.note.trim().length > SCENE_LIMITS.maximumNoteLength) {
    issues.push({ key: null, message: `A note must not exceed ${SCENE_LIMITS.maximumNoteLength} characters.` });
  }

  return issues;
}

/** The issues grouped by the object they belong to, for the navigator and the inspector. */
export function issuesByKey(issues: SceneIssue[]): Map<string, SceneIssue[]> {
  const grouped = new Map<string, SceneIssue[]>();
  for (const issue of issues) {
    if (issue.key === null) continue;
    const existing = grouped.get(issue.key);
    if (existing) existing.push(issue);
    else grouped.set(issue.key, [issue]);
  }
  return grouped;
}
