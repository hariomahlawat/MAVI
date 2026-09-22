import type { TrackObjectClass } from '../../api/tracks';
import type { AnalyticsCoverage } from '../../api/tracks';
import {
  bucketCount,
  DEFAULT_BUCKET_SECONDS,
  DEFAULT_GRID_WIDTH,
  MAXIMUM_BUCKETS,
  type AnalyticsAggregateResponse,
  type BucketSeconds,
  type GridWidth,
} from '../../api/analytics';

/**
 * The Analytics Workbench's question, and the pure reading of the answer.
 *
 * Everything here is a function of its arguments, so the counting rules the UI
 * depends on can be pinned by tests without a DOM. The two that matter most:
 *
 *  - a window total is never a sum of the series beside it unless the metric is
 *    genuinely additive, because a Track that spans four buckets appears in four
 *    of them and is still one Track;
 *  - an incomplete scope never yields a chart, however many zeros the server
 *    truthfully returned for the part it did evaluate.
 */

export const ANALYTICS_MODES = ['activity', 'heatmap'] as const;
export type AnalyticsMode = (typeof ANALYTICS_MODES)[number];

export const ACTIVITY_METRICS = [
  'zoneEntries',
  'zoneExits',
  'zoneUniqueTracks',
  'zoneOccupancy',
  'lineCrossings',
  'activeTracks',
] as const;
export type ActivityMetric = (typeof ACTIVITY_METRICS)[number];

/** What a metric needs selected before it means anything. */
export type MetricSubject = 'zone' | 'line' | 'none';

type MetricDescriptor = {
  label: string;
  subject: MetricSubject;
  /**
   * Whether summing the series across disjoint buckets is a true window total.
   * False for anything that counts a thing rather than an event.
   */
  additive: boolean;
  /** Exactly what is counted, in the words shown beside the chart. */
  definition: string;
  unit: string;
};

export const METRICS: Record<ActivityMetric, MetricDescriptor> = {
  zoneEntries: {
    label: 'Zone entries',
    subject: 'zone',
    additive: true,
    unit: 'entries',
    definition:
      'Each time a Track crossed into the zone, counted in the bucket holding the entry instant. '
      + 'A Track that entered, left and re-entered counts twice.',
  },
  zoneExits: {
    label: 'Zone exits',
    subject: 'zone',
    additive: true,
    unit: 'exits',
    definition:
      'Each time a Track crossed out of the zone, counted in the bucket holding the exit instant.',
  },
  zoneUniqueTracks: {
    label: 'Distinct Tracks in zone',
    subject: 'zone',
    additive: false,
    unit: 'Tracks',
    definition:
      'Distinct Tracks present in the zone at any point during each bucket. A Track counts once per '
      + 'bucket however many visits it made, so these cannot be added together: the window figure '
      + 'counts each Track once for the whole window.',
  },
  zoneOccupancy: {
    label: 'Zone occupancy',
    subject: 'zone',
    additive: false,
    unit: 'Tracks',
    definition:
      'How many Tracks were inside the zone at the instant each bucket began. This is a reading '
      + 'taken at a moment, not a total, so adding the readings together means nothing.',
  },
  lineCrossings: {
    label: 'Line crossings',
    subject: 'line',
    additive: true,
    unit: 'crossings',
    definition:
      'Each crossing of the trip line, counted in the bucket holding the crossing instant and kept '
      + 'separate by direction.',
  },
  activeTracks: {
    label: 'Active Tracks',
    subject: 'none',
    additive: false,
    unit: 'Tracks',
    definition:
      'Distinct analysed Tracks whose own interval overlaps each bucket. A Track spanning several '
      + 'buckets appears in each of them, so these cannot be added together: the window figure counts '
      + 'each Track once.',
  },
};

export const DEFAULT_METRIC: ActivityMetric = 'activeTracks';

// --- The question ----------------------------------------------------------

export type AnalyticsQueryState = {
  fromUtc: string;
  toUtc: string;
  bucketSeconds: BucketSeconds;
  objectClass: TrackObjectClass | null;
  mode: AnalyticsMode;
  metric: ActivityMetric;
  /** The zone or trip line the metric is read against, when it needs one. */
  subjectId: string | null;
  gridWidth: GridWidth;
};

export const WINDOW_PRESETS = [
  { id: 'lastHour', label: 'Last hour', seconds: 3_600, bucketSeconds: 60 },
  { id: 'last6Hours', label: 'Last 6 hours', seconds: 21_600, bucketSeconds: 300 },
  { id: 'last24Hours', label: 'Last 24 hours', seconds: 86_400, bucketSeconds: 900 },
  { id: 'last7Days', label: 'Last 7 days', seconds: 604_800, bucketSeconds: 3_600 },
] as const;

export type WindowPresetId = (typeof WINDOW_PRESETS)[number]['id'];

/**
 * A preset window ending at `nowUtc`, snapped down to a whole bucket.
 *
 * Snapping is what makes the answer stable: an unsnapped window moves every
 * second, so the same preset asked twice would be two cache entries and two
 * slightly different bucket axes for what the operator thinks is one question.
 */
export function presetWindow(presetId: WindowPresetId, nowUtc: Date): { fromUtc: string; toUtc: string; bucketSeconds: BucketSeconds } {
  const preset = WINDOW_PRESETS.find((candidate) => candidate.id === presetId) ?? WINDOW_PRESETS[2];
  const stepMs = preset.bucketSeconds * 1_000;
  const to = Math.floor(nowUtc.getTime() / stepMs) * stepMs;
  return {
    fromUtc: new Date(to - preset.seconds * 1_000).toISOString(),
    toUtc: new Date(to).toISOString(),
    bucketSeconds: preset.bucketSeconds as BucketSeconds,
  };
}

export function initialQueryState(nowUtc: Date): AnalyticsQueryState {
  const window = presetWindow('last24Hours', nowUtc);
  return {
    ...window,
    bucketSeconds: window.bucketSeconds ?? DEFAULT_BUCKET_SECONDS,
    objectClass: null,
    mode: 'activity',
    metric: DEFAULT_METRIC,
    subjectId: null,
    gridWidth: DEFAULT_GRID_WIDTH,
  };
}

/**
 * Why the window itself cannot be asked about, in the words shown to the operator.
 *
 * Both modes share this. Nothing here mentions the interval: the heatmap takes no
 * `bucketSeconds` at all, and a window it would happily answer must not be refused
 * because the interval left over from Activity would have produced too many buckets.
 */
export function windowProblem(state: Pick<AnalyticsQueryState, 'fromUtc' | 'toUtc'>): string | null {
  const from = Date.parse(state.fromUtc);
  const to = Date.parse(state.toUtc);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return 'Enter a start and end time.';
  if (to <= from) return 'The end of the window must be after its start.';
  return null;
}

/**
 * Why this window and interval together cannot be transported. Activity only.
 */
export function bucketProblem(state: Pick<AnalyticsQueryState, 'fromUtc' | 'toUtc' | 'bucketSeconds'>): string | null {
  const count = bucketCount(state.fromUtc, state.toUtc, state.bucketSeconds);
  if (count > MAXIMUM_BUCKETS) {
    return `That window and interval would produce ${count.toLocaleString()} buckets; the most that can be shown is `
      + `${MAXIMUM_BUCKETS.toLocaleString()}. Shorten the window or use a longer interval.`;
  }
  return null;
}

/** What stops the current mode's question being asked, if anything. */
export function queryProblem(
  state: Pick<AnalyticsQueryState, 'fromUtc' | 'toUtc' | 'bucketSeconds' | 'mode'>,
): string | null {
  const window = windowProblem(state);
  if (window !== null) return window;
  return state.mode === 'activity' ? bucketProblem(state) : null;
}

// --- Reading the answer ----------------------------------------------------

/**
 * Whether an answer may be drawn as an observation at all.
 *
 * A complete scope holding genuinely no facts is a real zero and is drawn as
 * one. An incomplete scope is not: the runs it did not evaluate might hold
 * anything, and an empty chart would assert they hold nothing. The two are
 * different states and the surface must render them differently.
 */
export type ScopePresence = 'observed' | 'incomplete';

export function scopePresence(coverage: AnalyticsCoverage): ScopePresence {
  return coverage.complete ? 'observed' : 'incomplete';
}

export type SeriesPoint = {
  startUtc: string;
  endUtc: string;
  value: number;
};

export type WindowFigure = {
  label: string;
  value: number;
  /** Present when the figure is a moment rather than a count over the window. */
  atUtc?: string | null;
};

export type ActivitySeries = {
  /** Named for what it counts, including its subject and direction. */
  label: string;
  points: SeriesPoint[];
};

export type ActivityReading = {
  metric: ActivityMetric;
  definition: string;
  unit: string;
  /** One series for most metrics; two for a trip line's two directions. */
  series: ActivitySeries[];
  /**
   * The window figures, taken from what the server transported. Never summed
   * from the series unless the metric is additive and the server agrees.
   */
  windowFigures: WindowFigure[];
  /** The subject's own name, or null where the metric has no subject. */
  subjectLabel: string | null;
};

function pointsFrom(response: AnalyticsAggregateResponse, counts: number[]): SeriesPoint[] {
  return response.buckets.map((bucket, index) => ({
    startUtc: bucket.startUtc,
    endUtc: bucket.endUtc,
    value: counts[index] ?? 0,
  }));
}

/**
 * The selected metric read off one response, or null when the subject it needs
 * is not in this answer.
 *
 * A missing subject is a real state rather than an empty chart: a zone that is
 * disabled in the resolved revision is absent from the response entirely, and
 * drawing zeros for it would claim it was watched and saw nothing.
 */
export function readActivity(
  response: AnalyticsAggregateResponse,
  metric: ActivityMetric,
  subjectId: string | null,
): ActivityReading | null {
  const descriptor = METRICS[metric];

  if (descriptor.subject === 'none') {
    const classes = response.classes;
    if (classes.length === 0) return null;
    return {
      metric,
      definition: descriptor.definition,
      unit: descriptor.unit,
      subjectLabel: null,
      series: classes.map((entry) => ({
        label: entry.objectClass,
        points: pointsFrom(response, entry.counts),
      })),
      windowFigures: classes.map((entry) => ({
        label: `Distinct ${entry.objectClass} Tracks`,
        value: entry.windowDistinctTrackCount,
      })),
    };
  }

  if (descriptor.subject === 'line') {
    const line = response.lines.find((candidate) => candidate.lineId === subjectId);
    if (!line) return null;
    return {
      metric,
      definition: descriptor.definition,
      unit: descriptor.unit,
      subjectLabel: line.name,
      series: [
        { label: line.aToBLabel, points: pointsFrom(response, line.aToBCounts) },
        { label: line.bToALabel, points: pointsFrom(response, line.bToACounts) },
      ],
      windowFigures: [
        { label: line.aToBLabel, value: line.windowAToBCount },
        { label: line.bToALabel, value: line.windowBToACount },
      ],
    };
  }

  const zone = response.zones.find((candidate) => candidate.zoneId === subjectId);
  if (!zone) return null;

  const counts = metric === 'zoneEntries' ? zone.entryCounts
    : metric === 'zoneExits' ? zone.exitCounts
      : metric === 'zoneUniqueTracks' ? zone.uniqueTrackCounts
        : zone.occupancyAtStart;

  const windowFigures: WindowFigure[] = metric === 'zoneEntries'
    ? [{ label: 'Entries in window', value: zone.windowEntryCount }]
    : metric === 'zoneExits'
      ? [{ label: 'Exits in window', value: zone.windowExitCount }]
      : metric === 'zoneUniqueTracks'
        ? [{ label: 'Distinct Tracks in window', value: zone.windowUniqueTrackCount }]
        : [{ label: 'Peak occupancy', value: zone.peakOccupancy, atUtc: zone.peakOccupancyAtUtc }];

  return {
    metric,
    definition: descriptor.definition,
    unit: descriptor.unit,
    subjectLabel: zone.name,
    series: [{ label: zone.name, points: pointsFrom(response, counts) }],
    windowFigures,
  };
}

/** The largest value any series reaches, which is what the axis is drawn to. */
export function readingMaximum(reading: ActivityReading): number {
  let maximum = 0;
  for (const series of reading.series) {
    for (const point of series.points) {
      if (point.value > maximum) maximum = point.value;
    }
  }
  return maximum;
}

/**
 * The subjects the operator may pick for a metric, taken from the answer rather
 * than from the scene: what is offered is what was actually evaluated.
 */
export function subjectsFor(
  response: AnalyticsAggregateResponse | undefined,
  metric: ActivityMetric,
): Array<{ id: string; label: string }> {
  if (!response) return [];
  if (METRICS[metric].subject === 'zone') {
    return response.zones.map((zone) => ({ id: zone.zoneId, label: zone.name }));
  }
  if (METRICS[metric].subject === 'line') {
    return response.lines.map((line) => ({ id: line.lineId, label: line.name }));
  }
  return [];
}

/** Keeps the selected subject valid as the metric or the answer changes. */
export function resolveSubject(
  response: AnalyticsAggregateResponse | undefined,
  metric: ActivityMetric,
  subjectId: string | null,
): string | null {
  const subjects = subjectsFor(response, metric);
  if (subjects.length === 0) return null;
  return subjects.some((subject) => subject.id === subjectId) ? subjectId : subjects[0].id;
}
