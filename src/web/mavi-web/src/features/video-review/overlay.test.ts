import { describe, expect, it } from 'vitest';
import { contentRect, isBoxVisibleAt, projectBox, projectPoint } from './overlay';

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
});
