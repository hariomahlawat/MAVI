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

  it('labels the endpoints with letters so orientation survives a monochrome view', () => {
    const svg = draw('analytics-lines', PILLARBOX);
    const letters = [...svg.querySelectorAll('.evidence-line__endpoint')].map((n) => n.textContent);
    expect(letters).toEqual(['A', 'B']);
  });

  it('distinguishes the two crossing directions without relying on hue', () => {
    // A and B say which end is which; they do not say which perpendicular ray
    // is the A-to-B crossing. Two plain opposing rays collapse into one
    // undirected line as soon as their hues cannot be told apart, so each ray
    // carries an arrowhead and the operator's own word for that direction.
    const svg = draw('analytics-lines', PILLARBOX);
    const atob = svg.querySelector('[data-testid="evidence-line-atob"]')!;
    const btoa = svg.querySelector('[data-testid="evidence-line-btoa"]')!;

    for (const ray of [atob, btoa]) {
      // An arrowhead: three points, so the ray has a head and a tail.
      expect(points(ray.querySelector('polygon'))).toHaveLength(3);
    }
    // And the operator's own words, which is what actually names the direction.
    expect(atob.querySelector('text')?.textContent).toBe('Inbound');
    expect(btoa.querySelector('text')?.textContent).toBe('Outbound');
  });

  it('falls back to neutral direction wording when the line has no labels', () => {
    const unlabelled = buildAnalyticsEvidence(
      analysedAnalytics(),
      sceneRevision({ zones: [], tripLines: [sceneTripLine({ aToBLabel: '', bToALabel: '' })] }),
    );
    const layer = analyticsLayers(unlabelled).find((l) => l.id === 'analytics-lines')!;
    const view = render(<svg>{layer.render(PILLARBOX, 0)}</svg>);
    const texts = [...view.container.querySelectorAll('.evidence-line__dir text')].map((n) => n.textContent);
    expect(texts).toEqual(['A → B', 'B → A']);
  });
});

/** The angle between two vectors, in degrees. */
function angleBetween(u: { x: number; y: number }, v: { x: number; y: number }): number {
  const dot = u.x * v.x + u.y * v.y;
  const magnitude = Math.hypot(u.x, u.y) * Math.hypot(v.x, v.y);
  return Math.acos(Math.max(-1, Math.min(1, dot / magnitude))) * (180 / Math.PI);
}

describe('direction cues are perpendicular in the space they are drawn in', () => {
  // A diagonal line is the case that exposes the defect: projection scales x
  // and y by different amounts, so a normal taken in normalised coordinates and
  // used as a pixel offset is not perpendicular to the *rendered* line. An
  // axis-aligned line hides this completely, which is why the original test
  // passed while the geometry was wrong.
  const diagonal = buildAnalyticsEvidence(
    analysedAnalytics(),
    sceneRevision({
      zones: [],
      tripLines: [sceneTripLine({ a: { x: 0.15, y: 0.2 }, b: { x: 0.85, y: 0.9 } })],
    }),
  );

  function measure(frame: typeof PILLARBOX) {
    const layer = analyticsLayers(diagonal).find((l) => l.id === 'analytics-lines')!;
    const view = render(<svg>{layer.render(frame, 0)}</svg>);
    const segment = view.container.querySelector('.evidence-line__segment')!;
    const along = {
      x: Number(segment.getAttribute('x2')) - Number(segment.getAttribute('x1')),
      y: Number(segment.getAttribute('y2')) - Number(segment.getAttribute('y1')),
    };
    const rays = [...view.container.querySelectorAll('.evidence-line__dir line')].map((ray) => ({
      x: Number(ray.getAttribute('x2')) - Number(ray.getAttribute('x1')),
      y: Number(ray.getAttribute('y2')) - Number(ray.getAttribute('y1')),
    }));
    view.unmount();
    return { along, rays };
  }

  it.each([
    ['pillarboxed', PILLARBOX],
    ['letterboxed', LETTERBOX],
    ['square', contentRect(600, 600, 600, 600)],
  ])('keeps both cues perpendicular to the drawn line on %s evidence', (_name, frame) => {
    const { along, rays } = measure(frame);
    expect(rays).toHaveLength(2);
    for (const ray of rays) {
      expect(angleBetween(along, ray)).toBeCloseTo(90, 4);
    }
    // And they point to opposite sides of it, so they are two directions.
    expect(angleBetween(rays[0], rays[1])).toBeCloseTo(180, 4);
  });

  it('keeps the A-to-B cue on the side the engine calls A to B', () => {
    // Projection is a positive axis-aligned scaling, so it cannot flip which
    // side of the line a point is on. The rendered cue must therefore agree
    // with the engine's own cross-product convention.
    const { along, rays } = measure(LETTERBOX);
    // Image axes put y downwards, so the A-to-B side is where the cross product
    // of the line direction with the vector to the point is negative.
    const cross = along.x * rays[0].y - along.y * rays[0].x;
    expect(cross).toBeLessThan(0);
  });

  it('draws no cue for an undirected line', () => {
    const undirected = buildAnalyticsEvidence(
      analysedAnalytics(),
      sceneRevision({ zones: [], tripLines: [sceneTripLine({ directed: false })] }),
    );
    const layer = analyticsLayers(undirected).find((l) => l.id === 'analytics-lines')!;
    const view = render(<svg>{layer.render(PILLARBOX, 0)}</svg>);
    expect(view.container.querySelectorAll('.evidence-line__dir')).toHaveLength(0);
  });
});

describe('overlay evidence grammar, continued', () => {
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
