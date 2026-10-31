import {
  QUERY_CONTRACT_VERSION,
  type QueryContract,
  type QueryOp,
  type QueryOperation,
  type QueryUnit,
  type QueryWhere,
  type StructuredQuery,
} from '../../api/query';

/**
 * The Advanced Search builder's state and the one function that turns it into a
 * `mavi-query-v1` query (ADR-024). The builder offers only what the published
 * contract allows for the chosen unit; anything it cannot express is not offered
 * rather than sent and refused. The server still validates every query.
 */
export type BuilderState = {
  unit: QueryUnit;
  fromUtc: string;
  toUtc: string;
  cameraIds: string[];
  objectClass: '' | 'Person' | 'Vehicle';
  objectSubclass: string;
  zoneId: string;
  zoneRelation: '' | 'entered' | 'exited' | 'dwelled';
  lineId: string;
  lineDirection: '' | 'aToB' | 'bToA';
  attributes: Record<string, string>;
  plateText: string;
  plateMatch: 'contains' | 'prefix' | 'exact';
  ruleIds: string[];
  op: QueryOp;
  limit: number;
  order: 'newest' | 'oldest';
  dimension: string;
  bucketSeconds: number;
  k: number;
  baselineFromUtc: string;
  baselineToUtc: string;
};

export const BUCKET_CHOICES = [60, 300, 900, 3_600, 21_600, 86_400] as const;

export function initialBuilderState(window: { fromUtc: string; toUtc: string } | null): BuilderState {
  return {
    unit: 'track',
    fromUtc: window?.fromUtc ?? '',
    toUtc: window?.toUtc ?? '',
    cameraIds: [],
    objectClass: '',
    objectSubclass: '',
    zoneId: '',
    zoneRelation: '',
    lineId: '',
    lineDirection: '',
    attributes: {},
    plateText: '',
    plateMatch: 'contains',
    ruleIds: [],
    op: 'count',
    limit: 50,
    order: 'newest',
    dimension: '',
    bucketSeconds: 3_600,
    k: 5,
    baselineFromUtc: '',
    baselineToUtc: '',
  };
}

/** An explicit UTC instant, normalised to the canonical millisecond form, or null. */
export function canonicalUtc(value: string): string | null {
  const text = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?(Z|\+00:00)$/.test(text)) return null;
  const parsed = Date.parse(text);
  if (!Number.isFinite(parsed)) return null;
  const iso = new Date(parsed).toISOString();
  // Date.parse rolls an impossible date over (2026-02-30 becomes 2026-03-02); the instant must reproduce the date and
  // time as entered, or it is refused here as the API would refuse it, never sent as a different window.
  return iso.slice(0, 19) === text.slice(0, 19) ? iso : null;
}

/** Whether a predicate is offered for the unit, by the published contract. */
export function offers(contract: QueryContract, unit: QueryUnit, predicate: string): boolean {
  return contract.units.find((item) => item.unit === unit)?.predicates.includes(predicate) ?? false;
}

/** The dimensions an operation takes for a unit (`by` or `field`), by the published contract. */
export function dimensionsFor(contract: QueryContract, unit: QueryUnit, op: QueryOp): string[] {
  const vocabulary = contract.units.find((item) => item.unit === unit);
  if (!vocabulary) return [];
  if (op === 'groupBy' || op === 'top') return vocabulary.groupDimensions;
  if (op === 'countDistinct') return vocabulary.distinctFields;
  return [];
}

/** Geometry belongs to one camera's scene: the builder offers zones and lines only then. */
export function geometryAvailable(state: BuilderState): boolean {
  return state.cameraIds.length === 1;
}

export type BuildResult = { query: StructuredQuery; problem: null } | { query: null; problem: string };

export function buildQuery(state: BuilderState, contract: QueryContract): BuildResult {
  const fromUtc = canonicalUtc(state.fromUtc);
  const toUtc = canonicalUtc(state.toUtc);
  if (fromUtc === null || toUtc === null) {
    return { query: null, problem: 'Enter both instants in UTC, for example 2026-10-30T08:00:00Z.' };
  }
  if (Date.parse(toUtc) <= Date.parse(fromUtc)) return { query: null, problem: 'To must be after From.' };

  const where: QueryWhere = { timeWindow: { fromUtc, toUtc } };
  const unit = state.unit;
  const has = (predicate: string) => offers(contract, unit, predicate);

  if (state.cameraIds.length > 0 && has('cameraIds')) where.cameraIds = [...state.cameraIds].sort();
  if (state.objectClass && has('objectClass')) where.objectClass = state.objectClass;
  if (state.objectSubclass && has('objectSubclass')) where.objectSubclass = state.objectSubclass;

  // Zones and lines come from one camera's scene, for either unit.
  const geometry = geometryAvailable(state);
  if (state.zoneId && has('zone') && geometry) {
    where.zone = unit === 'track' && state.zoneRelation ? { zoneId: state.zoneId, relation: state.zoneRelation } : { zoneId: state.zoneId };
  }
  if (state.lineId && has('line') && geometry) {
    where.line = state.lineDirection ? { lineId: state.lineId, direction: state.lineDirection } : { lineId: state.lineId };
  }

  const attributes = Object.entries(state.attributes).filter(([, value]) => value !== '');
  if (attributes.length > 0 && has('attributes')) {
    where.attributes = attributes.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([type, value]) => ({ type, value }));
  }
  // As on Track search, attributes and a plate text are never combined: said here rather than sent and refused.
  if (where.attributes && state.plateText.trim() && has('plateText')) {
    return { query: null, problem: 'Attributes and a plate text cannot be combined; clear one of them.' };
  }
  if (state.plateText.trim() && has('plateText')) where.plateText = { text: state.plateText.trim(), match: state.plateMatch };
  if (state.ruleIds.length > 0 && has('ruleIds')) where.ruleIds = [...state.ruleIds].sort();

  const operation: QueryOperation = { op: state.op };
  // A number the contract would refuse is not sent: the builder says what is wrong instead.
  const whole = (value: number, maximum: number) => Number.isInteger(value) && value >= 1 && value <= maximum;
  if (state.op === 'find' && !whole(state.limit, contract.bounds.maximumFindLimit)) {
    return { query: null, problem: `Rows must be a whole number from 1 to ${contract.bounds.maximumFindLimit}.` };
  }
  if (state.op === 'top' && !whole(state.k, contract.bounds.maximumTopK)) {
    return { query: null, problem: `How many must be a whole number from 1 to ${contract.bounds.maximumTopK}.` };
  }
  switch (state.op) {
    case 'find':
      operation.limit = state.limit;
      operation.order = state.order;
      break;
    case 'countDistinct':
    case 'groupBy':
    case 'top': {
      const dimensions = dimensionsFor(contract, unit, state.op);
      const dimension = dimensions.includes(state.dimension) ? state.dimension : dimensions[0];
      if (!dimension) return { query: null, problem: 'This unit has no dimension for that operation.' };
      if (state.op === 'countDistinct') operation.field = dimension; else operation.by = dimension;
      if (state.op === 'top') operation.k = state.k;
      break;
    }
    case 'timeBucket':
      operation.bucketSeconds = state.bucketSeconds;
      break;
    case 'compare': {
      const baselineFrom = canonicalUtc(state.baselineFromUtc);
      const baselineTo = canonicalUtc(state.baselineToUtc);
      if (baselineFrom === null || baselineTo === null || Date.parse(baselineTo) <= Date.parse(baselineFrom)) {
        return { query: null, problem: 'Enter a baseline window in UTC, with To after From.' };
      }
      operation.baseline = { fromUtc: baselineFrom, toUtc: baselineTo };
      break;
    }
    default:
      break;
  }

  return { query: { contractVersion: QUERY_CONTRACT_VERSION, unit, where, operation }, problem: null };
}

export type LoadResult = { state: BuilderState; problem: null } | { state: null; problem: string };

/**
 * The builder state that builds exactly this query (Ask MAVI's "Open in Advanced Search", D-S10-10), or why the
 * builder cannot hold it. Nothing is dropped silently: a member the builder has no control for refuses the load, so
 * the query opened in the builder is the query that was proposed.
 */
export function stateFromQuery(query: StructuredQuery): LoadResult {
  const { where, operation } = query;
  const unsupported = (what: string): LoadResult => ({ state: null, problem: `Advanced Search cannot build ${what}; run it from Ask MAVI instead.` });
  const known = new Set(['timeWindow', 'cameraIds', 'objectClass', 'objectSubclass', 'zone', 'line', 'attributes', 'plateText', 'ruleIds', 'catalogueVersion']);
  const extra = Object.keys(where).find((key) => !known.has(key));
  if (extra) return unsupported(extra === 'minDurationMs' ? 'a minimum duration' : `the ${extra} predicate`);
  if (query.requireCompleteCoverage) return unsupported('a query that requires complete coverage');
  if (where.zone && (where.zone.minDwellMs !== undefined || where.zone.loitering !== undefined)) return unsupported('a minimum dwell or loitering');
  if ((where.zone || where.line) && (where.cameraIds?.length ?? 0) !== 1) return unsupported('a zone or line without its one camera');
  if (operation.op === 'timeBucket' && !(BUCKET_CHOICES as readonly number[]).includes(operation.bucketSeconds ?? -1)) {
    return unsupported(`buckets of ${operation.bucketSeconds} seconds`);
  }
  const attributes: Record<string, string> = {};
  for (const attribute of where.attributes ?? []) {
    if (attribute.type in attributes) return unsupported('two values of one attribute');
    attributes[attribute.type] = attribute.value;
  }
  const state: BuilderState = {
    ...initialBuilderState({ fromUtc: where.timeWindow.fromUtc, toUtc: where.timeWindow.toUtc }),
    unit: query.unit,
    cameraIds: [...(where.cameraIds ?? [])],
    objectClass: where.objectClass ?? '',
    objectSubclass: where.objectSubclass ?? '',
    zoneId: where.zone?.zoneId ?? '',
    zoneRelation: where.zone?.relation ?? '',
    lineId: where.line?.lineId ?? '',
    lineDirection: where.line?.direction ?? '',
    attributes,
    plateText: where.plateText?.text ?? '',
    plateMatch: where.plateText?.match ?? 'contains',
    ruleIds: [...(where.ruleIds ?? [])],
    op: operation.op,
    limit: operation.limit ?? 50,
    order: operation.order ?? 'newest',
    dimension: operation.by ?? operation.field ?? '',
    bucketSeconds: operation.bucketSeconds ?? 3_600,
    k: operation.k ?? 5,
    baselineFromUtc: operation.baseline?.fromUtc ?? '',
    baselineToUtc: operation.baseline?.toUtc ?? '',
  };
  return { state, problem: null };
}

/** Readable words for contract tokens; an unknown token is shown as it is. */
export function dimensionLabel(token: string): string {
  const labels: Record<string, string> = {
    camera: 'Camera',
    objectClass: 'Class',
    objectSubclass: 'Vehicle subclass',
    video: 'Video',
    rule: 'Rule',
    direction: 'Direction',
    zone: 'Zone',
    line: 'Line',
    track: 'Track',
  };
  return labels[token] ?? token;
}

export function operationLabel(op: QueryOp): string {
  const labels: Record<QueryOp, string> = {
    find: 'Find (list)',
    count: 'Count',
    countDistinct: 'Count distinct',
    groupBy: 'Group by',
    timeBucket: 'Count per time bucket',
    first: 'First',
    last: 'Last',
    top: 'Top',
    compare: 'Compare with a baseline window',
  };
  return labels[op];
}
