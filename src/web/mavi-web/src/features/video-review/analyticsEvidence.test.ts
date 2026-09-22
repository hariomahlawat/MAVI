import { describe, expect, it } from 'vitest';
import {
  MAX_ZONE_SUBROWS,
  STATIONARY_LANE,
  ZONE_LANE,
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
  buildAnalyticsEvidence,
  hasOverlappingStationary,
  visitBoundaryNote,
} from './analyticsEvidence';

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
