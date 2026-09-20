import { decodeMsgpack, MsgpackError, type MsgpackValue } from '../../shared/msgpack/decode';

/** One trajectory sample: the Track's centre at a media offset, normalised 0..1. */
export type TrajectoryPoint = {
  offsetMs: number;
  centerX: number;
  centerY: number;
};

export class TrajectoryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TrajectoryError';
  }
}

function isFiniteNumber(value: MsgpackValue): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * The worker's `serialize_trajectory` writes `{v: 1, points: [[offsetMs, cx, cy], …]}`
 * with strictly increasing offsets. This mirrors its `deserialize_trajectory`
 * validation so the browser refuses exactly what the worker would.
 */
export function parseTrajectory(payload: ArrayBuffer | Uint8Array): TrajectoryPoint[] {
  let value: MsgpackValue;
  try {
    value = decodeMsgpack(payload);
  } catch (error) {
    throw new TrajectoryError(error instanceof MsgpackError ? error.message : 'Trajectory payload is not MessagePack.');
  }

  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TrajectoryError('Trajectory payload must be a map.');
  }
  const keys = Object.keys(value).sort();
  if (keys.length !== 2 || keys[0] !== 'points' || keys[1] !== 'v') {
    throw new TrajectoryError('Trajectory payload has unexpected keys.');
  }
  if (value.v !== 1) throw new TrajectoryError('Unsupported trajectory version.');
  if (!Array.isArray(value.points)) throw new TrajectoryError('Trajectory points must be a list.');

  const points: TrajectoryPoint[] = [];
  let previous = -1;
  for (const item of value.points) {
    if (!Array.isArray(item) || item.length !== 3) throw new TrajectoryError('Trajectory point must have three values.');
    const [offset, x, y] = item;
    if (!isFiniteNumber(offset) || !Number.isInteger(offset) || offset < 0) {
      throw new TrajectoryError('Trajectory offset must be a non-negative integer.');
    }
    if (!isFiniteNumber(x) || !isFiniteNumber(y)) throw new TrajectoryError('Trajectory centre must be numeric.');
    if (offset <= previous) throw new TrajectoryError('Trajectory offsets must increase.');
    previous = offset;
    points.push({ offsetMs: offset, centerX: x, centerY: y });
  }
  return points;
}

/**
 * The centre the Track occupied at `offsetMs`, linearly interpolated between
 * the two surrounding samples. Outside the sampled range there is no evidence
 * of position, so the result is null rather than a clamp.
 */
export function trajectoryPositionAt(points: readonly TrajectoryPoint[], offsetMs: number): { x: number; y: number } | null {
  if (points.length === 0 || !Number.isFinite(offsetMs)) return null;
  if (offsetMs < points[0].offsetMs || offsetMs > points[points.length - 1].offsetMs) return null;

  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (points[mid].offsetMs < offsetMs) low = mid + 1;
    else high = mid;
  }
  const after = points[low];
  if (after.offsetMs === offsetMs || low === 0) return { x: after.centerX, y: after.centerY };
  const before = points[low - 1];
  const span = after.offsetMs - before.offsetMs;
  const t = span === 0 ? 0 : (offsetMs - before.offsetMs) / span;
  return {
    x: before.centerX + (after.centerX - before.centerX) * t,
    y: before.centerY + (after.centerY - before.centerY) * t,
  };
}
