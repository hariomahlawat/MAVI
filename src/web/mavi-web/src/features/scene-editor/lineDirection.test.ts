import { describe, expect, it } from 'vitest';
import { aToBNormal, alongLine, bToANormal, crossProduct, midpoint } from './lineDirection';

/**
 * The engine's frozen convention is that arriving on the side where the cross
 * product is negative is `AToB`. These tests check the drawing against that
 * arithmetic rather than against a second copy of the convention, so the sign
 * cannot drift away from the backend.
 */
describe('trip line direction', () => {
  const a = { x: 0.1, y: 0.5 };
  const b = { x: 0.9, y: 0.5 };

  it('points the A to B indicator upwards for a line drawn left to right', () => {
    const normal = aToBNormal(a, b);
    expect(normal).not.toBeNull();
    // Screen axes put y downwards, so upwards is negative y.
    expect(normal!.y).toBeLessThan(0);
    expect(normal!.x).toBeCloseTo(0, 12);
  });

  it('points the B to A indicator downwards for the same line', () => {
    const normal = bToANormal(a, b);
    expect(normal!.y).toBeGreaterThan(0);
    expect(normal!.x).toBeCloseTo(0, 12);
  });

  it('puts the A to B indicator on the side the engine calls A to B', () => {
    const normal = aToBNormal(a, b)!;
    const arrivalSide = { x: 0.5 + normal.x * 0.2, y: 0.5 + normal.y * 0.2 };
    // Negative cross product is the AToB side in LineCrossingDetector.
    expect(crossProduct(a, b, arrivalSide)).toBeLessThan(0);
  });

  it('puts the B to A indicator on the opposite side', () => {
    const normal = bToANormal(a, b)!;
    const arrivalSide = { x: 0.5 + normal.x * 0.2, y: 0.5 + normal.y * 0.2 };
    expect(crossProduct(a, b, arrivalSide)).toBeGreaterThan(0);
  });

  it('reverses every direction when the endpoints are swapped', () => {
    const forward = aToBNormal(a, b)!;
    const reversed = aToBNormal(b, a)!;
    expect(reversed.x).toBeCloseTo(-forward.x, 12);
    expect(reversed.y).toBeCloseTo(-forward.y, 12);
  });

  it.each([
    ['vertical downwards', { x: 0.5, y: 0.1 }, { x: 0.5, y: 0.9 }],
    ['diagonal', { x: 0.2, y: 0.2 }, { x: 0.8, y: 0.7 }],
    ['vertical upwards', { x: 0.5, y: 0.9 }, { x: 0.5, y: 0.1 }],
  ])('agrees with the engine for a %s line', (_name, from, to) => {
    const normal = aToBNormal(from, to)!;
    const centre = midpoint(from, to);
    const arrivalSide = { x: centre.x + normal.x * 0.1, y: centre.y + normal.y * 0.1 };
    expect(crossProduct(from, to, arrivalSide)).toBeLessThan(0);
  });

  it('is a unit vector perpendicular to the line', () => {
    const along = alongLine(a, b)!;
    const normal = aToBNormal(a, b)!;
    expect(Math.hypot(normal.x, normal.y)).toBeCloseTo(1, 12);
    expect(along.x * normal.x + along.y * normal.y).toBeCloseTo(0, 12);
  });

  it('has no direction when the endpoints coincide', () => {
    expect(aToBNormal({ x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 })).toBeNull();
    expect(bToANormal({ x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 })).toBeNull();
    expect(alongLine({ x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 })).toBeNull();
  });

  it('stays perpendicular once the line is projected into pixels', () => {
    // Projection scales x and y by different amounts, so the normal has to be
    // taken in the space the line is drawn in. A normal computed in normalised
    // space and used as a pixel offset would be visibly off the perpendicular.
    const frame = { x: 0, y: 0, width: 640, height: 360 };
    const from = { x: 0.2, y: 0.2 };
    const to = { x: 0.8, y: 0.7 };
    const drawnFrom = { x: frame.x + from.x * frame.width, y: frame.y + from.y * frame.height };
    const drawnTo = { x: frame.x + to.x * frame.width, y: frame.y + to.y * frame.height };

    const drawnDirection = alongLine(drawnFrom, drawnTo)!;
    const drawnNormal = aToBNormal(drawnFrom, drawnTo)!;
    expect(drawnDirection.x * drawnNormal.x + drawnDirection.y * drawnNormal.y).toBeCloseTo(0, 12);

    // The naive normal, taken before projection, is not perpendicular once drawn.
    const naive = aToBNormal(from, to)!;
    expect(Math.abs(drawnDirection.x * naive.x + drawnDirection.y * naive.y)).toBeGreaterThan(0.1);
  });

  it('keeps the drawn normal on the side the engine calls A to B', () => {
    // Projection is a positive axis-aligned scaling, so it cannot move a point
    // across the line: the side a pixel-space normal points to is still the
    // side the backend computes a negative cross product for.
    const frame = { width: 640, height: 360 };
    for (const [from, to] of [
      [{ x: 0.2, y: 0.2 }, { x: 0.8, y: 0.7 }],
      [{ x: 0.9, y: 0.1 }, { x: 0.1, y: 0.8 }],
      [{ x: 0.1, y: 0.5 }, { x: 0.9, y: 0.5 }],
    ] as const) {
      const drawnFrom = { x: from.x * frame.width, y: from.y * frame.height };
      const drawnTo = { x: to.x * frame.width, y: to.y * frame.height };
      const normal = aToBNormal(drawnFrom, drawnTo)!;
      const centre = midpoint(drawnFrom, drawnTo);
      const arrival = { x: centre.x + normal.x * 20, y: centre.y + normal.y * 20 };
      // Back into normalised space, where the engine's rule is stated.
      const normalised = { x: arrival.x / frame.width, y: arrival.y / frame.height };
      expect(crossProduct(from, to, normalised)).toBeLessThan(0);
    }
  });
});
