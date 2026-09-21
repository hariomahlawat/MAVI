import { apiRequest } from './client';

export type TrackObjectClass = 'Person' | 'Vehicle';

/**
 * The analytic query grammar frozen in plan §S, mirrored by hand as the rest of
 * this client mirrors its server contracts (`TrackSearchContractRules`).
 * Values are sent case-sensitively, exactly as listed; the backend is the
 * authority on every dependency between keys and refuses what it does not accept.
 */
export const ZONE_RELATIONS = ['entered', 'exited', 'dwelled'] as const;
export type ZoneRelation = (typeof ZONE_RELATIONS)[number];
export const DEFAULT_ZONE_RELATION: ZoneRelation = 'dwelled';

export const CROSSING_DIRECTIONS = ['aToB', 'bToA'] as const;
export type CrossingDirection = (typeof CROSSING_DIRECTIONS)[number];

/** Screen headings: north is decreasing y. Never compass bearings. */
export const MOTION_DIRECTIONS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const;
export type MotionDirection = (typeof MOTION_DIRECTIONS)[number];

/** The frozen engine version shape, `scene-analytics-v<major>`. */
export const ALGORITHM_VERSION_PATTERN = /^scene-analytics-v[1-9]\d{0,3}$/;

export type TrackSearchFilters = {
  cameraId?: string;
  videoAssetId?: string;
  processingRunId?: string;
  objectClass?: TrackObjectClass;
  fromUtc?: string;
  toUtc?: string;
  minimumDurationMs?: number;
  minimumConfidence?: number;
  sceneRevisionId?: string;
  analyticsAlgorithmVersion?: string;
  zoneId?: string;
  zoneRelation?: ZoneRelation;
  minDwellMs?: number;
  lineId?: string;
  crossingDirection?: CrossingDirection;
  motionDirection?: MotionDirection;
  minStationaryMs?: number;
  loitering?: true;
  cursor?: string;
  limit?: number;
};

/** The §H coverage block: how much of the search scope analytics actually evaluated. */
export type AnalyticsCoverage = {
  sceneRevisionId: string | null;
  algorithmVersion: string;
  evaluatedRuns: number;
  pendingRuns: number;
  failedRuns: number;
  notConfiguredRuns: number;
  disabledRuns: number;
  staleRuns: number;
  analysedTracks: number;
  unavailableTracks: number;
  complete: boolean;
};

export type TrackItemZoneAnalytics = {
  zoneId: string;
  visitCount: number;
  totalDwellMs: number;
  loitering: boolean;
};

export type TrackItemLineAnalytics = {
  lineId: string;
  crossingCount: number;
  matchedDirection: CrossingDirection | null;
  firstMatchedCrossingUtc: string | null;
};

export type TrackItemMotionAnalytics = {
  heading: string;
  longestStationaryMs: number;
};

/** Why a row matched an analytic search, bounded to what was asked about. */
export type TrackItemAnalytics = {
  sceneRevisionId: string;
  algorithmVersion: string;
  zones: TrackItemZoneAnalytics[];
  lines: TrackItemLineAnalytics[];
  motion: TrackItemMotionAnalytics | null;
};

export type TrackSearchResponse = {
  items: TrackSearchItem[];
  nextCursor: string | null;
  /** Present only for an analytics-dependent search. */
  analyticsCoverage?: AnalyticsCoverage;
};

export type TrackSearchItem = {
  id: string;
  processingRunId: string;
  videoAssetId: string;
  cameraId: string;
  cameraCode: string;
  cameraName: string;
  objectClass: TrackObjectClass;
  startTimestampUtc: string;
  endTimestampUtc: string;
  startOffsetMs: number;
  endOffsetMs: number;
  durationMs: number;
  detectionCount: number;
  meanConfidence: number;
  maxConfidence: number;
  reviewStatus: string;
  thumbnailArtifactId: string | null;
  thumbnailContentUrl: string | null;
  videoContentUrl: string;
  /** Present only for an analytics-dependent search. */
  analytics?: TrackItemAnalytics;
};

export type TrackCamera = {
  id: string;
  code: string;
  name: string;
};

export type TrackProcessing = {
  pipelineVersion: string;
  detectorName: string | null;
  detectorVersion: string | null;
  trackerName: string | null;
  trackerVersion: string | null;
  completedAtUtc: string;
};

export type TrackVideo = {
  recordingStartUtc: string;
  recordingEndUtc: string;
  durationMs: number;
  width: number;
  height: number;
  frameRateNumerator: number;
  frameRateDenominator: number;
  videoContentUrl: string;
};

export type TrackBoundingBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type TrackRepresentative = {
  observationId: string;
  sourceFrameNumber: number;
  videoOffsetMs: number;
  timestampUtc: string;
  confidence: number;
  qualityScore: number;
  boundingBox: TrackBoundingBox;
  thumbnailArtifactId: string | null;
  thumbnailContentUrl: string | null;
};

/** The per-Track analytics status vocabulary: two outcome kinds plus the readiness words. */
export type TrackAnalyticsStatus = 'Analysed' | 'Unavailable' | 'Pending' | 'Failed' | 'Stale' | 'NotConfigured' | 'Disabled';

export type TrackDetailZoneSummary = {
  zoneId: string;
  visitCount: number;
  totalDwellMs: number;
  firstEntryTimestampUtc: string | null;
  lastExitTimestampUtc: string | null;
  loitering: boolean;
  loiteringThresholdSeconds: number;
  loiteringDwellMs: number;
};

export type TrackDetailZoneVisit = {
  zoneId: string;
  visitIndex: number;
  entryOffsetMs: number;
  exitOffsetMs: number;
  entryTimestampUtc: string;
  exitTimestampUtc: string;
  dwellMs: number;
  beganInside: boolean;
  endedInside: boolean;
  closedByGap: boolean;
  entryHeading: string;
  exitHeading: string;
};

export type TrackDetailLineCrossing = {
  lineId: string;
  crossingIndex: number;
  offsetMs: number;
  timestampUtc: string;
  direction: CrossingDirection;
  pointX: number;
  pointY: number;
};

export type TrackDetailMotionSummary = {
  heading: string;
  pathLengthNormalised: number;
  meanDisplacementRate: number;
  longestStationaryMs: number;
  totalStationaryMs: number;
  stationaryIntervals: { startOffsetMs: number; endOffsetMs: number }[];
  stationaryZoneIds: string[];
};

export type TrackAnalyticsIdentitySummary = {
  sceneRevisionId: string;
  sceneRevisionNumber: number;
  algorithmVersion: string;
  unitStatus: string;
  outcome: string;
};

/** Everything analytics knows about one Track for one identity. Facts only when `Analysed`. */
export type TrackDetailAnalytics = {
  sceneRevisionId: string | null;
  sceneRevisionNumber: number | null;
  algorithmVersion: string;
  status: TrackAnalyticsStatus;
  unavailableReason: string | null;
  referencePoint: string | null;
  sampleCount: number | null;
  gapCount: number | null;
  gapTotalMs: number | null;
  zoneSummaries: TrackDetailZoneSummary[];
  zoneVisits: TrackDetailZoneVisit[];
  lineCrossings: TrackDetailLineCrossing[];
  motion: TrackDetailMotionSummary | null;
  otherIdentities: TrackAnalyticsIdentitySummary[];
};

/** Which analytic identity a detail should be read against; both absent means the current one. */
export type TrackAnalyticsIdentity = {
  sceneRevisionId?: string;
  analyticsAlgorithmVersion?: string;
};

export type TrackDetail = {
  id: string;
  processingRunId: string;
  videoAssetId: string;
  camera: TrackCamera;
  objectClass: TrackObjectClass;
  localTrackNumber: number;
  startOffsetMs: number;
  endOffsetMs: number;
  startTimestampUtc: string;
  endTimestampUtc: string;
  durationMs: number;
  detectionCount: number;
  meanConfidence: number;
  maxConfidence: number;
  reviewStatus: string;
  processing: TrackProcessing;
  video: TrackVideo;
  representative: TrackRepresentative | null;
  trajectoryArtifactId: string | null;
  trajectoryContentUrl: string | null;
  analytics: TrackDetailAnalytics;
};

export function serializePlainDecimal(value: number): string {
  if (!Number.isFinite(value)) return String(value);

  const raw = String(value).toLowerCase();
  if (!raw.includes('e')) return raw;

  const [mantissa, exponentText] = raw.split('e');
  const exponent = Number(exponentText);
  const sign = mantissa.startsWith('-') ? '-' : '';
  const unsignedMantissa = sign ? mantissa.slice(1) : mantissa;
  const [integerPart, fractionalPart = ''] = unsignedMantissa.split('.');
  const digits = integerPart + fractionalPart;
  const decimalPosition = integerPart.length + exponent;

  let expanded: string;
  if (decimalPosition <= 0) {
    expanded = '0.' + '0'.repeat(-decimalPosition) + digits;
  } else if (decimalPosition >= digits.length) {
    expanded = digits + '0'.repeat(decimalPosition - digits.length);
  } else {
    expanded = digits.slice(0, decimalPosition) + '.' + digits.slice(decimalPosition);
  }

  const [expandedInteger, expandedFraction = ''] = expanded.split('.');
  const normalizedInteger = expandedInteger.replace(/^0+(?=\d)/, '') || '0';
  const normalizedFraction = expandedFraction.replace(/0+$/, '');
  return sign + normalizedInteger + (normalizedFraction ? '.' + normalizedFraction : '');
}

const orderedFilterKeys: ReadonlyArray<keyof TrackSearchFilters> = [
  'cameraId',
  'videoAssetId',
  'processingRunId',
  'objectClass',
  'fromUtc',
  'toUtc',
  'minimumDurationMs',
  'minimumConfidence',
  'sceneRevisionId',
  'analyticsAlgorithmVersion',
  'zoneId',
  'zoneRelation',
  'minDwellMs',
  'lineId',
  'crossingDirection',
  'motionDirection',
  'minStationaryMs',
  'loitering',
  'cursor',
  'limit',
];

export function serializeTrackSearchFilters(filters: TrackSearchFilters): string {
  const params = new URLSearchParams();
  for (const key of orderedFilterKeys) {
    const value = filters[key];
    if (value === undefined || value === null || value === '') continue;
    params.set(key, key === 'minimumConfidence' ? serializePlainDecimal(value as number) : String(value));
  }
  return params.toString();
}

export function searchTracks(filters: TrackSearchFilters, signal?: AbortSignal): Promise<TrackSearchResponse> {
  const query = serializeTrackSearchFilters(filters);
  const path = '/api/tracks' + (query ? '?' + query : '');
  return apiRequest<TrackSearchResponse>(path, { signal });
}

export function getTrack(trackId: string, signal?: AbortSignal, identity?: TrackAnalyticsIdentity): Promise<TrackDetail> {
  const params = new URLSearchParams();
  if (identity?.sceneRevisionId) params.set('sceneRevisionId', identity.sceneRevisionId);
  if (identity?.analyticsAlgorithmVersion) params.set('analyticsAlgorithmVersion', identity.analyticsAlgorithmVersion);
  const query = params.toString();
  return apiRequest<TrackDetail>('/api/tracks/' + encodeURIComponent(trackId) + (query ? '?' + query : ''), { signal });
}
