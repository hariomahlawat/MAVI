import { apiJson, apiRequest } from './client';

/**
 * The scene-configuration contracts frozen in Slice 0
 * (`Mavi.Contracts/Api/Scene`), mirrored by hand as the rest of this client
 * mirrors its server contracts.
 *
 * Coordinates are normalised to the source video frame: origin top-left, x
 * right, y down, both in [0, 1]. The backend is the authority on every
 * geometric and identity rule; these types only describe the wire.
 */

/** The closed vocabulary of zone kinds. Sent case-sensitively, exactly as listed. */
export const SCENE_ZONE_KINDS = ['General', 'Restricted', 'Entrance', 'Exit'] as const;

export type SceneZoneKind = (typeof SCENE_ZONE_KINDS)[number];

export const DEFAULT_SCENE_ZONE_KIND: SceneZoneKind = 'General';

/** Transport bounds, matching `SceneContractRules` by value. */
export const SCENE_LIMITS = {
  minimumZoneVertices: 3,
  maximumZoneVertices: 64,
  maximumZonesPerRevision: 64,
  maximumTripLinesPerRevision: 64,
  maximumNameLength: 64,
  maximumDirectionLabelLength: 32,
  maximumNoteLength: 500,
  /** Endpoints closer than this are the same point to the backend. */
  minimumLineEndpointSeparation: 0.005,
  maximumLoiteringThresholdSeconds: 86_400,
  /** Fixed persisted precision of a coordinate component. */
  coordinateDecimals: 6,
} as const;

export type ScenePoint = { x: number; y: number };

export type SceneZone = {
  zoneId: string;
  name: string;
  kind: string;
  enabled: boolean;
  vertices: ScenePoint[];
  loiteringThresholdSeconds: number | null;
};

export type SceneTripLine = {
  lineId: string;
  name: string;
  enabled: boolean;
  a: ScenePoint;
  b: ScenePoint;
  directed: boolean;
  aToBLabel: string;
  bToALabel: string;
};

export type SceneRevision = {
  revisionId: string;
  revisionNumber: number;
  cameraId: string;
  createdAtUtc: string;
  createdBy: string;
  note: string | null;
  referenceFrameVideoAssetId: string | null;
  referenceFrameOffsetMs: number | null;
  zones: SceneZone[];
  tripLines: SceneTripLine[];
  /** Derived by the server from the geometry; never sent back. */
  analyticsEnabled: boolean;
};

export type SceneRevisionSummary = {
  revisionId: string;
  revisionNumber: number;
  createdAtUtc: string;
  createdBy: string;
  note: string | null;
  analyticsEnabled: boolean;
  zoneCount: number;
  tripLineCount: number;
};

export type CameraScene = {
  cameraId: string;
  /** False when the camera has never had a revision, which is not the same as one that disables analytics. */
  configured: boolean;
  activeRevision: SceneRevision | null;
  history: SceneRevisionSummary[];
};

/**
 * A zone as submitted. `zoneId` is omitted for a new zone and carries an
 * existing stable identity when the operator is keeping one across revisions.
 * The browser never mints an identity: the server issues a UUIDv7.
 */
export type SaveSceneZoneRequest = {
  zoneId?: string;
  name: string;
  kind: string;
  enabled: boolean;
  vertices: ScenePoint[];
  loiteringThresholdSeconds: number | null;
};

export type SaveSceneTripLineRequest = {
  lineId?: string;
  name: string;
  enabled: boolean;
  a: ScenePoint;
  b: ScenePoint;
  directed: boolean;
  aToBLabel: string;
  bToALabel: string;
};

/**
 * The whole scene, not a patch. `expectedRevisionNumber` is the revision the
 * editor was working from, or 0 when the camera has no configuration yet.
 */
export type SaveSceneRequest = {
  expectedRevisionNumber: number;
  note: string | null;
  referenceFrameVideoAssetId: string | null;
  referenceFrameOffsetMs: number | null;
  zones: SaveSceneZoneRequest[];
  tripLines: SaveSceneTripLineRequest[];
};

export function getCameraScene(cameraId: string, signal?: AbortSignal): Promise<CameraScene> {
  return apiRequest<CameraScene>(`/api/cameras/${encodeURIComponent(cameraId)}/scene`, { signal });
}

export function getCameraSceneRevision(
  cameraId: string,
  revisionNumber: number,
  signal?: AbortSignal,
): Promise<SceneRevision> {
  return apiRequest<SceneRevision>(
    `/api/cameras/${encodeURIComponent(cameraId)}/scene/revisions/${revisionNumber}`,
    { signal },
  );
}

export function saveCameraScene(
  cameraId: string,
  request: SaveSceneRequest,
  signal?: AbortSignal,
): Promise<SceneRevision> {
  return apiJson<SceneRevision>(`/api/cameras/${encodeURIComponent(cameraId)}/scene`, 'PUT', request, signal);
}

/** The evidence content URL for a video asset, as the Track contracts already build it. */
export function videoContentUrl(videoAssetId: string): string {
  return `/api/videos/${encodeURIComponent(videoAssetId)}/content`;
}

export function isSceneZoneKind(value: string): value is SceneZoneKind {
  return (SCENE_ZONE_KINDS as readonly string[]).includes(value);
}
