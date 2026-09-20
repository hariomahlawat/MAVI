import {
  DEFAULT_SCENE_ZONE_KIND,
  SCENE_LIMITS,
  isSceneZoneKind,
  type CameraScene,
  type SaveSceneRequest,
  type SaveSceneTripLineRequest,
  type SaveSceneZoneRequest,
  type ScenePoint,
  type SceneRevision,
  type SceneZoneKind,
} from '../../api/scene';

/**
 * The editor's own model of a scene being edited.
 *
 * Every object carries a local key that exists only in this browser session and
 * a `zoneId`/`lineId` that is null until the server has issued one. Keeping the
 * two apart is what makes the stable-identity rules safe: a saved object keeps
 * the identity the server gave it, a new object sends none, and a deleted
 * object is simply absent from the next revision. The browser never invents a
 * persistent identity, and an identity from a historical revision can never be
 * submitted because a historical revision is never loaded into a draft.
 */

export type DraftZone = {
  /** Local only. Stable for the lifetime of this draft, never sent. */
  key: string;
  /** The server-issued identity, or null while the zone is new. */
  zoneId: string | null;
  name: string;
  kind: SceneZoneKind;
  enabled: boolean;
  vertices: ScenePoint[];
  loiteringThresholdSeconds: number | null;
};

export type DraftTripLine = {
  key: string;
  lineId: string | null;
  name: string;
  enabled: boolean;
  a: ScenePoint;
  b: ScenePoint;
  directed: boolean;
  aToBLabel: string;
  bToALabel: string;
};

export type SceneDraft = {
  /** The revision this draft was loaded from; 0 when the camera has no scene yet. */
  baseRevisionNumber: number;
  note: string;
  referenceFrameVideoAssetId: string | null;
  referenceFrameOffsetMs: number | null;
  zones: DraftZone[];
  tripLines: DraftTripLine[];
};

let keyCounter = 0;

/** A local key. Deliberately not a UUID, so it can never be mistaken for an identity. */
export function nextLocalKey(prefix: 'zone' | 'line'): string {
  keyCounter += 1;
  return `${prefix}-local-${keyCounter}`;
}

/** Rounds a coordinate to the precision the scene model persists. */
export function roundCoordinate(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const factor = 10 ** SCENE_LIMITS.coordinateDecimals;
  return Math.round(value * factor) / factor;
}

export function roundPoint(point: ScenePoint): ScenePoint {
  return { x: roundCoordinate(point.x), y: roundCoordinate(point.y) };
}

export function clampUnit(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

export function clampPoint(point: ScenePoint): ScenePoint {
  return roundPoint({ x: clampUnit(point.x), y: clampUnit(point.y) });
}

/** The draft that an active revision, or the absence of one, starts from. */
export function draftFromScene(scene: CameraScene | undefined): SceneDraft {
  const revision = scene?.activeRevision ?? null;
  return revision ? draftFromRevision(revision) : emptyDraft();
}

export function emptyDraft(): SceneDraft {
  return {
    baseRevisionNumber: 0,
    note: '',
    referenceFrameVideoAssetId: null,
    referenceFrameOffsetMs: null,
    zones: [],
    tripLines: [],
  };
}

/**
 * Copies a revision into an editable draft.
 *
 * Every value is copied rather than referenced, so editing the draft can never
 * mutate the cached API response that the reset action restores from.
 */
export function draftFromRevision(revision: SceneRevision): SceneDraft {
  return {
    baseRevisionNumber: revision.revisionNumber,
    note: '',
    referenceFrameVideoAssetId: revision.referenceFrameVideoAssetId,
    referenceFrameOffsetMs: revision.referenceFrameOffsetMs,
    zones: revision.zones.map((zone) => ({
      key: nextLocalKey('zone'),
      zoneId: zone.zoneId,
      name: zone.name,
      kind: isSceneZoneKind(zone.kind) ? zone.kind : DEFAULT_SCENE_ZONE_KIND,
      enabled: zone.enabled,
      vertices: zone.vertices.map((vertex) => ({ x: vertex.x, y: vertex.y })),
      loiteringThresholdSeconds: zone.loiteringThresholdSeconds,
    })),
    tripLines: revision.tripLines.map((line) => ({
      key: nextLocalKey('line'),
      lineId: line.lineId,
      name: line.name,
      enabled: line.enabled,
      a: { x: line.a.x, y: line.a.y },
      b: { x: line.b.x, y: line.b.y },
      directed: line.directed,
      aToBLabel: line.aToBLabel,
      bToALabel: line.bToALabel,
    })),
  };
}

/** The request body for save-and-activate: the whole scene, never a patch. */
export function saveRequestFromDraft(draft: SceneDraft): SaveSceneRequest {
  return {
    expectedRevisionNumber: draft.baseRevisionNumber,
    note: draft.note.trim() ? draft.note.trim() : null,
    // The pair is sent whole or not at all; the backend refuses half of one.
    referenceFrameVideoAssetId: draft.referenceFrameVideoAssetId,
    referenceFrameOffsetMs: draft.referenceFrameVideoAssetId ? draft.referenceFrameOffsetMs : null,
    zones: draft.zones.map(zoneRequest),
    tripLines: draft.tripLines.map(lineRequest),
  };
}

function zoneRequest(zone: DraftZone): SaveSceneZoneRequest {
  const request: SaveSceneZoneRequest = {
    name: zone.name.trim(),
    kind: zone.kind,
    enabled: zone.enabled,
    vertices: zone.vertices.map(roundPoint),
    loiteringThresholdSeconds: zone.loiteringThresholdSeconds,
  };
  // A new zone sends no identity at all, rather than a null the server would
  // have to interpret.
  if (zone.zoneId) request.zoneId = zone.zoneId;
  return request;
}

function lineRequest(line: DraftTripLine): SaveSceneTripLineRequest {
  const request: SaveSceneTripLineRequest = {
    name: line.name.trim(),
    enabled: line.enabled,
    a: roundPoint(line.a),
    b: roundPoint(line.b),
    directed: line.directed,
    aToBLabel: line.aToBLabel.trim(),
    bToALabel: line.bToALabel.trim(),
  };
  if (line.lineId) request.lineId = line.lineId;
  return request;
}

/**
 * True when the draft would produce a revision that disables analytics: no
 * geometry at all, or none of it enabled.
 */
export function draftAnalyticsEnabled(draft: SceneDraft): boolean {
  return draft.zones.some((zone) => zone.enabled) || draft.tripLines.some((line) => line.enabled);
}

/**
 * Whether the draft differs materially from the revision it was loaded from.
 *
 * Compared on the submitted shape, so selecting an object, switching tool or
 * scrubbing a video cannot make a scene look edited. The note is excluded on
 * purpose: it describes a save that has not happened, and typing one is not a
 * change to the scene.
 */
export function isDraftDirty(draft: SceneDraft, baseline: SceneDraft): boolean {
  const left = saveRequestFromDraft({ ...draft, note: '' });
  const right = saveRequestFromDraft({ ...baseline, note: '' });
  return JSON.stringify(left) !== JSON.stringify(right);
}
