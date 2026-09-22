import { describe, expect, it } from 'vitest';
import {
  MAX_ZONE_SUBROWS,
  STATIONARY_LANE,
  ZONE_LANE,
  overflowSegments,
  packIntervals,
  type EvidenceTimelineInterval,
} from '../../shared/evidence/timeline';
import {
  LINE_A,
  ZONE_A,
  ZONE_B,
  ZONE_C,
  ZONE_D,
  analysedAnalytics,
  lineCrossing,
  sceneRevision,
  sceneTripLine,
  sceneZone,
  zoneSummary,
  zoneVisit,
} from '../../test/analyticsFixtures';
import {
  DESCRIBED_VERTEX_SAMPLE,
  buildAnalyticsEvidence,
  extentOf,
  hasOverlappingStationary,
  visitBoundaryNote,
} from './analyticsEvidence';
import { analyticsLayers } from './analyticsLayers';

const revision = sceneRevision({
  zones: [
    sceneZone(),
    sceneZone({ zoneId: ZONE_B, name: 'Loading bay' }),
    sceneZone({ zoneId: ZONE_C, name: 'Old store', enabled: false }),
  ],
  tripLines: [sceneTripLine()],
});

describe('zone visits become timeline evidence', () => {
  it('maps one persisted visit to one interval at its exact offsets', () => {
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ zoneVisits: [zoneVisit()] }),
      revision,
    );

    expect(model.intervals).toHaveLength(1);
    const [interval] = model.intervals;
    expect(interval.lane).toBe(ZONE_LANE);
    expect(interval.startOffsetMs).toBe(11_000);
    expect(interval.endOffsetMs).toBe(14_000);
    expect(interval.label).toContain('Forecourt');
    expect(interval.label).toContain('3s');
  });

  it('keeps two visits to the same zone as two distinct intervals', () => {
    // One row per zone would collapse these; they are separate facts with
    // separate offsets, and an operator counting visits must see two.
    const model = buildAnalyticsEvidence(
      analysedAnalytics({
        zoneVisits: [
          zoneVisit({ visitIndex: 0, entryOffsetMs: 11_000, exitOffsetMs: 12_000 }),
          zoneVisit({ visitIndex: 1, entryOffsetMs: 16_000, exitOffsetMs: 18_000 }),
        ],
      }),
      revision,
    );

    expect(model.intervals).toHaveLength(2);
    expect(new Set(model.intervals.map((i) => i.id)).size).toBe(2);
    expect(model.intervals.map((i) => [i.startOffsetMs, i.endOffsetMs]))
      .toEqual([[11_000, 12_000], [16_000, 18_000]]);
  });
});

describe('boundary markers are never fabricated', () => {
  it('marks an entry and an exit when the Track actually crossed both', () => {
    const model = buildAnalyticsEvidence(analysedAnalytics({ zoneVisits: [zoneVisit()] }), revision);
    expect(model.markers.map((m) => m.kind)).toEqual(['zone-entry', 'zone-exit']);
    expect(model.markers[0].offsetMs).toBe(11_000);
    expect(model.markers[1].offsetMs).toBe(14_000);
  });

  it('adds no entry marker when the Track was already inside', () => {
    // The entry offset is where observation began, not where the Track came
    // through the edge. Calling it an entry would invent an event.
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ zoneVisits: [zoneVisit({ beganInside: true })] }),
      revision,
    );
    expect(model.markers.map((m) => m.kind)).toEqual(['zone-exit']);
    expect(model.intervals[0].label).toContain('already inside when the Track was first observed');
  });

  it('adds no exit marker when the Track was still inside at the end', () => {
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ zoneVisits: [zoneVisit({ endedInside: true })] }),
      revision,
    );
    expect(model.markers.map((m) => m.kind)).toEqual(['zone-entry']);
    expect(model.intervals[0].label).toContain('still inside when the Track was last observed');
  });

  it('adds no exit marker when the visit was closed by a sample gap', () => {
    // The samples stopped; the Track did not leave. This is the case most
    // likely to be mistaken for a boundary crossing, so it says what it is.
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ zoneVisits: [zoneVisit({ closedByGap: true })] }),
      revision,
    );
    expect(model.markers.map((m) => m.kind)).toEqual(['zone-entry']);
    expect(model.intervals[0].label).toContain('closed by a gap in the samples, not by leaving');
  });

  it('describes a visit that both began inside and was cut off', () => {
    expect(visitBoundaryNote(zoneVisit({ beganInside: true, closedByGap: true })))
      .toBe('already inside when the Track was first observed; closed by a gap in the samples, not by leaving');
    expect(visitBoundaryNote(zoneVisit())).toBe('');
  });
});

describe('line crossings are persisted evidence, not recomputed geometry', () => {
  it('keeps the persisted point, offset and direction exactly', () => {
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ lineCrossings: [lineCrossing({ pointX: 0.4321, pointY: 0.6789, offsetMs: 12_345 })] }),
      revision,
    );

    expect(model.crossings).toHaveLength(1);
    const [crossing] = model.crossings;
    // Not the midpoint of the line, not an intersection of the trajectory with
    // it: the coordinates the engine persisted, unrounded.
    expect(crossing.x).toBe(0.4321);
    expect(crossing.y).toBe(0.6789);
    expect(crossing.offsetMs).toBe(12_345);
    expect(model.markers.find((m) => m.kind === 'crossing')?.offsetMs).toBe(12_345);
  });

  it('distinguishes the two directions by the operator wording of the pinned line', () => {
    const both = buildAnalyticsEvidence(
      analysedAnalytics({
        lineCrossings: [
          lineCrossing({ crossingIndex: 0, direction: 'aToB' }),
          lineCrossing({ crossingIndex: 1, direction: 'bToA', offsetMs: 15_000 }),
        ],
      }),
      revision,
    );

    expect(both.crossings.map((c) => c.directionLabel)).toEqual(['Inbound', 'Outbound']);
    expect(both.crossings.map((c) => c.direction)).toEqual(['aToB', 'bToA']);
    // The direction reaches the timeline as words, so it is never carried by
    // colour alone.
    const labels = both.markers.filter((m) => m.kind === 'crossing').map((m) => m.label);
    expect(labels[0]).toContain('Inbound');
    expect(labels[1]).toContain('Outbound');
  });

  it('falls back to a stable id when the pinned geometry could not be loaded', () => {
    // The crossing point is still evidence. Naming its line from some other
    // revision would be a guess, so it is named by its identifier instead.
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ lineCrossings: [lineCrossing()] }),
      undefined,
    );

    expect(model.crossings).toHaveLength(1);
    expect(model.crossings[0].x).toBe(0.4);
    expect(model.crossings[0].lineName).toBe(LINE_A.slice(0, 8) + '…');
    expect(model.crossings[0].directionLabel).toBe('A → B');
    // Nothing is drawn as an outline, because there is no revision to draw.
    expect(model.zones).toEqual([]);
    expect(model.lines).toEqual([]);
  });
});

describe('matched versus contextual geometry', () => {
  it('marks only the geometry this Track actually interacted with', () => {
    const model = buildAnalyticsEvidence(
      analysedAnalytics({
        zoneVisits: [zoneVisit()],
        zoneSummaries: [zoneSummary()],
        lineCrossings: [lineCrossing()],
      }),
      revision,
    );

    expect(model.zones.map((z) => [z.name, z.interacted]))
      .toEqual([['Forecourt', true], ['Loading bay', false], ['Old store', false]]);
    expect(model.zones[0].visitCount).toBe(1);
    expect(model.lines.map((l) => [l.name, l.interacted, l.crossingCount]))
      .toEqual([['Gate line', true, 1]]);
  });

  it('never presents a disabled zone as matched, whatever the ids say', () => {
    // A disabled zone was not evaluated by the engine that produced these
    // facts, so a fact naming it cannot have come from it.
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ zoneVisits: [zoneVisit({ zoneId: ZONE_C })] }),
      revision,
    );

    const disabled = model.zones.find((z) => z.zone.zoneId === ZONE_C);
    expect(disabled?.zone.enabled).toBe(false);
    expect(disabled?.interacted).toBe(false);
  });

  it('never presents a disabled line as matched', () => {
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ lineCrossings: [lineCrossing()] }),
      sceneRevision({ zones: [], tripLines: [sceneTripLine({ enabled: false })] }),
    );
    expect(model.lines[0].interacted).toBe(false);
  });
});

describe('stationary evidence', () => {
  it('maps persisted stationary intervals exactly and classifies nothing itself', () => {
    const model = buildAnalyticsEvidence(
      analysedAnalytics({
        motion: {
          heading: 'E', pathLengthNormalised: 0.4, meanDisplacementRate: 0.01,
          longestStationaryMs: 4_000, totalStationaryMs: 5_000,
          stationaryIntervals: [
            { startOffsetMs: 11_000, endOffsetMs: 15_000 },
            { startOffsetMs: 16_000, endOffsetMs: 17_000 },
          ],
          stationaryZoneIds: [],
        },
      }),
      revision,
    );

    const stationary = model.intervals.filter((i) => i.lane === STATIONARY_LANE);
    expect(stationary.map((i) => [i.startOffsetMs, i.endOffsetMs]))
      .toEqual([[11_000, 15_000], [16_000, 17_000]]);
    expect(stationary[0].label).toContain('4s');
  });

  it('detects malformed overlapping stationary facts rather than painting over them', () => {
    // Stationary is one fixed row. Overlapping intervals would occlude one
    // another silently, which hides evidence; the host states it instead.
    const disjoint = buildAnalyticsEvidence(
      analysedAnalytics({
        motion: {
          heading: 'E', pathLengthNormalised: 0, meanDisplacementRate: 0,
          longestStationaryMs: 0, totalStationaryMs: 0,
          stationaryIntervals: [{ startOffsetMs: 0, endOffsetMs: 10 }, { startOffsetMs: 10, endOffsetMs: 20 }],
          stationaryZoneIds: [],
        },
      }),
      revision,
    );
    expect(hasOverlappingStationary(disjoint.intervals.filter((i) => i.lane === STATIONARY_LANE))).toBe(false);

    const overlapping = buildAnalyticsEvidence(
      analysedAnalytics({
        motion: {
          heading: 'E', pathLengthNormalised: 0, meanDisplacementRate: 0,
          longestStationaryMs: 0, totalStationaryMs: 0,
          stationaryIntervals: [{ startOffsetMs: 0, endOffsetMs: 15 }, { startOffsetMs: 10, endOffsetMs: 20 }],
          stationaryZoneIds: [],
        },
      }),
      revision,
    );
    expect(hasOverlappingStationary(overlapping.intervals.filter((i) => i.lane === STATIONARY_LANE))).toBe(true);
  });
});

describe('nothing analytical is derived in the browser', () => {
  it('produces no facts at all from an analysed Track with no persisted facts', () => {
    // The Track has a trajectory and a pinned revision full of geometry. If
    // anything here inferred a visit from a path crossing a polygon, this would
    // not be empty.
    const model = buildAnalyticsEvidence(analysedAnalytics(), revision);
    expect(model.intervals).toEqual([]);
    expect(model.markers).toEqual([]);
    expect(model.crossings).toEqual([]);
    expect(model.matchedZoneIds.size).toBe(0);
    expect(model.matchedLineIds.size).toBe(0);
    // The geometry is still drawn, as context.
    expect(model.zones).toHaveLength(3);
    expect(model.zones.every((z) => !z.interacted)).toBe(true);
  });

  it('preserves raw evidence semantics when analytics are unavailable', () => {
    // A one-observation Track: valid raw evidence, insufficient for path facts.
    // Analytics honestly says so, and this model adds nothing of its own.
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ status: 'Unavailable', unavailableReason: 'trajectory_too_short', sampleCount: 1 }),
      undefined,
    );
    expect(model.intervals).toEqual([]);
    expect(model.markers).toEqual([]);
  });
});

/** Zone-visit intervals, as the packer receives them. */
function span(id: string, start: number, end: number): EvidenceTimelineInterval {
  return { id, startOffsetMs: start, endOffsetMs: end, label: id, lane: ZONE_LANE };
}

describe('bounded zone-visit packing', () => {
  it('keeps one visit on the first row', () => {
    const packed = packIntervals([span('a', 0, 10)]);
    expect(packed.map((p) => [p.interval.id, p.row, p.concurrent])).toEqual([['a', 0, 1]]);
  });

  it('separates two overlapping visits onto two rows', () => {
    const packed = packIntervals([span('a', 0, 10), span('b', 5, 15)]);
    expect(packed.map((p) => p.row)).toEqual([0, 1]);
    expect(packed.map((p) => p.concurrent)).toEqual([2, 2]);
  });

  it('separates three overlapping visits onto three rows', () => {
    const packed = packIntervals([span('a', 0, 30), span('b', 5, 30), span('c', 10, 30)]);
    expect(packed.map((p) => p.row)).toEqual([0, 1, 2]);
    expect(packed.every((p) => p.concurrent === 3)).toBe(true);
  });

  it('sends a fourth concurrent visit to the overflow rail rather than over an existing one', () => {
    const packed = packIntervals([span('a', 0, 30), span('b', 5, 30), span('c', 10, 30), span('d', 12, 30)]);
    expect(packed.map((p) => p.row)).toEqual([0, 1, 2, null]);
    // The count the rail states, so the operator knows evidence is aggregated.
    expect(packed[3].concurrent).toBe(4);
    // Every input still comes out: overflow is a placement, not a drop.
    expect(packed).toHaveLength(4);
    expect(packed.map((p) => p.interval.id).sort()).toEqual(['a', 'b', 'c', 'd']);
  });

  it('never grows beyond the fixed number of rows however dense the evidence', () => {
    const many = Array.from({ length: 40 }, (_, index) => span(`v${index}`, index, 100));
    const packed = packIntervals(many);
    const rows = new Set(packed.map((p) => p.row).filter((row): row is number => row !== null));
    expect(rows.size).toBeLessThanOrEqual(MAX_ZONE_SUBROWS);
    expect(Math.max(...rows)).toBe(MAX_ZONE_SUBROWS - 1);
    expect(packed).toHaveLength(40);
    expect(packed.filter((p) => p.row === null)).toHaveLength(37);
  });

  it('lets intervals that only touch at an endpoint reuse a row', () => {
    // Touching is not concurrency: nothing is obscured, so a second row would
    // be wasted height.
    const packed = packIntervals([span('a', 0, 10), span('b', 10, 20)]);
    expect(packed.map((p) => p.row)).toEqual([0, 0]);
    expect(packed.map((p) => p.concurrent)).toEqual([1, 1]);
  });

  it('orders equal starts and equal ends deterministically by stable id', () => {
    const forwards = packIntervals([span('b', 0, 10), span('a', 0, 10)]);
    const backwards = packIntervals([span('a', 0, 10), span('b', 0, 10)]);
    expect(forwards.map((p) => p.interval.id)).toEqual(['a', 'b']);
    expect(backwards.map((p) => p.interval.id)).toEqual(['a', 'b']);
    expect(forwards.map((p) => p.row)).toEqual(backwards.map((p) => p.row));

    // Equal starts, different ends: the shorter one is placed first.
    const byEnd = packIntervals([span('long', 0, 20), span('short', 0, 10)]);
    expect(byEnd.map((p) => p.interval.id)).toEqual(['short', 'long']);
  });

  it('keeps an overflowed visit individually identifiable', () => {
    const packed = packIntervals([
      span('a', 0, 30), span('b', 5, 30), span('c', 10, 30),
      span('over-1', 12, 20), span('over-2', 14, 30),
    ]);
    const overflowed = packed.filter((p) => p.row === null);
    expect(overflowed.map((p) => p.interval.id)).toEqual(['over-1', 'over-2']);
    // Each keeps its own identity, offsets and label — the semantic list is
    // built from these, so nothing is merged into an aggregate fact.
    expect(overflowed[0].interval.startOffsetMs).toBe(12);
    expect(overflowed[0].interval.endOffsetMs).toBe(20);
    expect(overflowed[1].interval.startOffsetMs).toBe(14);
  });

  it('changes no offset and merges no visit', () => {
    const input = [span('a', 0, 30), span('b', 5, 30), span('c', 10, 30), span('d', 12, 30)];
    const packed = packIntervals(input);
    for (const entry of packed) {
      const original = input.find((i) => i.id === entry.interval.id);
      expect(entry.interval.startOffsetMs).toBe(original?.startOffsetMs);
      expect(entry.interval.endOffsetMs).toBe(original?.endOffsetMs);
      expect(entry.interval.label).toBe(original?.label);
    }
  });
});

describe('the zone family is not one row per zone', () => {
  it('packs visits to four different zones by concurrency, not by identity', () => {
    // Four zones, but the visits are sequential: one row is enough. A
    // row-per-zone layout would use four and grow with the scene.
    const model = buildAnalyticsEvidence(
      analysedAnalytics({
        zoneVisits: [
          zoneVisit({ zoneId: ZONE_A, visitIndex: 0, entryOffsetMs: 0, exitOffsetMs: 1_000 }),
          zoneVisit({ zoneId: ZONE_B, visitIndex: 0, entryOffsetMs: 2_000, exitOffsetMs: 3_000 }),
          zoneVisit({ zoneId: ZONE_C, visitIndex: 0, entryOffsetMs: 4_000, exitOffsetMs: 5_000 }),
          zoneVisit({ zoneId: ZONE_D, visitIndex: 0, entryOffsetMs: 6_000, exitOffsetMs: 7_000 }),
        ],
      }),
      revision,
    );
    const packed = packIntervals(model.intervals.filter((i) => i.lane === ZONE_LANE));
    expect(packed.every((p) => p.row === 0)).toBe(true);
  });
});

describe('accessible descriptions stay bounded at maximum scene complexity', () => {
  /** The largest scene the contract allows: 64 zones of 64 vertices each. */
  const maximal = sceneRevision({
    zones: Array.from({ length: 64 }, (_, zoneIndex) => sceneZone({
      zoneId: `018f3f5a-2f70-7a2b-8a12-2d02f4c2${(0x1500 + zoneIndex).toString(16)}`,
      name: `Zone ${zoneIndex}`,
      vertices: Array.from({ length: 64 }, (_, vertexIndex) => ({
        x: 0.5 + 0.4 * Math.cos((vertexIndex / 64) * 2 * Math.PI),
        y: 0.5 + 0.4 * Math.sin((vertexIndex / 64) * 2 * Math.PI),
      })),
    })),
    tripLines: [],
  });

  it('never enumerates every vertex, however many a zone has', () => {
    const model = buildAnalyticsEvidence(analysedAnalytics(), maximal);
    expect(model.zones).toHaveLength(64);

    for (const zone of model.zones) {
      // Four sample vertices, not sixty-four. Counting the coordinate pairs is
      // what catches a regression here: a full dump would still "contain" the
      // extent and the count, so asserting on those alone would pass.
      const pairs = zone.description.detail.match(/\(\d\.\d{3}, \d\.\d{3}\)/g) ?? [];
      expect(pairs).toHaveLength(DESCRIBED_VERTEX_SAMPLE);
      // It says what it left out rather than pretending the shape is a square.
      expect(zone.description.detail).toContain('64-sided');
      expect(zone.description.detail).toContain('60 further vertices not listed here');
      // And it gives where the shape is, which is the part that is actually
      // usable without sight of the outline.
      expect(zone.description.detail).toMatch(/spanning x \d\.\d{3} to \d\.\d{3}, y \d\.\d{3} to \d\.\d{3}/);
    }
  });

  it('keeps each zone description short enough to be read', () => {
    const model = buildAnalyticsEvidence(analysedAnalytics(), maximal);
    for (const zone of model.zones) {
      expect(zone.description.detail.length).toBeLessThan(400);
    }
  });

  it('does not grow or rebuild the description as the playhead moves', () => {
    const model = buildAnalyticsEvidence(analysedAnalytics(), maximal);
    const [layer] = analyticsLayers(model);

    const atStart = layer.kind === 'spatial' ? layer.describe(0) : [];
    const atMiddle = layer.kind === 'spatial' ? layer.describe(45_000) : [];
    const atEnd = layer.kind === 'spatial' ? layer.describe(600_000) : [];

    // Same size at every playhead position: the description of a polygon does
    // not depend on where the media is.
    expect(atStart).toHaveLength(64);
    expect(atMiddle).toHaveLength(64);
    expect(atEnd).toHaveLength(64);
    expect(atMiddle.map((d) => d.detail)).toEqual(atStart.map((d) => d.detail));

    // And the same objects, not equal copies: the work of walking 4096
    // vertices happened once when the model was built, not on every frame.
    expect(atMiddle[0]).toBe(atStart[0]);
    expect(atEnd).toBe(atStart);
  });

  it('gives a trip line its complete geometry, because two endpoints are bounded', () => {
    const model = buildAnalyticsEvidence(analysedAnalytics(), sceneRevision({ zones: [] }));
    expect(model.lines[0].description.detail).toContain('From (0.100, 0.500) to (0.900, 0.500)');
    expect(model.lines[0].description.detail).toContain('Inbound one way, Outbound the other');
  });

  it('names a crossing by its persisted point, direction and media time', () => {
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ lineCrossings: [lineCrossing()] }),
      revision,
    );
    const detail = model.crossings[0].description.detail;
    expect(detail).toContain('Inbound');
    expect(detail).toContain('00:12.5');
    expect(detail).toContain('(0.400, 0.600)');
  });

  it('says a zone is disabled rather than merely unmatched', () => {
    // Three different facts an operator must be able to tell apart: evaluated
    // and matched, evaluated and not matched, and never evaluated at all.
    const model = buildAnalyticsEvidence(
      analysedAnalytics({ zoneVisits: [zoneVisit()], zoneSummaries: [zoneSummary()] }),
      revision,
    );
    const [matched, context, disabled] = model.zones;
    expect(matched.description.detail).toContain('This Track was inside it: 1 visit');
    expect(context.description.detail).toContain('Context only');
    expect(disabled.description.detail).toContain('Disabled in this revision');
    expect(disabled.description.detail).not.toContain('Context only');
  });
});

describe('the extent helper', () => {
  it('bounds a polygon and survives a degenerate one', () => {
    expect(extentOf([{ x: 0.2, y: 0.8 }, { x: 0.6, y: 0.1 }, { x: 0.4, y: 0.5 }]))
      .toEqual({ x0: 0.2, y0: 0.1, x1: 0.6, y1: 0.8 });
    expect(extentOf([])).toEqual({ x0: 0, y0: 0, x1: 0, y1: 0 });
  });
});

describe('concurrency means simultaneous, not merely overlapping somewhere', () => {
  it('does not claim a three-way overlap that never happened', () => {
    // A runs the whole span. B is early, C is late, and B and C never share an
    // instant. A pairwise tally would call this three concurrent visits and
    // claim an overlap the evidence does not contain.
    const packed = packIntervals([
      span('a', 0, 100),
      span('b', 0, 40),
      span('c', 60, 100),
    ]);
    const by = (id: string) => packed.find((p) => p.interval.id === id)!;
    expect(by('a').concurrent).toBe(2);
    expect(by('b').concurrent).toBe(2);
    expect(by('c').concurrent).toBe(2);
  });

  it('counts a genuine three-way overlap as three', () => {
    const packed = packIntervals([span('a', 0, 100), span('b', 10, 90), span('c', 20, 80)]);
    for (const entry of packed) expect(entry.concurrent).toBe(3);
  });

  it('counts a lone interval as one', () => {
    expect(packIntervals([span('a', 0, 10)])[0].concurrent).toBe(1);
    // Touching is not sharing an instant.
    const touching = packIntervals([span('a', 0, 10), span('b', 10, 20)]);
    expect(touching.map((p) => p.concurrent)).toEqual([1, 1]);
  });

  it('reports the peak inside a visit, not the count at its start', () => {
    // Nothing overlaps `a` when it begins; the crowd arrives later.
    const packed = packIntervals([span('a', 0, 100), span('b', 50, 100), span('c', 60, 100)]);
    expect(packed.find((p) => p.interval.id === 'a')!.concurrent).toBe(3);
  });
});

describe('the packer survives evidence it should never be handed', () => {
  it('places a zero-duration interval without claiming concurrency', () => {
    const packed = packIntervals([span('a', 0, 100), span('point', 50, 50)]);
    expect(packed).toHaveLength(2);
    expect(packed.find((p) => p.interval.id === 'point')!.concurrent).toBe(1);
    expect(packed.every((p) => p.row !== null)).toBe(true);
  });

  it('does not lose a malformed interval whose end precedes its start', () => {
    // Failing visibly beats silently repairing evidence: the interval keeps the
    // offsets it was given, and nothing pretends they are sensible.
    const packed = packIntervals([span('a', 0, 100), span('backwards', 80, 20)]);
    expect(packed).toHaveLength(2);
    const bad = packed.find((p) => p.interval.id === 'backwards')!;
    expect(bad.interval.startOffsetMs).toBe(80);
    expect(bad.interval.endOffsetMs).toBe(20);
  });

  it('keeps duplicate ids as separate entries rather than collapsing them', () => {
    const packed = packIntervals([span('same', 0, 50), span('same', 10, 60)]);
    expect(packed).toHaveLength(2);
    expect(packed.map((p) => p.row)).toEqual([0, 1]);
  });

  it('handles an interval at offset zero and one ending at the duration', () => {
    const packed = packIntervals([span('start', 0, 10), span('end', 90, 100)]);
    expect(packed.map((p) => p.row)).toEqual([0, 0]);
  });

  it('keeps a hundred overlapping visits bounded and complete', () => {
    const many = Array.from({ length: 100 }, (_, i) => span(`v${i}`, i, 1_000));
    const packed = packIntervals(many);
    expect(packed).toHaveLength(100);
    expect(packed.filter((p) => p.row !== null)).toHaveLength(MAX_ZONE_SUBROWS);
    // Every one of them is still an interval with its own identity.
    expect(new Set(packed.map((p) => p.interval.id)).size).toBe(100);
  });

  it('lets a visit take a row again once the earlier crowd has ended', () => {
    // Four concurrent at the start, but the last one begins after three have
    // finished, so it is drawn rather than pushed into overflow.
    const packed = packIntervals([
      span('a', 0, 20), span('b', 1, 20), span('c', 2, 20), span('later', 30, 40),
    ]);
    expect(packed.find((p) => p.interval.id === 'later')!.row).toBe(0);
    expect(packed.filter((p) => p.row === null)).toHaveLength(0);
  });
});

describe('overflow segments state simultaneous density, not membership', () => {
  it('never reports a bridging chain as three at once', () => {
    // A overlaps B, B overlaps C, A never meets C. Grouping by transitive
    // overlap called that "3"; no instant in it holds three visits.
    const packed = packIntervals([
      ...['f1', 'f2', 'f3'].map((id) => span(id, 0, 30)),
      span('a', 1, 11), span('b', 6, 16), span('c', 15, 21),
    ]);
    const segments = overflowSegments(packed);
    expect(Math.max(...segments.map((segment) => segment.count))).toBe(2);
    // And the density really does vary across the run rather than being flat.
    expect(new Set(segments.map((segment) => segment.count))).toEqual(new Set([1, 2]));
  });

  it('reports a genuine three-way overlap as three', () => {
    const packed = packIntervals([
      ...['f1', 'f2', 'f3'].map((id) => span(id, 0, 30)),
      span('a', 1, 20), span('b', 5, 15), span('c', 7, 12),
    ]);
    const segments = overflowSegments(packed);
    // 7 to 12 is the common intersection of all three.
    const peak = segments.find((segment) => segment.count === 3);
    expect(peak).toBeDefined();
    expect(peak!.startOffsetMs).toBe(7);
    expect(peak!.endOffsetMs).toBe(12);
  });

  it('follows the active set up and down within one contiguous run', () => {
    const packed = packIntervals([
      ...['f1', 'f2', 'f3'].map((id) => span(id, 0, 40)),
      span('a', 1, 30), span('b', 10, 20), span('c', 12, 16),
    ]);
    const segments = overflowSegments(packed);
    // Contiguous, disjoint, and the counts rise then fall with the evidence.
    expect(segments.map((segment) => segment.count)).toEqual([1, 2, 3, 2, 1]);
    for (let i = 1; i < segments.length; i += 1) {
      expect(segments[i].startOffsetMs).toBe(segments[i - 1].endOffsetMs);
    }
  });

  it('does not count an interval that only touches another end to end', () => {
    const packed = packIntervals([
      ...['f1', 'f2', 'f3'].map((id) => span(id, 0, 40)),
      span('a', 1, 10), span('b', 10, 20), span('c', 20, 30),
    ]);
    const segments = overflowSegments(packed);
    expect(segments.map((segment) => segment.count)).toEqual([1, 1, 1]);
  });

  it('keeps two independent dense regions apart', () => {
    const packed = packIntervals([
      ...['a', 'b', 'c', 'd'].map((id, i) => span(id, i, 50)),
      ...['e', 'f', 'g', 'h'].map((id, i) => span(id, 100 + i, 150)),
    ]);
    const segments = overflowSegments(packed);
    expect(segments).toHaveLength(2);
    // Disjoint, so one can never be drawn over the other.
    expect(segments[0].endOffsetMs).toBeLessThanOrEqual(segments[1].startOffsetMs);
  });

  it('coalesces a boundary that changes nothing', () => {
    // Three identical overflowed visits: one band, not three, because the
    // active set never changes across them.
    const packed = packIntervals(
      Array.from({ length: 6 }, (_, i) => span(`v${i}`, 10, 20)),
    );
    const segments = overflowSegments(packed);
    expect(segments).toHaveLength(1);
    expect(segments[0].count).toBe(3);
    expect(segments[0].startOffsetMs).toBe(10);
    expect(segments[0].endOffsetMs).toBe(20);
  });

  it('has no segments when nothing overflowed', () => {
    expect(overflowSegments(packIntervals([span('a', 0, 10), span('b', 5, 15)]))).toEqual([]);
  });
});
