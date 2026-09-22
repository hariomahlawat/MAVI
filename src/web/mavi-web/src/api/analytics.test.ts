import { describe, expect, it } from 'vitest';
import {
  ANALYTICS_HEATMAP_SCOPE_TOO_LARGE,
  bucketCount,
  gridHeightFor,
  heatmapScopeRefusal,
  serializeAggregateQuery,
  serializeHeatmapQuery,
  GRID_WIDTHS,
  MAXIMUM_BUCKETS,
} from './analytics';
import { ApiError } from './client';

describe('analytics query serialization', () => {
  it('spells one question one way whatever order the caller wrote it in', () => {
    const a = serializeAggregateQuery({
      fromUtc: '2026-09-21T04:00:00Z',
      toUtc: '2026-09-21T07:00:00Z',
      bucketSeconds: 900,
      objectClass: 'Person',
    });
    const b = serializeAggregateQuery({
      objectClass: 'Person',
      bucketSeconds: 900,
      toUtc: '2026-09-21T07:00:00Z',
      fromUtc: '2026-09-21T04:00:00Z',
    });

    expect(a).toBe(b);
    expect(a).toBe(
      'fromUtc=2026-09-21T04%3A00%3A00Z&toUtc=2026-09-21T07%3A00%3A00Z&bucketSeconds=900&objectClass=Person',
    );
  });

  it('omits what was not asked rather than sending an empty value', () => {
    // The server whitelists keys strictly; an empty parameter is not "no filter".
    expect(serializeHeatmapQuery({ fromUtc: '2026-09-21T04:00:00Z', toUtc: '2026-09-21T07:00:00Z' })).toBe(
      'fromUtc=2026-09-21T04%3A00%3A00Z&toUtc=2026-09-21T07%3A00%3A00Z',
    );
  });
});

describe('bucketCount', () => {
  it('counts a short final bucket, as the server does', () => {
    // 90 minutes in 60-minute buckets is two buckets, the second one short.
    expect(bucketCount('2026-09-21T00:00:00Z', '2026-09-21T01:30:00Z', 3_600)).toBe(2);
  });

  it('agrees with the transport bound at exactly the bound', () => {
    const from = '2026-09-21T00:00:00Z';
    const to = new Date(Date.parse(from) + MAXIMUM_BUCKETS * 60_000).toISOString();
    expect(bucketCount(from, to, 60)).toBe(MAXIMUM_BUCKETS);
  });

  it('is zero for an empty, inverted or unparseable window', () => {
    expect(bucketCount('2026-09-21T01:00:00Z', '2026-09-21T01:00:00Z', 60)).toBe(0);
    expect(bucketCount('2026-09-21T02:00:00Z', '2026-09-21T01:00:00Z', 60)).toBe(0);
    expect(bucketCount('not a time', '2026-09-21T01:00:00Z', 60)).toBe(0);
  });
});

describe('gridHeightFor', () => {
  it('gives the frozen 16:9 companion for every accepted width', () => {
    expect(GRID_WIDTHS.map(gridHeightFor)).toEqual([9, 18, 36, 72]);
  });
});

describe('heatmapScopeRefusal', () => {
  it('reports which bound fired and what it is', () => {
    const error = new ApiError({
      status: 422,
      code: ANALYTICS_HEATMAP_SCOPE_TOO_LARGE,
      detail: 'too large',
      extensions: { dimension: 'coveredRuns', limit: 50 },
    });

    expect(heatmapScopeRefusal(error)).toEqual({ dimension: 'coveredRuns', limit: 50 });
  });

  it('does not invent a dimension the wire did not name', () => {
    const error = new ApiError({
      status: 422,
      code: ANALYTICS_HEATMAP_SCOPE_TOO_LARGE,
      detail: 'too large',
      extensions: { dimension: 'somethingElse' },
    });

    expect(heatmapScopeRefusal(error)).toEqual({ dimension: null, limit: null });
  });

  it('is undefined for any other failure, so nothing else reads as a narrowable scope', () => {
    expect(heatmapScopeRefusal(new ApiError({ status: 503, code: 'analytics_evidence_unreadable', detail: 'x' })))
      .toBeUndefined();
    expect(heatmapScopeRefusal(new Error('network'))).toBeUndefined();
  });
});
