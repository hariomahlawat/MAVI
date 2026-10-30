import { apiJson, apiRequest } from './client';
import type { AnalyticsCoverage } from './tracks';

/**
 * The structured query client (ADR-024, contract `mavi-query-v1`).
 *
 * The browser composes a query only from the vocabulary the server publishes at
 * `GET /api/query/contract`, posts it whole, and renders the envelope it gets back.
 * It computes no figure of its own: counts, groups, buckets and coverage are what
 * the server transported, and a withheld answer stays withheld.
 */

export const QUERY_CONTRACT_VERSION = 'mavi-query-v1';
export const QUERY_REFUSED = 'query_refused';

export type QueryUnit = 'track' | 'event' | 'entity';
export type QueryOp =
  | 'find' | 'count' | 'countDistinct' | 'groupBy' | 'timeBucket' | 'first' | 'last' | 'top' | 'compare';

export type QueryWindow = { fromUtc: string; toUtc: string };

export type QueryWhere = {
  timeWindow: QueryWindow;
  cameraIds?: string[];
  objectClass?: 'Person' | 'Vehicle';
  objectSubclass?: string;
  minDurationMs?: number;
  minConfidence?: number;
  zone?: { zoneId: string; relation?: 'entered' | 'exited' | 'dwelled'; minDwellMs?: number; loitering?: boolean };
  line?: { lineId: string; direction?: 'aToB' | 'bToA' };
  motion?: { direction?: string; minStationaryMs?: number };
  attributes?: { type: string; value: string }[];
  plateText?: { text: string; match?: 'contains' | 'prefix' | 'exact' };
  similarTo?: { trackId: string; k?: number };
  ruleIds?: string[];
  catalogueVersion?: string;
};

export type QueryOperation = {
  op: QueryOp;
  limit?: number;
  order?: 'newest' | 'oldest';
  field?: string;
  by?: string;
  bucketSeconds?: number;
  k?: number;
  baseline?: QueryWindow;
};

export type StructuredQuery = {
  contractVersion: typeof QUERY_CONTRACT_VERSION;
  unit: QueryUnit;
  where: QueryWhere;
  operation: QueryOperation;
  requireCompleteCoverage?: boolean;
};

export type QueryUnitVocabulary = {
  unit: QueryUnit;
  dataAvailable: boolean;
  unavailableReason: string | null;
  predicates: string[];
  groupDimensions: string[];
  distinctFields: string[];
};

export type QueryContract = {
  contractVersion: string;
  units: QueryUnitVocabulary[];
  operations: QueryOp[];
  objectClasses: string[];
  objectSubclasses: string[];
  zoneRelations: string[];
  crossingDirections: string[];
  motionDirections: string[];
  plateMatches: string[];
  attributes: { type: string; objectClass: string; values: string[] }[];
  attributeDisclosure: string | null;
  eventRuleIds: string[];
  eventCatalogueVersion: string;
  bounds: {
    maximumCameraIds: number;
    defaultFindLimit: number;
    maximumFindLimit: number;
    maximumTopK: number;
    maximumSimilarK: number;
    minimumBucketSeconds: number;
    maximumBucketSeconds: number;
    maximumBuckets: number;
    maximumMatchedRecords: number;
  };
  refusalCodes: string[];
  disclosure: string;
};

export type QueryCoverageComponent = {
  kind: 'sceneAnalytics' | 'events' | 'attributes' | 'plates' | 'similarity' | 'entities' | string;
  window: 'query' | 'baseline' | string;
  complete: boolean;
  cameraId: string | null;
  sceneAnalytics: AnalyticsCoverage | null;
  derivedRuns: number | null;
  eventsPendingRuns: number | null;
  attributes: {
    tracksInScope: number;
    analysed: number;
    unavailable: number;
    notAnalysed: number;
    unknown: { type: string; value: string; tracks: number }[];
  } | null;
  plates: { vehicleTracksInScope: number; ready: number; pending: number; failed: number; stale: number; notConfigured: number } | null;
  reason: string | null;
};

export type QueryTrackRow = {
  trackId: string;
  cameraId: string;
  cameraCode: string;
  cameraName: string;
  videoAssetId: string;
  processingRunId: string;
  objectClass: string;
  objectSubclass: string | null;
  startTimestampUtc: string;
  endTimestampUtc: string;
  startOffsetMs: number;
  durationMs: number;
  meanConfidence: number;
  thumbnailArtifactId: string | null;
  similarityScore: number | null;
};

export type QueryEventRow = {
  eventId: string;
  ruleId: string;
  ruleVersion: number;
  cameraId: string;
  cameraCode: string;
  cameraName: string;
  videoAssetId: string;
  primaryTrackId: string | null;
  objectClass: string | null;
  zoneId: string | null;
  zoneName: string | null;
  lineId: string | null;
  lineName: string | null;
  direction: string | null;
  startUtc: string;
  endUtc: string;
  startOffsetMs: number;
};

/** An operator-confirmed Entity (ADR-023): its in-scope members only. A recorded operator judgement, never an identification. */
export type QueryEntityRow = {
  entityId: string;
  displayCode: string;
  entityType: 'Person' | 'Vehicle';
  firstStartUtc: string;
  lastEndUtc: string;
  cameraIds: string[];
  memberTrackIds: string[];
};

export type QueryResult = {
  kind: 'rows' | 'value' | 'groups' | 'buckets' | 'comparison' | 'withheld' | 'empty';
  tracks: QueryTrackRow[] | null;
  events: QueryEventRow[] | null;
  /** Present only for Entity rows. */
  entities?: QueryEntityRow[] | null;
  /** `totalIsLowerBound`: coverage is incomplete, so `total` counts only the analysed part ("at least"). */
  truncation: { truncated: boolean; returned: number; total: number; limit: number; totalIsLowerBound: boolean } | null;
  value: number | null;
  dimension: string | null;
  groups: { key: string | null; label: string; count: number }[] | null;
  bucketSeconds: number | null;
  buckets: { startUtc: string; endUtc: string; count: number }[] | null;
  comparison: { current: number; baseline: number; difference: number } | null;
  reason: string | null;
  message: string | null;
};

export type QueryCameraIdentity = {
  cameraId: string;
  cameraCode: string;
  cameraName: string;
  sceneRevisionId: string | null;
  sceneRevisionNumber: number | null;
  algorithmVersion: string;
};

export type QueryEnvelope = {
  contractVersion: string;
  resolvedQuery: StructuredQuery;
  queryFingerprint: string;
  unit: QueryUnit;
  operation: QueryOp;
  snapshot: { visibilitySequence: number | null; evaluatedAtUtc: string; similaritySnapshot: string | null };
  identity: {
    cameras: QueryCameraIdentity[];
    attributeIdentityFingerprint: string | null;
    attributeDisclosure: string | null;
    plateIdentityFingerprint: string | null;
    embeddingIdentityFingerprint: string | null;
    eventCatalogueVersion: string | null;
  };
  coverage: { complete: boolean; components: QueryCoverageComponent[] };
  result: QueryResult;
  disclosure: string;
};

export type QueryRefusal = { code: string; path: string; message: string };

export function getQueryContract(signal?: AbortSignal): Promise<QueryContract> {
  return apiRequest<QueryContract>('/api/query/contract', { signal });
}

export function runQuery(query: StructuredQuery, signal?: AbortSignal): Promise<QueryEnvelope> {
  return apiJson<QueryEnvelope>('/api/query', 'POST', query, signal);
}

/** The typed refusal a `query_refused` problem carries, or null for any other failure. */
export function queryRefusal(error: unknown): QueryRefusal | null {
  if (typeof error !== 'object' || error === null || !('code' in error) || (error as { code: unknown }).code !== QUERY_REFUSED) return null;
  const refusal = (error as { extensions?: Record<string, unknown> }).extensions?.refusal;
  if (typeof refusal !== 'object' || refusal === null) return null;
  const { code, path, message } = refusal as Record<string, unknown>;
  return typeof code === 'string' && typeof path === 'string' && typeof message === 'string' ? { code, path, message } : null;
}

/** Plain-language coverage gaps for one component; empty when it is complete. */
export function coverageComponentGaps(component: QueryCoverageComponent): string[] {
  if (component.complete) return [];
  const gaps: string[] = [];
  const scene = component.sceneAnalytics;
  if (scene) {
    if (scene.pendingRuns > 0) gaps.push(`${scene.pendingRuns} run(s) awaiting scene analytics`);
    if (scene.failedRuns > 0) gaps.push(`${scene.failedRuns} run(s) whose scene analytics failed`);
    if (scene.staleRuns > 0) gaps.push(`${scene.staleRuns} run(s) analysed against an older scene revision`);
    if (scene.notConfiguredRuns > 0) gaps.push(`${scene.notConfiguredRuns} run(s) on a camera with no scene configuration`);
    if (scene.disabledRuns > 0) gaps.push(`${scene.disabledRuns} run(s) with analytics switched off`);
  }
  if ((component.eventsPendingRuns ?? 0) > 0) gaps.push(`${component.eventsPendingRuns} analysed run(s) whose events are not derived yet`);
  if (component.attributes && component.attributes.notAnalysed > 0) {
    gaps.push(`${component.attributes.notAnalysed} Track(s) without a zero-shot attribute analysis yet`);
  }
  if (component.plates) {
    const plates = component.plates;
    if (plates.pending > 0) gaps.push(`${plates.pending} vehicle Track(s) awaiting plate reading`);
    if (plates.failed > 0) gaps.push(`${plates.failed} vehicle Track(s) whose plate reading failed`);
    if (plates.stale > 0) gaps.push(`${plates.stale} vehicle Track(s) read by an older plate identity`);
  }
  if (component.reason) gaps.push(reasonText(component.reason));
  return gaps.length > 0 ? gaps : ['not every part of the scope has been analysed'];
}

export function reasonText(reason: string): string {
  switch (reason) {
    case 'attributes_not_configured': return 'zero-shot attributes are not configured on this installation';
    case 'plates_not_configured': return 'plate reading is not configured on this installation';
    case 'plate_coverage_integrity_fault': return 'plate coverage could not be verified';
    case 'entity_data_unavailable': return 'no Entity exists until ReID candidates are confirmed (S7)';
    case 'operator_required': return 'Entities are shown to operators only';
    case 'operator_confirmed_membership_only': return 'Entities count only Tracks an operator confirmed, never candidates';
    case 'notConfigured': return 'similarity is not configured on this installation';
    case 'pending': return 'the Track has not been embedded yet';
    default: return reason;
  }
}
