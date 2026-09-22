import type { ScenePoint } from '../../api/scene';

/**
 * Which way a trip line is crossed, drawn to agree with the engine.
 *
 * The frozen rule (plan section K, implemented in `LineCrossingDetector`) is
 * that arriving on the left-hand side of A to B is `AToB`. Image axes put y
 * downwards, so the cross product of the line's direction with the vector to a
 * point is negative on that side, and the side is the one visually *above* a
 * line drawn left to right.
 *
 * A crossing direction is therefore perpendicular to the line, never along it.
 * Drawing an arrow from A towards B would show where the endpoints are, not
 * which way a Track has to move to count as `AToB`.
 */

export type UnitVector = { x: number; y: number };

/** The unit vector along A to B, or null when the endpoints coincide. */
export function alongLine(a: ScenePoint, b: ScenePoint): UnitVector | null {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy);
  if (!Number.isFinite(length) || length <= 0) return null;
  return { x: dx / length, y: dy / length };
}

/**
 * The unit normal pointing to the side a Track arrives on when it crosses
 * `AToB`, proportional to `(dy, -dx)`.
 *
 * For a line drawn left to right this points upwards on screen, which is the
 * direction a Track must be travelling to cross A to B.
 */
export function aToBNormal(a: ScenePoint, b: ScenePoint): UnitVector | null {
  const direction = alongLine(a, b);
  if (!direction) return null;
  return { x: direction.y, y: -direction.x };
}

/** The opposite side: the direction of travel that counts as `BToA`. */
export function bToANormal(a: ScenePoint, b: ScenePoint): UnitVector | null {
  const normal = aToBNormal(a, b);
  return normal ? { x: -normal.x, y: -normal.y } : null;
}

/**
 * The sign the engine computes for a point, as a cross product of the line
 * direction with the vector to the point. Negative is the `AToB` side.
 *
 * Exposed so a test can check the drawing against the same arithmetic the
 * backend uses rather than against another copy of the convention.
 */
export function crossProduct(a: ScenePoint, b: ScenePoint, point: ScenePoint): number {
  return (b.x - a.x) * (point.y - a.y) - (b.y - a.y) * (point.x - a.x);
}

/** The midpoint of the line, where the crossing indicator is anchored. */
export function midpoint(a: ScenePoint, b: ScenePoint): ScenePoint {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * A triangular head for a direction ray, pointing along `(dx, dy)`.
 *
 * Takes the direction it is given rather than deriving one, so the caller
 * decides which space it is in — and every caller works in **projected pixel**
 * space, because that is the only space in which "perpendicular" means what the
 * operator sees.
 */
export function arrowHead(x: number, y: number, dx: number, dy: number, size = 5): string {
  const nx = -dy;
  const ny = dx;
  return [
    `${x + dx * size},${y + dy * size}`,
    `${x - dx * size + nx * size * 0.7},${y - dy * size + ny * size * 0.7}`,
    `${x - dx * size - nx * size * 0.7},${y - dy * size - ny * size * 0.7}`,
  ].join(' ');
}
