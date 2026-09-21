import type { CrossingDirection, MotionDirection } from '../../api/tracks';
import type { SceneTripLine, SceneZone } from '../../api/scene';

/**
 * Operator words for the analytic vocabulary (plan §S "operator presentation").
 *
 * Headings are image directions — north is decreasing y — so they are rendered
 * as Up / Down / Left / Right and never as compass bearings, while the wire
 * keeps the eight letters. A trip line's directions use the labels the operator
 * gave the line when one is known and the neutral A→B / B→A otherwise.
 */
export const MOTION_DIRECTION_LABELS: Record<MotionDirection, string> = {
  N: 'Up',
  NE: 'Up-right',
  E: 'Right',
  SE: 'Down-right',
  S: 'Down',
  SW: 'Down-left',
  W: 'Left',
  NW: 'Up-left',
};

export function motionDirectionLabel(direction: string): string {
  return (MOTION_DIRECTION_LABELS as Record<string, string>)[direction] ?? direction;
}

export const ZONE_RELATION_LABELS = {
  dwelled: 'Dwelled in',
  entered: 'Entered',
  exited: 'Exited',
} as const;

export function crossingDirectionLabel(direction: CrossingDirection, line?: Pick<SceneTripLine, 'aToBLabel' | 'bToALabel'>): string {
  if (direction === 'aToB') return line?.aToBLabel ?? 'A → B';
  return line?.bToALabel ?? 'B → A';
}

/** Enough of a GUID to tell two apart, without pretending to be a name (§24). */
export function shortId(id: string): string {
  return id.slice(0, 8) + '…';
}

/** The names the operator gave the geometry, when the scene that owns it is known. */
export type GeometryNames = {
  zones: ReadonlyMap<string, SceneZone>;
  lines: ReadonlyMap<string, SceneTripLine>;
  /** The revision the names came from, so a chip can say "Revision 4" rather than an id. */
  revisionNumber: number | null;
};

export function zoneLabel(zoneId: string, names: GeometryNames | undefined): string {
  return names?.zones.get(zoneId.toLowerCase())?.name ?? shortId(zoneId);
}

export function lineLabel(lineId: string, names: GeometryNames | undefined): string {
  return names?.lines.get(lineId.toLowerCase())?.name ?? shortId(lineId);
}

export function geometryNames(zones: SceneZone[], lines: SceneTripLine[], revisionNumber: number | null): GeometryNames {
  return {
    zones: new Map(zones.map((zone) => [zone.zoneId.toLowerCase(), zone])),
    lines: new Map(lines.map((line) => [line.lineId.toLowerCase(), line])),
    revisionNumber,
  };
}

/** "scene-analytics-v1" as an operator reads it. */
export function engineLabel(algorithmVersion: string): string {
  const match = /^scene-analytics-v(\d+)$/.exec(algorithmVersion);
  return match ? `Engine v${match[1]}` : algorithmVersion;
}
