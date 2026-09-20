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
});
