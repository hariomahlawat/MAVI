import { describe, expect, it } from 'vitest';
import { hasSampleAt, parseTrajectory, TrajectoryError, trajectoryPositionAt } from './trajectory';

function str(value: string): number[] {
  const bytes = Array.from(new TextEncoder().encode(value));
  return [0xa0 | bytes.length, ...bytes];
}
function f64(value: number): number[] {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  return [0xcb, ...Array.from(new Uint8Array(view.buffer))];
}
function payload(points: Array<[number, number, number]>, version = 1): Uint8Array {
  return new Uint8Array([
    0x82, ...str('v'), version,
    ...str('points'), 0x90 | points.length,
    ...points.flatMap(([offset, x, y]) => [0x93, offset, ...f64(x), ...f64(y)]),
  ]);
}

describe('parseTrajectory', () => {
  it('parses increasing samples into points', () => {
    expect(parseTrajectory(payload([[0, 0.1, 0.2], [40, 0.3, 0.4]]))).toEqual([
      { offsetMs: 0, centerX: 0.1, centerY: 0.2 },
      { offsetMs: 40, centerX: 0.3, centerY: 0.4 },
    ]);
  });

  it('rejects an unsupported version, non-increasing offsets and malformed bytes', () => {
    expect(() => parseTrajectory(payload([[0, 0, 0]], 2))).toThrow(/version/);
    expect(() => parseTrajectory(payload([[5, 0, 0], [5, 0, 0]]))).toThrow(/increase/);
    expect(() => parseTrajectory(new Uint8Array([0xc4]))).toThrow(TrajectoryError);
  });

  /*
   * Slice 7, deferred obligation 1. The application decoder that decides whether
   * a trajectory may produce facts rejects a centre outside the unit interval
   * (`NormalizedPoint.IsInRange`: finite, and within [0, 1] once rounded to the
   * persisted six decimals). The browser accepted any finite number, so a
   * corrupt or hostile artefact could be drawn as a position outside the frame
   * while the server refused to derive anything from it — two different answers
   * about the same sealed evidence.
   */
  it('rejects a finite centre outside the unit interval, as the application decoder does', () => {
    expect(() => parseTrajectory(payload([[0, -0.5, 0.5]]))).toThrow(/\[0, 1\]/);
    expect(() => parseTrajectory(payload([[0, 1.5, 0.5]]))).toThrow(/\[0, 1\]/);
    expect(() => parseTrajectory(payload([[0, 0.5, -0.5]]))).toThrow(/\[0, 1\]/);
    expect(() => parseTrajectory(payload([[0, 0.5, 1.5]]))).toThrow(/\[0, 1\]/);
    // Barely outside still counts: the rule is the rounded value, not a tolerance.
    expect(() => parseTrajectory(payload([[0, 1.000002, 0.5]]))).toThrow(/\[0, 1\]/);
    expect(() => parseTrajectory(payload([[0, 0.5, -0.000002]]))).toThrow(/\[0, 1\]/);
  });

  it('keeps the closed interval closed: exactly 0 and exactly 1 are valid', () => {
    // The complement, so the range check cannot pass by rejecting the edges the
    // frame legitimately contains.
    expect(parseTrajectory(payload([[0, 0, 0], [40, 1, 1]]))).toEqual([
      { offsetMs: 0, centerX: 0, centerY: 0 },
      { offsetMs: 40, centerX: 1, centerY: 1 },
    ]);
  });

  it('accepts a value that only rounds into range, matching the persisted precision', () => {
    // Six-decimal rounding is part of the frozen rule, so a coordinate a hair
    // outside is in range exactly when the persisted value would be.
    expect(parseTrajectory(payload([[0, 1.0000004, -0.0000004]]))).toEqual([
      { offsetMs: 0, centerX: 1.0000004, centerY: -0.0000004 },
    ]);
  });
});

describe('trajectoryPositionAt', () => {
  const points = [
    { offsetMs: 0, centerX: 0, centerY: 0 },
    { offsetMs: 100, centerX: 1, centerY: 0.5 },
    { offsetMs: 300, centerX: 0, centerY: 1 },
  ];

  it('interpolates linearly between samples and returns samples exactly', () => {
    expect(trajectoryPositionAt(points, 50)).toEqual({ x: 0.5, y: 0.25 });
    expect(trajectoryPositionAt(points, 200)).toEqual({ x: 0.5, y: 0.75 });
    expect(trajectoryPositionAt(points, 100)).toEqual({ x: 1, y: 0.5 });
  });

  it('returns the one persisted sample of a single-observation Track, and nothing beside it', () => {
    // The worker finalises a Track on one observation, so a one-point
    // trajectory is valid evidence. At that offset the sample is the position;
    // anywhere else there is nothing to interpolate between and no position is
    // claimed, in either direction.
    const single = [{ offsetMs: 120, centerX: 0.25, centerY: 0.75 }];
    expect(trajectoryPositionAt(single, 120)).toEqual({ x: 0.25, y: 0.75 });
    expect(trajectoryPositionAt(single, 119)).toBeNull();
    expect(trajectoryPositionAt(single, 121)).toBeNull();
    expect(hasSampleAt(single, 120)).toBe(true);
    expect(hasSampleAt(single, 119)).toBe(false);
    expect(hasSampleAt([], 120)).toBe(false);
  });

  it('claims no position outside the sampled range', () => {
    expect(trajectoryPositionAt(points, -1)).toBeNull();
    expect(trajectoryPositionAt(points, 301)).toBeNull();
    expect(trajectoryPositionAt([], 0)).toBeNull();
  });
});
