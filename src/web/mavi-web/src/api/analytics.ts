import { apiRequest, problemNumber, problemText, ApiError } from './client';
import type { AnalyticsCoverage, TrackObjectClass } from './tracks';

/**
 * The Slice 6 read-only analytics client: bucketed aggregates and the on-demand
 * heatmap, for one camera and one window.
 *
 * The vocabularies below mirror `AnalyticsQueryRules` by hand, as the rest of this
 * client mirrors its server contracts. They exist so the UI offers only choices the
 * server accepts; the server remains the sole authority and refuses anything else.
 *
 * Nothing here recomputes an answer. Every number a surface shows — including the
 * non-additive ones — is transported explicitly, because a client that summed a
 * series to get a window total would count a Track once per bucket it spans.
 */

/** Bucket sizes the UI offers. The API accepts any whole second in range. */
export const BUCKET_SECONDS = [60, 300, 900, 3_600, 21_600, 86_400] as const;
export type BucketSeconds = (typeof BUCKET_SECONDS)[number];
export const DEFAULT_BUCKET_SECONDS: BucketSeconds = 900;

export const MINIMUM_BUCKET_SECONDS = 60;
export const MAXIMUM_BUCKET_SECONDS = 86_400;

/** The hard response-shape bound: the most buckets the contract will transport. */
export const MAXIMUM_BUCKETS = 512;

/** The only grid widths the heatmap accepts. */
export const GRID_WIDTHS = [16, 32, 64, 128] as const;
export type GridWidth = (typeof GRID_WIDTHS)[number];
export const DEFAULT_GRID_WIDTH: GridWidth = 64;

/** The frozen 16:9 companion height. The server sends the height; this is for layout. */
export function gridHeightFor(width: number): number {
  return Math.trunc((width * 9) / 16);
}

/**
 * The bucket count a window and size produce, half-open on `toUtc`.
 *
 * A window that is not a whole multiple of the bucket size ends in one short
 * bucket, which is a real bucket and is counted — the same ceiling rule the server
 * applies, so the UI can warn before it asks for a body the contract will refuse.
 */
export function bucketCount(fromUtc: string, toUtc: string, bucketSeconds: number): number {
  const from = Date.parse(fromUtc);
  const to = Date.parse(toUtc);
  if (!Number.isFinite(from) || !Number.isFinite(to) || bucketSeconds <= 0 || to <= from) return 0;
  return Math.ceil((to - from) / (bucketSeconds * 1_000));
}

// --- Problem codes ---------------------------------------------------------

export const ANALYTICS_QUERY_INVALID = 'analytics_query_invalid';
export const ANALYTICS_CAMERA_NOT_FOUND = 'camera_not_found';
export const ANALYTICS_BUCKET_COUNT_INVALID = 'analytics_bucket_count_invalid';
export const ANALYTICS_HEATMAP_SCOPE_TOO_LARGE = 'analytics_heatmap_scope_too_large';
export const ANALYTICS_EVIDENCE_UNREADABLE = 'analytics_evidence_unreadable';

/** The two bounded dimensions a heatmap scope can exceed. */
export const SCOPE_DIMENSIONS = {
  coveredRuns: 'coveredRuns',
  candidateTracks: 'candidateTracks',
} as const;
export type ScopeDimension = (typeof SCOPE_DIMENSIONS)[keyof typeof SCOPE_DIMENSIONS];

/**
 * Which work bound a refusal fired on, when that is what happened.
 *
 * Returns undefined for every other failure, so a caller cannot mistake an
 * unrelated error for a scope that merely needs narrowing.
 */
export function heatmapScopeRefusal(
  error: unknown,
): { dimension: ScopeDimension | null; limit: number | null } | undefined {
  if (!(error instanceof ApiError) || error.code !== ANALYTICS_HEATMAP_SCOPE_TOO_LARGE) return undefined;
  const dimension = problemText(error, 'dimension');
  return {
    dimension: dimension === SCOPE_DIMENSIONS.coveredRuns || dimension === SCOPE_DIMENSIONS.candidateTracks
      ? dimension
      : null,
    limit: problemNumber(error, 'limit') ?? null,
  };
}

// --- Response types --------------------------------------------------------

/** One bucket of the window, half-open: `[startUtc, endUtc)`. */
export type AnalyticsBucket = {
  startUtc: string;
  endUtc: string;
};

/**
 * One zone's series. Every array is exactly as long as the response's bucket list.
 *
 * The `window*` fields are not sums of the series beside them.
 * `windowUniqueTrackCount` counts a Track once for the whole window however many
 * buckets it appears in, and `peakOccupancy` is a maximum. Only entries and exits
 * are additive across disjoint buckets.
 *
 * `repeatedVisitTrackCount` is a whole-Track summary: Tracks that visited this zone
 * at least twice anywhere in their own life — deliberately not "twice in this
 * window".
 */
export type AnalyticsZoneSeries = {
  zoneId: string;
  name: string;
  entryCounts: number[];
  exitCounts: number[];
  uniqueTrackCounts: number[];
  occupancyAtStart: number[];
  peakOccupancy: number;
  peakOccupancyAtUtc: string | null;
  windowEntryCount: number;
  windowExitCount: number;
  windowUniqueTrackCount: number;
  repeatedVisitTrackCount: number;
};

export type AnalyticsLineSeries = {
  lineId: string;
  name: string;
  aToBLabel: string;
  bToALabel: string;
  aToBCounts: number[];
  bToACounts: number[];
  windowAToBCount: number;
  windowBToACount: number;
};

/** Distinct analysed Tracks of one class whose interval overlaps each bucket. */
export type AnalyticsClassSeries = {
  objectClass: TrackObjectClass;
  counts: number[];
  windowDistinctTrackCount: number;
};

/**
 * The bucketed answer.
 *
 * Disabled zones and trip lines are absent rather than present as rows of zeros:
 * they were never evaluated, and a zero row would read as an observed absence.
 */
export type AnalyticsAggregateResponse = {
  cameraId: string;
  sceneRevisionId: string | null;
  sceneRevisionNumber: number | null;
  algorithmVersion: string;
  snapshotVisibilitySequence: number;
  fromUtc: string;
  toUtc: string;
  bucketSeconds: number;
  objectClass: TrackObjectClass | null;
  coverage: AnalyticsCoverage;
  buckets: AnalyticsBucket[];
  zones: AnalyticsZoneSeries[];
  lines: AnalyticsLineSeries[];
  classes: AnalyticsClassSeries[];
};

/**
 * The trajectory-sample density map.
 *
 * `values` is row-major with exactly `gridWidth * gridHeight` entries, in
 * normalised source-frame coordinates. It is sample density — not people density
 * and not probability — and the UI is required to say so.
 */
export type AnalyticsHeatmapResponse = {
  cameraId: string;
  sceneRevisionId: string | null;
  sceneRevisionNumber: number | null;
  algorithmVersion: string;
  snapshotVisibilitySequence: number;
  fromUtc: string;
  toUtc: string;
  objectClass: TrackObjectClass | null;
  processingRunId: string | null;
  coverage: AnalyticsCoverage;
  gridWidth: number;
  gridHeight: number;
  sampleCount: number;
  trackCount: number;
  maxCellValue: number;
  values: number[];
};

// --- Requests --------------------------------------------------------------

export type AnalyticsAggregateQuery = {
  fromUtc: string;
  toUtc: string;
  bucketSeconds: number;
  objectClass?: TrackObjectClass;
};

export type AnalyticsHeatmapQuery = {
  fromUtc: string;
  toUtc: string;
  objectClass?: TrackObjectClass;
  gridWidth?: GridWidth;
  processingRunId?: string;
};

/*
 * A fixed key order, so one question always serializes to one string: the query
 * string is what identifies a cache entry, and two spellings of the same request
 * would be two entries holding the same answer.
 */
const aggregateKeys: ReadonlyArray<keyof AnalyticsAggregateQuery> = [
  'fromUtc',
  'toUtc',
  'bucketSeconds',
  'objectClass',
];

const heatmapKeys: ReadonlyArray<keyof AnalyticsHeatmapQuery> = [
  'fromUtc',
  'toUtc',
  'objectClass',
  'gridWidth',
  'processingRunId',
];

function serialize<T extends object>(query: T, keys: ReadonlyArray<keyof T>): string {
  const params = new URLSearchParams();
  for (const key of keys) {
    const value = query[key];
    if (value === undefined || value === null || value === '') continue;
    params.set(String(key), String(value));
  }
  return params.toString();
}

export function serializeAggregateQuery(query: AnalyticsAggregateQuery): string {
  return serialize(query, aggregateKeys);
}

export function serializeHeatmapQuery(query: AnalyticsHeatmapQuery): string {
  return serialize(query, heatmapKeys);
}

function route(cameraId: string, leaf: string, query: string): string {
  return `/api/cameras/${encodeURIComponent(cameraId)}/analytics/${leaf}` + (query ? '?' + query : '');
}

export function getAnalyticsAggregates(
  cameraId: string,
  query: AnalyticsAggregateQuery,
  signal?: AbortSignal,
): Promise<AnalyticsAggregateResponse> {
  return apiRequest<AnalyticsAggregateResponse>(
    route(cameraId, 'aggregates', serializeAggregateQuery(query)),
    { signal },
  );
}

export function getAnalyticsHeatmap(
  cameraId: string,
  query: AnalyticsHeatmapQuery,
  signal?: AbortSignal,
): Promise<AnalyticsHeatmapResponse> {
  return apiRequest<AnalyticsHeatmapResponse>(
    route(cameraId, 'heatmap', serializeHeatmapQuery(query)),
    { signal },
  );
}
