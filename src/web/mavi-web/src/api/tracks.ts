import { apiRequest } from './client';

export type TrackObjectClass = 'Person' | 'Vehicle';

/**
 * The operator-facing vehicle subclasses (Stage 3, X1/X2): exactly what the
 * backend's exposure policy can return or accept. The backend is the authority;
 * this list only mirrors it so the filter offers nothing the server refuses.
 */
export const OBJECT_SUBCLASSES = ['car'] as const;
export type TrackObjectSubclass = (typeof OBJECT_SUBCLASSES)[number];

const OBJECT_SUBCLASS_LABELS: Record<TrackObjectSubclass, string> = { car: 'Car' };

export function objectSubclassLabel(subclass: string | undefined): string | undefined {
  return subclass !== undefined && (OBJECT_SUBCLASSES as readonly string[]).includes(subclass)
    ? OBJECT_SUBCLASS_LABELS[subclass as TrackObjectSubclass]
    : undefined;
}

/**
 * The class line a Track is shown under: the broad class, refined by the
 * subclass the server exposed (`Vehicle · Car`). The subclass never replaces
 * the class, and only a server-sent value is ever shown.
 */
export function objectClassLabel(track: { objectClass: TrackObjectClass; objectSubclass?: string }): string {
  const subclass = objectSubclassLabel(track.objectSubclass);
  return subclass ? track.objectClass + ' · ' + subclass : track.objectClass;
}

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

export const PLATE_MATCH_MODES = ['contains', 'prefix', 'exact'] as const;
export type PlateMatch = (typeof PLATE_MATCH_MODES)[number];

export type TrackSearchFilters = {
  plateText?: string;
  plateMatch?: PlateMatch;
  cameraId?: string;
  videoAssetId?: string;
  processingRunId?: string;
  objectClass?: TrackObjectClass;
  objectSubclass?: TrackObjectSubclass;
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
  /**
   * ADR-021 §4: a free-text appearance description. It ranks the base
   * candidates by text→image similarity in one page; it cannot be combined
   * with plate or analytic predicates.
   */
  appearanceQuery?: string;
  /** The opaque snapshot token of an earlier appearance response, for a stable replay. */
  appearanceSnapshot?: string;
  cursor?: string;
  limit?: number;
};

/**
 * The exact label every similarity surface carries (ADR-021 §5): results are
 * similarity candidates from a Development model, never identity or a match.
 */
export const SIMILARITY_CANDIDATES_LABEL = 'Similarity candidates — Development';

/** The appearance block of an appearance-ranked search response. */
export type AppearanceSearchBlock = {
  label: string;
  identityFingerprint: string;
  modelId: string;
  modelVersion: string;
  snapshot: string | null;
  snapshotUtc: string | null;
};

/** Scope-wide plate readiness; never treat incomplete coverage as a definitive negative. */
export type PlateCoverage = {
  identityFingerprint: string | null;
  vehicleTracksInScope: number;
  ready: number;
  pending: number;
  failed: number;
  stale: number;
  notConfigured: number;
};

export type TrackItemPlate = {
  matchedText: string;
  matchKind: PlateMatch;
  supportCount: number;
  plateObservationCount: number;
  distinctTextCount: number;
  maxConfidence: number;
  bestPlateObservationId: string;
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
  /** Present on every plate-filtered search, including empty results. */
  plateCoverage?: PlateCoverage;
  /** Present on an appearance-ranked search (`appearanceQuery`). */
  appearance?: AppearanceSearchBlock;
};

export type TrackSearchItem = {
  id: string;
  processingRunId: string;
  videoAssetId: string;
  cameraId: string;
  cameraCode: string;
  cameraName: string;
  objectClass: TrackObjectClass;
  /** Present only when the server exposes the Track's subclass (X1: `car`). */
  objectSubclass?: TrackObjectSubclass;
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
  /** The reading that matched the plate predicate, not a verified registration. */
  plate?: TrackItemPlate;
  /** Cosine similarity in [-1, 1] on an appearance-ranked search; a score, never a verdict. */
  appearanceScore?: number;
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

/**
 * The closed Evidence Set role vocabulary, in canonical order (S1.3 plan §4.1,
 * §7.1). Wire values are case-sensitive and match the persisted domain roles.
 */
export const TRACK_EVIDENCE_ROLES = [
  'Representative',
  'NearView',
  'EarlyDiverse',
  'LateDiverse',
] as const;

export type TrackEvidenceRole = (typeof TRACK_EVIDENCE_ROLES)[number];

/**
 * One accepted Observation of a Track's Evidence Set. `evidenceContentUrl` is
 * server-authored; nothing in the web builds an artifact URL from
 * `evidenceArtifactId`.
 */
export type TrackEvidenceObservation = {
  observationId: string;
  evidenceRole: TrackEvidenceRole;
  evidenceRank: number;
  sourceFrameNumber: number;
  videoOffsetMs: number;
  timestampUtc: string;
  confidence: number;
  qualityScore: number;
  selectionScore: number;
  boundingBox: TrackBoundingBox;
  evidenceArtifactId: string | null;
  evidenceContentUrl: string | null;
};

/**
 * The wire's compatibility Representative. The server derives it from
 * `observations[0]`; the web reads the Representative only from there, through
 * `representativeObservation` (S1.3 plan §8.1), and never from this object.
 */
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

export type TrackPlateReading = {
  rank: number;
  rawText: string;
  rawLineCount: number;
  normalisedText?: string;
  normalisationOutcome: 'ok' | 'rejected';
  confidence: number;
  formatClass?: string;
};

export type TrackPlateObservation = {
  plateObservationId: string;
  sourceObservationId: string;
  role: TrackEvidenceRole;
  offsetMs: number;
  sourceFrameNumber: number;
  timestampUtc: string;
  box: { x: number; y: number; width: number; height: number; cropWidth: number; cropHeight: number };
  detectorConfidence: number;
  outcome: 'Read' | 'Unreadable';
  readings: TrackPlateReading[];
};

export type TrackPlates = {
  readiness: 'Pending' | 'Ready' | 'Failed' | 'Stale' | 'NotConfigured';
  trackOutcome?: 'Analysed' | 'Unavailable';
  unavailableReason?: string;
  agreement?: 'none' | 'single' | 'consistent' | 'conflicting';
  texts: Array<{ normalisedText: string; supportCount: number; maxConfidence: number; bestPlateObservationId: string }>;
  observations: TrackPlateObservation[];
  provenance?: {
    analysisId: string;
    plateDetectorModelPackId: string;
    ocrModelPackId: string;
    normalisation: { id: string; sha256: string };
    summaryPolicy: { id: string; version: string; sha256: string };
    completedAtUtc: string;
  };
};

export type TrackDetail = {
  id: string;
  processingRunId: string;
  videoAssetId: string;
  camera: TrackCamera;
  objectClass: TrackObjectClass;
  /** Present only when the server exposes the Track's subclass (X1: `car`). */
  objectSubclass?: TrackObjectSubclass;
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
  /** Compatibility only. No feature code reads it: see `TrackRepresentative`. */
  representative: TrackRepresentative | null;
  /**
   * The Track's Evidence Set: at most four accepted Observations in
   * `evidenceRank` order, rank 0 the Representative. Empty for a legacy Track
   * with no Representative. The authoritative Track evidence on the read side.
   */
  observations: TrackEvidenceObservation[];
  trajectoryArtifactId: string | null;
  trajectoryContentUrl: string | null;
  analytics: TrackDetailAnalytics;
  /** Vehicle Track only; omitted for Person. */
  plates?: TrackPlates;
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
  'objectSubclass',
  'plateText',
  'plateMatch',
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
  'appearanceQuery',
  'appearanceSnapshot',
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

/** `GET /api/tracks/{id}/similar` (ADR-021 §4). */
export type SimilarTracksState = 'ready' | 'pending' | 'unavailable' | 'notConfigured' | 'notAnalysed' | 'failed';

export type SimilarityUnavailableReason = 'evidence_too_small' | 'no_evidence' | 'evidence_unavailable';

export type EmbeddingIdentity = {
  fingerprint: string;
  modelId: string;
  modelVersion: string;
};

export type SimilarTrackCandidate = {
  rank: number;
  /** Cosine similarity in [-1, 1]. A ranking score, never a match probability. */
  score: number;
  sourceObservationId: string | null;
  track: TrackSearchItem;
};

export type SimilarTracksResponse = {
  state: SimilarTracksState;
  /** Set when `state` is `unavailable`; an open string so a new reason degrades to a generic sentence. */
  reason: SimilarityUnavailableReason | (string & {}) | null;
  label: string;
  queryTrackId: string;
  identity: EmbeddingIdentity | null;
  snapshot: string | null;
  snapshotUtc: string | null;
  candidates: SimilarTrackCandidate[];
};

export const SIMILAR_TRACKS_K_MAX = 50;
export const SIMILAR_TRACKS_K_DEFAULT = 20;

export type SimilarTracksParams = {
  k?: number;
  cameraId?: string;
  fromUtc?: string;
  toUtc?: string;
  objectClass?: TrackObjectClass;
  /** The opaque token of an earlier response; replays its ranked list unchanged. */
  snapshot?: string;
};

const similarParamKeys: ReadonlyArray<keyof SimilarTracksParams> = ['k', 'cameraId', 'fromUtc', 'toUtc', 'objectClass', 'snapshot'];

export function serializeSimilarTracksParams(params: SimilarTracksParams): string {
  const query = new URLSearchParams();
  for (const key of similarParamKeys) {
    const value = params[key];
    if (value === undefined || value === null || value === '') continue;
    query.set(key, String(value));
  }
  return query.toString();
}

export function getSimilarTracks(trackId: string, params: SimilarTracksParams = {}, signal?: AbortSignal): Promise<SimilarTracksResponse> {
  const query = serializeSimilarTracksParams(params);
  return apiRequest<SimilarTracksResponse>(
    '/api/tracks/' + encodeURIComponent(trackId) + '/similar' + (query ? '?' + query : ''),
    { signal },
  );
}
