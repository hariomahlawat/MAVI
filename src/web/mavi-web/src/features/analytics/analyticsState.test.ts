import { describe, expect, it } from 'vitest';
import type { AnalyticsAggregateResponse } from '../../api/analytics';
import type { AnalyticsCoverage } from '../../api/tracks';
import {
  METRICS,
  presetWindow,
  queryProblem,
  readActivity,
  readingMaximum,
  resolveSubject,
  scopePresence,
  subjectsFor,
} from './analyticsState';

const coverage: AnalyticsCoverage = {
  sceneRevisionId: 'r-1',
  algorithmVersion: 'scene-analytics-v1',
  evaluatedRuns: 2,
  pendingRuns: 0,
  failedRuns: 0,
  notConfiguredRuns: 0,
  disabledRuns: 0,
  staleRuns: 0,
  analysedTracks: 9,
  unavailableTracks: 0,
  complete: true,
};

function response(overrides: Partial<AnalyticsAggregateResponse> = {}): AnalyticsAggregateResponse {
  return {
    cameraId: 'c-1',
    sceneRevisionId: 'r-1',
    sceneRevisionNumber: 4,
    algorithmVersion: 'scene-analytics-v1',
    snapshotVisibilitySequence: 12,
    fromUtc: '2026-09-21T00:00:00Z',
    toUtc: '2026-09-21T02:00:00Z',
    bucketSeconds: 3_600,
    objectClass: null,
    coverage,
    buckets: [
      { startUtc: '2026-09-21T00:00:00Z', endUtc: '2026-09-21T01:00:00Z' },
      { startUtc: '2026-09-21T01:00:00Z', endUtc: '2026-09-21T02:00:00Z' },
    ],
    zones: [
      {
        zoneId: 'z-1',
        name: 'Gate apron',
        entryCounts: [3, 2],
        exitCounts: [1, 4],
        uniqueTrackCounts: [4, 4],
        occupancyAtStart: [0, 2],
        peakOccupancy: 5,
        peakOccupancyAtUtc: '2026-09-21T01:00:00Z',
        windowEntryCount: 5,
        windowExitCount: 5,
        // Deliberately not 8: two of the four Tracks appear in both buckets.
        windowUniqueTrackCount: 6,
        repeatedVisitTrackCount: 2,
      },
    ],
    lines: [
      {
        lineId: 'l-1',
        name: 'Main gate',
        aToBLabel: 'Inbound',
        bToALabel: 'Outbound',
        aToBCounts: [2, 1],
        bToACounts: [0, 3],
        windowAToBCount: 3,
        windowBToACount: 3,
      },
    ],
    classes: [
      { objectClass: 'Person', counts: [4, 4], windowDistinctTrackCount: 6 },
    ],
    ...overrides,
  };
}

describe('window presets', () => {
  it('snaps the window down to a whole bucket so one question is one question', () => {
    // Asked twice a few seconds apart, an unsnapped window would be two windows.
    const a = presetWindow('lastHour', new Date('2026-09-21T06:17:42.500Z'));
    const b = presetWindow('lastHour', new Date('2026-09-21T06:17:59.900Z'));

    expect(a).toEqual(b);
    expect(a.toUtc).toBe('2026-09-21T06:17:00.000Z');
    expect(a.fromUtc).toBe('2026-09-21T05:17:00.000Z');
  });
});

describe('queryProblem', () => {
  const activity = { mode: 'activity' } as const;
  const heatmap = { mode: 'heatmap' } as const;

  it('accepts an ordinary window', () => {
    expect(queryProblem({ ...activity, fromUtc: '2026-09-21T00:00:00Z', toUtc: '2026-09-21T02:00:00Z', bucketSeconds: 900 }))
      .toBeNull();
  });

  it('refuses an empty or inverted window in either mode', () => {
    const inverted = { fromUtc: '2026-09-21T02:00:00Z', toUtc: '2026-09-21T02:00:00Z', bucketSeconds: 900 } as const;
    expect(queryProblem({ ...activity, ...inverted })).toMatch(/after its start/);
    expect(queryProblem({ ...heatmap, ...inverted })).toMatch(/after its start/);
  });

  it('says what to do about a window that would overflow the response', () => {
    const problem = queryProblem({
      ...activity,
      fromUtc: '2026-09-01T00:00:00Z',
      toUtc: '2026-09-21T00:00:00Z',
      bucketSeconds: 60,
    });
    expect(problem).toMatch(/512/);
    expect(problem).toMatch(/Shorten the window or use a longer interval/);
  });

  it('never applies the bucket bound to a heatmap, which takes no interval', () => {
    // The interval left over from Activity says nothing about a map the server
    // would answer perfectly well under its own run and Track bounds.
    const window = { fromUtc: '2026-09-01T00:00:00Z', toUtc: '2026-09-21T00:00:00Z', bucketSeconds: 60 } as const;
    expect(queryProblem({ ...activity, ...window })).not.toBeNull();
    expect(queryProblem({ ...heatmap, ...window })).toBeNull();
  });
});

describe('scopePresence', () => {
  it('lets a complete scope with no facts be drawn as the real zero it is', () => {
    expect(scopePresence({ ...coverage, analysedTracks: 0 })).toBe('observed');
  });

  it('never lets an incomplete scope be drawn as an observation', () => {
    expect(scopePresence({ ...coverage, pendingRuns: 1, complete: false })).toBe('incomplete');
    expect(scopePresence({ ...coverage, staleRuns: 1, complete: false })).toBe('incomplete');
  });
});

describe('readActivity', () => {
  it('reports a non-additive window figure from the wire, not by summing the buckets', () => {
    const reading = readActivity(response(), 'zoneUniqueTracks', 'z-1')!;

    const summed = reading.series[0].points.reduce((total, point) => total + point.value, 0);
    expect(summed).toBe(8);
    // The truth: two Tracks were present in both buckets and are one Track each.
    expect(reading.windowFigures).toEqual([{ label: 'Distinct Tracks in window', value: 6 }]);
    expect(METRICS.zoneUniqueTracks.additive).toBe(false);
  });

  it('reports occupancy as a peak with its instant, not as a total', () => {
    const reading = readActivity(response(), 'zoneOccupancy', 'z-1')!;

    expect(reading.series[0].points.map((point) => point.value)).toEqual([0, 2]);
    expect(reading.windowFigures).toEqual([
      { label: 'Peak occupancy', value: 5, atUtc: '2026-09-21T01:00:00Z' },
    ]);
  });

  it('keeps a trip line’s two directions apart and names them as the operator did', () => {
    const reading = readActivity(response(), 'lineCrossings', 'l-1')!;

    expect(reading.series.map((series) => series.label)).toEqual(['Inbound', 'Outbound']);
    expect(reading.series[1].points.map((point) => point.value)).toEqual([0, 3]);
    expect(reading.windowFigures).toEqual([
      { label: 'Inbound', value: 3 },
      { label: 'Outbound', value: 3 },
    ]);
  });

  it('counts an active Track once for the window however many buckets it spans', () => {
    const reading = readActivity(response(), 'activeTracks', null)!;

    expect(reading.series[0].points.map((point) => point.value)).toEqual([4, 4]);
    expect(reading.windowFigures).toEqual([{ label: 'Distinct Person Tracks', value: 6 }]);
  });

  it('is null for a subject the answer does not contain, rather than a row of zeros', () => {
    // A zone disabled in the resolved revision is absent from the response.
    // Drawing zeros for it would claim it was watched and saw nothing.
    expect(readActivity(response(), 'zoneEntries', 'z-missing')).toBeNull();
    expect(readActivity(response({ classes: [] }), 'activeTracks', null)).toBeNull();
  });

  it('draws the axis to the tallest value across every series', () => {
    expect(readingMaximum(readActivity(response(), 'lineCrossings', 'l-1')!)).toBe(3);
  });
});

describe('subject selection', () => {
  it('offers only what was actually evaluated', () => {
    expect(subjectsFor(response(), 'zoneEntries')).toEqual([{ id: 'z-1', label: 'Gate apron' }]);
    expect(subjectsFor(response(), 'lineCrossings')).toEqual([{ id: 'l-1', label: 'Main gate' }]);
    expect(subjectsFor(response(), 'activeTracks')).toEqual([]);
  });

  it('moves a stale selection onto something real rather than leaving it dangling', () => {
    expect(resolveSubject(response(), 'zoneEntries', 'l-1')).toBe('z-1');
    expect(resolveSubject(response(), 'zoneEntries', 'z-1')).toBe('z-1');
    expect(resolveSubject(response(), 'activeTracks', 'z-1')).toBeNull();
    expect(resolveSubject(undefined, 'zoneEntries', 'z-1')).toBeNull();
  });
});
