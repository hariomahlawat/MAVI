import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { contentRect } from '../../shared/evidence/projection';
import {
  ZONE_B,
  analysedAnalytics,
  lineCrossing,
  sceneRevision,
  sceneTripLine,
  sceneZone,
  zoneVisit,
} from '../../test/analyticsFixtures';
import { buildAnalyticsEvidence, hasOverlappingStationary } from './analyticsEvidence';
import { STATIONARY_LANE } from '../../shared/evidence/timeline';
import { analyticsLayers } from './analyticsLayers';

/**
 * The overlay is drawn into the video's *content* rectangle, not its element
 * box. Getting this wrong is invisible on a perfectly fitted video and puts
 * every zone in the wrong place the moment the player is letterboxed — which is
 * most of the time, because evidence video rarely matches the panel's aspect.
 */
const PILLARBOX = contentRect(1000, 300, 1920, 1080); // bars left and right
const LETTERBOX = contentRect(500, 500, 1920, 1080); // bars top and bottom

const model = buildAnalyticsEvidence(
  analysedAnalytics({
    zoneVisits: [zoneVisit()],
    lineCrossings: [lineCrossing({ pointX: 0.25, pointY: 0.75 })],
  }),
  sceneRevision({
    zones: [sceneZone(), sceneZone({ zoneId: ZONE_B, name: 'Old store', enabled: false })],
    tripLines: [sceneTripLine()],
  }),
);

/** Renders one layer's SVG output and returns the stage element. */
function draw(layerId: string, frame: typeof PILLARBOX) {
  const layer = analyticsLayers(model).find((candidate) => candidate.id === layerId)!;
  const view = render(<svg>{layer.render(frame, 12_000)}</svg>);
  return view.container.querySelector('svg')!;
}

function points(element: Element | null): { x: number; y: number }[] {
  return (element?.getAttribute('points') ?? '')
    .trim().split(/\s+/)
    .map((pair) => {
      const [x, y] = pair.split(',').map(Number);
      return { x, y };
    });
}

describe('overlay projection', () => {
  it('places zone vertices inside the pillarboxed content rectangle', () => {
    // The frame is 533.33 wide starting at x 233.33; a vertex at normalised
    // 0.2 belongs at 233.33 + 0.2 * 533.33, not at 0.2 * 1000.
    expect(PILLARBOX.x).toBeCloseTo(233.33, 1);
    expect(PILLARBOX.width).toBeCloseTo(533.33, 1);

    const svg = draw('analytics-zones', PILLARBOX);
    const zone = points(svg.querySelectorAll('[data-testid="evidence-zone"]')[0]);
    expect(zone[0].x).toBeCloseTo(233.33 + 0.2 * 533.33, 0);
    expect(zone[0].y).toBeCloseTo(0 + 0.2 * 300, 0);
    expect(zone[2].x).toBeCloseTo(233.33 + 0.6 * 533.33, 0);
    expect(zone[2].y).toBeCloseTo(0 + 0.8 * 300, 0);
    // Never outside the video itself, which is what an element-box projection
    // would produce.
    for (const vertex of zone) {
      expect(vertex.x).toBeGreaterThanOrEqual(PILLARBOX.x);
      expect(vertex.x).toBeLessThanOrEqual(PILLARBOX.x + PILLARBOX.width);
    }
  });

  it('places zone vertices inside the letterboxed content rectangle', () => {
    expect(LETTERBOX.y).toBeCloseTo(109.375, 2);
    expect(LETTERBOX.height).toBeCloseTo(281.25, 2);

    const svg = draw('analytics-zones', LETTERBOX);
    const zone = points(svg.querySelectorAll('[data-testid="evidence-zone"]')[0]);
    expect(zone[0].x).toBeCloseTo(0 + 0.2 * 500, 0);
    expect(zone[0].y).toBeCloseTo(109.375 + 0.2 * 281.25, 0);
    for (const vertex of zone) {
      expect(vertex.y).toBeGreaterThanOrEqual(LETTERBOX.y);
      expect(vertex.y).toBeLessThanOrEqual(LETTERBOX.y + LETTERBOX.height);
    }
  });

  it('places trip-line endpoints on the content rectangle', () => {
    const svg = draw('analytics-lines', LETTERBOX);
    const segment = svg.querySelector('.evidence-line__segment')!;
    expect(Number(segment.getAttribute('x1'))).toBeCloseTo(0.1 * 500, 0);
    expect(Number(segment.getAttribute('x2'))).toBeCloseTo(0.9 * 500, 0);
    expect(Number(segment.getAttribute('y1'))).toBeCloseTo(109.375 + 0.5 * 281.25, 0);
  });

  it('places the crossing glyph at the persisted point', () => {
    const svg = draw('analytics-crossings', PILLARBOX);
    const glyph = points(svg.querySelector('.evidence-crossing__glyph'));
    // The diamond's centre, recovered from its four corners.
    const cx = (glyph[1].x + glyph[3].x) / 2;
    const cy = (glyph[0].y + glyph[2].y) / 2;
    expect(cx).toBeCloseTo(233.33 + 0.25 * 533.33, 0);
    expect(cy).toBeCloseTo(0.75 * 300, 0);
  });
});

describe('overlay evidence grammar', () => {
  it('distinguishes matched from contextual geometry without relying on colour', () => {
    const svg = draw('analytics-zones', PILLARBOX);
    const zones = svg.querySelectorAll('[data-testid="evidence-zone"]');
    // The state reaches the DOM as data, which the stylesheet turns into stroke
    // weight rather than a different hue.
    expect(zones[0].getAttribute('data-matched')).toBe('true');
    expect(zones[1].getAttribute('data-matched')).toBe('false');
  });

  it('marks a disabled zone as disabled and never as matched', () => {
    const svg = draw('analytics-zones', PILLARBOX);
    const disabled = svg.querySelectorAll('[data-testid="evidence-zone"]')[1];
    expect(disabled.getAttribute('data-enabled')).toBe('false');
    expect(disabled.getAttribute('data-matched')).toBe('false');
  });

  it('carries the crossing direction as data, not as colour alone', () => {
    const svg = draw('analytics-crossings', PILLARBOX);
    expect(svg.querySelector('.evidence-crossing')?.getAttribute('data-direction')).toBe('aToB');
    // A diamond of four points: the shape is the cue that survives the hue.
    expect(points(svg.querySelector('.evidence-crossing__glyph'))).toHaveLength(4);
  });

  it('labels the endpoints with letters so direction survives a monochrome view', () => {
    const svg = draw('analytics-lines', PILLARBOX);
    const letters = [...svg.querySelectorAll('.evidence-line__endpoint')].map((n) => n.textContent);
    expect(letters).toEqual(['A', 'B']);
    // The travel directions that count as a crossing are perpendicular to the
    // line, matching the engine's own convention.
    const cues = svg.querySelectorAll('.evidence-line__dir');
    expect(cues).toHaveLength(2);
    const horizontalLine = { x1: 0.1, x2: 0.9 };
    expect(horizontalLine.x1).toBeLessThan(horizontalLine.x2);
    // A horizontal line's cues must move vertically, never along it.
    for (const cue of cues) {
      expect(Number(cue.getAttribute('x1'))).toBeCloseTo(Number(cue.getAttribute('x2')), 5);
      expect(Number(cue.getAttribute('y1'))).not.toBeCloseTo(Number(cue.getAttribute('y2')), 1);
    }
  });

  it('names the crossing layer Crossings, not Events', () => {
    // Stage-7 defines behaviour events; a persisted line crossing is a
    // geometric fact, and borrowing the word now would pull that vocabulary
    // forward into a slice that does not implement it.
    const layer = analyticsLayers(model).find((l) => l.id === 'analytics-crossings')!;
    expect(layer.label).toBe('Crossings');
    expect(analyticsLayers(model).map((l) => l.label)).toEqual(['Zones', 'Trip lines', 'Crossings']);
  });

  it('offers every analytical layer as spatial, so none can omit its semantics', () => {
    for (const layer of analyticsLayers(model)) {
      expect(layer.kind).toBe('spatial');
      expect(layer.describe).toBeTypeOf('function');
    }
  });

  it('offers a layer with nothing to draw as unavailable rather than silently missing', () => {
    const empty = buildAnalyticsEvidence(analysedAnalytics(), sceneRevision({ zones: [], tripLines: [] }));
    for (const layer of analyticsLayers(empty)) {
      expect(layer.available).toBe(false);
      expect(layer.unavailableReason).toBeTruthy();
    }
  });
});

describe('drawing cost does not follow the playhead', () => {
  it('returns the same geometry for the same content rectangle', () => {
    // The player calls render on every animation frame while the media plays.
    // None of this geometry moves with the media, so re-projecting a scene of
    // 64 zones sixty times a second would spend a quarter of a million
    // operations producing an identical picture. The same element reference
    // also lets React skip reconciling the subtree.
    const layer = analyticsLayers(model).find((l) => l.id === 'analytics-zones')!;
    const first = layer.render(PILLARBOX, 0);
    expect(layer.render(PILLARBOX, 12_000)).toBe(first);
    expect(layer.render(PILLARBOX, 599_000)).toBe(first);
  });

  it('redraws when the video is resized, because the projection changes then', () => {
    const layer = analyticsLayers(model).find((l) => l.id === 'analytics-zones')!;
    const wide = layer.render(PILLARBOX, 0);
    const tall = layer.render(LETTERBOX, 0);
    expect(tall).not.toBe(wide);
    // And back again is a fresh projection, not a stale cached one.
    const again = layer.render(PILLARBOX, 0);
    expect(again).not.toBe(tall);
  });

  it('holds for the line and crossing layers too', () => {
    for (const id of ['analytics-lines', 'analytics-crossings']) {
      const layer = analyticsLayers(model).find((l) => l.id === id)!;
      expect(layer.render(PILLARBOX, 5_000)).toBe(layer.render(PILLARBOX, 0));
    }
  });
});

describe('malformed stationary facts are reported, not tidied away', () => {
  it('says so when the persisted stationary intervals overlap', () => {
    // One fixed lane means overlapping intervals paint over each other. The
    // engine should not emit them, so the honest response is to say the facts
    // are wrong rather than to repack them into a layout that makes the
    // overlap look intended.
    const overlapping = buildAnalyticsEvidence(
      analysedAnalytics({
        motion: {
          heading: 'E', pathLengthNormalised: 0, meanDisplacementRate: 0,
          longestStationaryMs: 0, totalStationaryMs: 0,
          stationaryIntervals: [
            { startOffsetMs: 1_000, endOffsetMs: 5_000 },
            { startOffsetMs: 3_000, endOffsetMs: 8_000 },
          ],
          stationaryZoneIds: [],
        },
      }),
      sceneRevision(),
    );
    expect(hasOverlappingStationary(
      overlapping.intervals.filter((i) => i.lane === STATIONARY_LANE),
    )).toBe(true);
  });
});
