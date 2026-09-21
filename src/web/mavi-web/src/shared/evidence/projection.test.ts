import { describe, expect, it } from 'vitest';
import { contentRect, isBoxVisibleAt, isInsideFrame, projectBox, projectPoint, unprojectPoint } from './projection';

describe('overlay geometry', () => {
  it('letterboxes a 16:9 frame inside a wider element', () => {
    expect(contentRect(1000, 300, 1920, 1080)).toEqual({ x: (1000 - 533.3333333333334) / 2, y: 0, width: 533.3333333333334, height: 300 });
  });

  it('pillarboxes a 16:9 frame inside a taller element', () => {
    const rect = contentRect(400, 600, 1920, 1080);
    expect(rect.width).toBe(400);
    expect(rect.height).toBeCloseTo(225);
    expect(rect.x).toBe(0);
    expect(rect.y).toBeCloseTo(187.5);
  });

  it('falls back to the element box when any dimension is unknown', () => {
    expect(contentRect(640, 360, 0, 0)).toEqual({ x: 0, y: 0, width: 640, height: 360 });
  });

  it('projects normalised boxes and points into the frame rectangle', () => {
    const frame = { x: 10, y: 20, width: 200, height: 100 };
    expect(projectBox({ x: 0.5, y: 0.5, width: 0.25, height: 0.1 }, frame)).toEqual({ x: 110, y: 70, width: 50, height: 10 });
    expect(projectPoint(0, 1, frame)).toEqual({ x: 10, y: 120 });
  });

  it('shows the representative box only near its own frame', () => {
    expect(isBoxVisibleAt(1_000, 1_000)).toBe(true);
    expect(isBoxVisibleAt(1_400, 1_000)).toBe(true);
    expect(isBoxVisibleAt(1_401, 1_000)).toBe(false);
  });

  it('inverts a projection exactly at the corners and the centre', () => {
    const frame = { x: 10, y: 20, width: 200, height: 100 };
    for (const point of [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 0, y: 1 }, { x: 1, y: 1 }, { x: 0.5, y: 0.5 }]) {
      const projected = projectPoint(point.x, point.y, frame);
      expect(unprojectPoint(projected.x, projected.y, frame)).toEqual(point);
    }
  });

  it('round-trips through a letterboxed 16:9 frame within scene precision', () => {
    // A 16:9 source in a square element leaves bars above and below.
    const frame = contentRect(600, 600, 1920, 1080);
    for (const point of [{ x: 0.123456, y: 0.987654 }, { x: 0.3, y: 0.7 }, { x: 0.000001, y: 0.999999 }]) {
      const projected = projectPoint(point.x, point.y, frame);
      const back = unprojectPoint(projected.x, projected.y, frame);
      expect(back.x).toBeCloseTo(point.x, 6);
      expect(back.y).toBeCloseTo(point.y, 6);
    }
  });

  it('round-trips through a pillarboxed portrait frame', () => {
    // A portrait source in a landscape element leaves bars left and right.
    const frame = contentRect(800, 400, 1080, 1920);
    for (const point of [{ x: 0.25, y: 0.25 }, { x: 0.9, y: 0.1 }, { x: 0.5, y: 0.5 }]) {
      const projected = projectPoint(point.x, point.y, frame);
      const back = unprojectPoint(projected.x, projected.y, frame);
      expect(back.x).toBeCloseTo(point.x, 6);
      expect(back.y).toBeCloseTo(point.y, 6);
    }
  });

  it('clamps a position that leaves the frame rather than producing a coordinate out of range', () => {
    const frame = { x: 10, y: 20, width: 200, height: 100 };
    expect(unprojectPoint(-500, -500, frame)).toEqual({ x: 0, y: 0 });
    expect(unprojectPoint(5_000, 5_000, frame)).toEqual({ x: 1, y: 1 });
  });

  it('never produces a coordinate that is not a finite number', () => {
    const frame = { x: 10, y: 20, width: 200, height: 100 };
    expect(unprojectPoint(Number.NaN, 0, frame)).toEqual({ x: 0, y: 0 });
    expect(unprojectPoint(0, Number.POSITIVE_INFINITY, frame)).toEqual({ x: 0, y: 0 });
    expect(unprojectPoint(30, 40, { x: 0, y: 0, width: 0, height: 0 })).toEqual({ x: 0, y: 0 });
  });

  it('tells a click on the image from a click on a letterbox bar', () => {
    const frame = contentRect(600, 600, 1920, 1080);
    // The bars run above and below a 337.5px-tall image centred in 600px.
    expect(isInsideFrame(300, 300, frame)).toBe(true);
    expect(isInsideFrame(300, 10, frame)).toBe(false);
    expect(isInsideFrame(300, 590, frame)).toBe(false);
    expect(isInsideFrame(300, frame.y, frame)).toBe(true);
    expect(isInsideFrame(300, frame.y + frame.height, frame)).toBe(true);
  });

  it('treats a click on a pillarbox bar as outside the image', () => {
    const frame = contentRect(800, 400, 1080, 1920);
    expect(isInsideFrame(400, 200, frame)).toBe(true);
    expect(isInsideFrame(5, 200, frame)).toBe(false);
    expect(isInsideFrame(795, 200, frame)).toBe(false);
  });
});
