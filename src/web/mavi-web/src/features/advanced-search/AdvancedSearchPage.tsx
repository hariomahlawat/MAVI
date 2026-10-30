import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import {
  coverageComponentGaps,
  getQueryContract,
  queryRefusal,
  reasonText,
  runQuery,
  type QueryCameraIdentity,
  type QueryContract,
  type QueryEnvelope,
  type QueryEventRow,
  type QueryOp,
  type QueryTrackRow,
  type QueryUnit,
  type StructuredQuery,
} from '../../api/query';
import { getCameraScene } from '../../api/scene';
import { getSystemConfig } from '../../api/system';
import { listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import EmptyState from '../../shared/components/EmptyState';
import Panel from '../../shared/components/Panel';
import { displayTimestamp, formatOffset } from '../../shared/format/format';
import { recordingsWindow } from '../events/EventsPage';
import {
  BUCKET_CHOICES,
  buildQuery,
  dimensionLabel,
  dimensionsFor,
  geometryAvailable,
  initialBuilderState,
  offers,
  operationLabel,
  type BuilderState,
} from './queryBuilder';

const UNIT_LABELS: Record<QueryUnit, string> = { track: 'Tracks', event: 'Events', entity: 'Entities' };

/**
 * Advanced Search (Stage 8; ADR-024; register C8.2).
 *
 * A builder over the structured query contract: it offers only the predicates,
 * operations and dimensions the server publishes for the chosen unit, shows the
 * query exactly as the server resolved it, and renders the envelope — a table, a
 * count, grouped bars or time buckets — with drill-through to the Tracks and
 * Events behind every row. A figure the coverage does not support is withheld,
 * never drawn as zero.
 */
export default function AdvancedSearchPage() {
  const contract = useQuery({ queryKey: ['query-contract'], queryFn: ({ signal }) => getQueryContract(signal), staleTime: Infinity });
  const cameras = useQuery({ queryKey: queryKeys.cameras, queryFn: ({ signal }) => listCameras(signal) });
  const videos = useQuery({ queryKey: queryKeys.videos, queryFn: ({ signal }) => listVideos(signal) });
  const systemConfig = useQuery({ queryKey: queryKeys.systemConfig, queryFn: ({ signal }) => getSystemConfig(signal), staleTime: 60_000 });
  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId ?? undefined;

  const defaultWindow = useMemo(() => recordingsWindow(videos.data ?? []), [videos.data]);
  const [state, setState] = useState<BuilderState>(() => initialBuilderState(null));
  useEffect(() => {
    if (defaultWindow && state.fromUtc === '' && state.toUtc === '') {
      setState((current) => ({ ...current, fromUtc: defaultWindow.fromUtc, toUtc: defaultWindow.toUtc }));
    }
  }, [defaultWindow, state.fromUtc, state.toUtc]);

  const sceneCameraId = geometryAvailable(state) ? state.cameraIds[0] : '';
  const scene = useQuery({
    queryKey: queryKeys.cameraScene(sceneCameraId),
    queryFn: ({ signal }) => getCameraScene(sceneCameraId, signal),
    enabled: sceneCameraId !== '',
  });

  const run = useMutation({ mutationFn: (query: StructuredQuery) => runQuery(query) });
  const update = (patch: Partial<BuilderState>) => setState((current) => ({ ...current, ...patch }));

  if (contract.isError) {
    return <EmptyState title="Advanced Search is unavailable">The query contract could not be read. Try again.</EmptyState>;
  }
  if (!contract.data) return <p className="query-page__muted" role="status">Loading the query contract…</p>;

  const vocabulary = contract.data;
  const built = buildQuery(state, vocabulary);
  const has = (predicate: string) => offers(vocabulary, state.unit, predicate);
  const dimensions = dimensionsFor(vocabulary, state.unit, state.op);
  const unitInfo = vocabulary.units.find((item) => item.unit === state.unit);
  const zones = scene.data?.activeRevision?.zones.filter((zone) => zone.enabled) ?? [];
  const lines = scene.data?.activeRevision?.tripLines.filter((line) => line.enabled) ?? [];
  // Attributes apply to one class: they are offered once a class is chosen, so a mix the server refuses is never built.
  const attributeTypes = vocabulary.attributes.filter((attribute) => attribute.objectClass === state.objectClass);

  const setUnit = (unit: QueryUnit) => {
    // Predicates the new unit does not take are cleared, so nothing hidden is ever sent.
    setState((current) => ({
      ...initialBuilderState({ fromUtc: current.fromUtc, toUtc: current.toUtc }),
      unit,
      cameraIds: current.cameraIds,
      objectClass: unit === 'entity' ? '' : current.objectClass,
      op: current.op,
    }));
    run.reset();
  };

  return (
    <div className="query-page">
      <header className="query-page__header">
        <h1>Advanced Search</h1>
        <p className="query-page__disclosure">
          Structured queries over contract <strong>{vocabulary.contractVersion}</strong>: only what the contract allows can be
          asked, and every answer states its scope, identity and coverage. {vocabulary.disclosure}
        </p>
      </header>

      <Panel title="Query">
        <form
          className="query-page__builder"
          onSubmit={(event) => {
            event.preventDefault();
            if (built.query) run.mutate(built.query);
          }}
        >
          <fieldset className="query-page__group">
            <legend>Unit</legend>
            {vocabulary.units.map((unit) => (
              <label key={unit.unit}>
                <input type="radio" name="unit" checked={state.unit === unit.unit} onChange={() => setUnit(unit.unit)} />
                {UNIT_LABELS[unit.unit]}
                {unit.dataAvailable ? null : <span className="query-page__reason"> — {reasonText(unit.unavailableReason ?? '')}</span>}
              </label>
            ))}
          </fieldset>

          <fieldset className="query-page__group">
            <legend>Window (UTC)</legend>
            <label>
              From
              <input aria-label="From (UTC)" value={state.fromUtc} onChange={(event) => update({ fromUtc: event.target.value })} />
            </label>
            <label>
              To
              <input aria-label="To (UTC)" value={state.toUtc} onChange={(event) => update({ toUtc: event.target.value })} />
            </label>
            {defaultWindow ? (
              <button
                type="button"
                className="button button--ghost button--md"
                onClick={() => update({ fromUtc: defaultWindow.fromUtc, toUtc: defaultWindow.toUtc })}
              >
                Fit to recordings
              </button>
            ) : null}
          </fieldset>

          <fieldset className="query-page__group">
            <legend>Cameras (none selected means every camera)</legend>
            <div className="query-page__cameras">
              {(cameras.data ?? []).map((camera) => (
                <label key={camera.id}>
                  <input
                    type="checkbox"
                    checked={state.cameraIds.includes(camera.id.toLowerCase())}
                    onChange={(event) => {
                      const id = camera.id.toLowerCase();
                      const next = event.target.checked ? [...state.cameraIds, id] : state.cameraIds.filter((item) => item !== id);
                      // Geometry belongs to one camera; a different selection forgets it.
                      update({ cameraIds: next, zoneId: '', lineId: '', lineDirection: '', zoneRelation: '' });
                    }}
                  />
                  {camera.code} · {camera.name}
                </label>
              ))}
            </div>
          </fieldset>

          {state.unit !== 'entity' ? (
            <fieldset className="query-page__group">
              <legend>Filters</legend>
              {has('objectClass') ? (
                <label>
                  Class
                  <select
                    aria-label="Class"
                    value={state.objectClass}
                    onChange={(event) => {
                      const objectClass = event.target.value as BuilderState['objectClass'];
                      // A class change clears what the new class hides: attributes of the other class, a vehicle subclass and,
                      // for Person, a plate text. Nothing hidden is ever sent.
                      update({ objectClass, attributes: {}, objectSubclass: '', plateText: objectClass === 'Person' ? '' : state.plateText });
                    }}
                  >
                    <option value="">Any</option>
                    {vocabulary.objectClasses.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>
              ) : null}
              {has('objectSubclass') && state.objectClass !== 'Person' ? (
                <label>
                  Vehicle subclass
                  <select aria-label="Vehicle subclass" value={state.objectSubclass} onChange={(event) => update({ objectSubclass: event.target.value })}>
                    <option value="">Any</option>
                    {vocabulary.objectSubclasses.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>
              ) : null}
              {has('zone') || has('line') ? (
                geometryAvailable(state) ? (
                  <>
                    {has('zone') ? (
                      <label>
                        Zone
                        <select aria-label="Zone" value={state.zoneId} onChange={(event) => update({ zoneId: event.target.value })}>
                          <option value="">Any</option>
                          {zones.map((zone) => <option key={zone.zoneId} value={zone.zoneId}>{zone.name}</option>)}
                        </select>
                      </label>
                    ) : null}
                    {state.unit === 'track' && state.zoneId ? (
                      <label>
                        Zone relation
                        <select aria-label="Zone relation" value={state.zoneRelation} onChange={(event) => update({ zoneRelation: event.target.value as BuilderState['zoneRelation'] })}>
                          <option value="">Dwelled (default)</option>
                          <option value="entered">Entered</option>
                          <option value="exited">Exited</option>
                        </select>
                      </label>
                    ) : null}
                    {has('line') ? (
                      <label>
                        Line
                        <select aria-label="Line" value={state.lineId} onChange={(event) => update({ lineId: event.target.value, lineDirection: '' })}>
                          <option value="">Any</option>
                          {lines.map((line) => <option key={line.lineId} value={line.lineId}>{line.name}</option>)}
                        </select>
                      </label>
                    ) : null}
                    {state.lineId ? (
                      <label>
                        Direction
                        <select aria-label="Direction" value={state.lineDirection} onChange={(event) => update({ lineDirection: event.target.value as BuilderState['lineDirection'] })}>
                          <option value="">Either</option>
                          <option value="aToB">{lines.find((line) => line.lineId === state.lineId)?.aToBLabel ?? 'A → B'}</option>
                          <option value="bToA">{lines.find((line) => line.lineId === state.lineId)?.bToALabel ?? 'B → A'}</option>
                        </select>
                      </label>
                    ) : null}
                  </>
                ) : (
                  <p className="query-page__muted">Select exactly one camera to filter by its zones and lines.</p>
                )
              ) : null}
              {has('plateText') && state.objectClass !== 'Person' ? (
                <label>
                  Plate text
                  <input aria-label="Plate text" value={state.plateText} onChange={(event) => update({ plateText: event.target.value })} />
                  <select aria-label="Plate match" value={state.plateMatch} onChange={(event) => update({ plateMatch: event.target.value as BuilderState['plateMatch'] })}>
                    {vocabulary.plateMatches.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>
              ) : null}
              {has('ruleIds') ? (
                <div className="query-page__rules" role="group" aria-label="Rules">
                  {vocabulary.eventRuleIds.map((ruleId) => (
                    <label key={ruleId}>
                      <input
                        type="checkbox"
                        checked={state.ruleIds.includes(ruleId)}
                        onChange={(event) => update({
                          ruleIds: event.target.checked ? [...state.ruleIds, ruleId] : state.ruleIds.filter((item) => item !== ruleId),
                        })}
                      />
                      {ruleId}
                    </label>
                  ))}
                </div>
              ) : null}
              {has('attributes') && state.objectClass === '' && vocabulary.attributes.length > 0 ? (
                <p className="query-page__muted">Choose a class to filter by its zero-shot attributes.</p>
              ) : null}
              {has('attributes') && state.objectClass !== '' && attributeTypes.length > 0 ? (
                <div className="query-page__attributes" role="group" aria-label="Attributes">
                  <p className="query-page__muted">Attributes are zero-shot, uncalibrated, Development: Unknown is not counted either way.</p>
                  {attributeTypes.map((attribute) => (
                    <label key={attribute.type}>
                      {attribute.type}
                      <select
                        aria-label={`Attribute ${attribute.type}`}
                        value={state.attributes[attribute.type] ?? ''}
                        onChange={(event) => update({ attributes: { ...state.attributes, [attribute.type]: event.target.value } })}
                      >
                        <option value="">Any</option>
                        {attribute.values.map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    </label>
                  ))}
                </div>
              ) : null}
            </fieldset>
          ) : null}

          <fieldset className="query-page__group">
            <legend>Operation</legend>
            <label>
              Operation
              <select aria-label="Operation" value={state.op} onChange={(event) => update({ op: event.target.value as QueryOp, dimension: '' })}>
                {vocabulary.operations.map((op) => <option key={op} value={op}>{operationLabel(op)}</option>)}
              </select>
            </label>
            {dimensions.length > 0 ? (
              <label>
                {state.op === 'countDistinct' ? 'Distinct' : 'By'}
                <select aria-label="Dimension" value={dimensions.includes(state.dimension) ? state.dimension : dimensions[0]} onChange={(event) => update({ dimension: event.target.value })}>
                  {dimensions.map((value) => <option key={value} value={value}>{dimensionLabel(value)}</option>)}
                </select>
              </label>
            ) : null}
            {state.op === 'top' ? (
              <label>
                How many
                <input aria-label="How many" type="number" min={1} max={vocabulary.bounds.maximumTopK} value={state.k} onChange={(event) => update({ k: Number(event.target.value) })} />
              </label>
            ) : null}
            {state.op === 'find' ? (
              <>
                <label>
                  Rows
                  <input aria-label="Rows" type="number" min={1} max={vocabulary.bounds.maximumFindLimit} value={state.limit} onChange={(event) => update({ limit: Number(event.target.value) })} />
                </label>
                <label>
                  Order
                  <select aria-label="Order" value={state.order} onChange={(event) => update({ order: event.target.value as BuilderState['order'] })}>
                    <option value="newest">Newest first</option>
                    <option value="oldest">Oldest first</option>
                  </select>
                </label>
              </>
            ) : null}
            {state.op === 'timeBucket' ? (
              <label>
                Bucket
                <select aria-label="Bucket" value={state.bucketSeconds} onChange={(event) => update({ bucketSeconds: Number(event.target.value) })}>
                  {BUCKET_CHOICES.map((value) => <option key={value} value={value}>{value >= 3_600 ? `${value / 3_600} h` : `${value / 60} min`}</option>)}
                </select>
              </label>
            ) : null}
            {state.op === 'compare' ? (
              <>
                <label>
                  Baseline from (UTC)
                  <input aria-label="Baseline from (UTC)" value={state.baselineFromUtc} onChange={(event) => update({ baselineFromUtc: event.target.value })} />
                </label>
                <label>
                  Baseline to (UTC)
                  <input aria-label="Baseline to (UTC)" value={state.baselineToUtc} onChange={(event) => update({ baselineToUtc: event.target.value })} />
                </label>
              </>
            ) : null}
          </fieldset>

          <div className="query-page__actions">
            <button type="submit" className="button button--primary button--md" disabled={built.query === null || run.isPending}>
              {run.isPending ? 'Running…' : 'Run query'}
            </button>
            {built.problem ? <p className="query-page__muted" role="status">{built.problem}</p> : null}
            {unitInfo && !unitInfo.dataAvailable ? (
              <p className="query-page__muted">This unit is defined in the contract and has no data yet.</p>
            ) : null}
          </div>
        </form>
      </Panel>

      {run.isError ? <Refusal error={run.error} /> : null}
      {run.data ? <Answer envelope={run.data} contract={vocabulary} displayTimeZoneId={displayTimeZoneId} /> : null}
    </div>
  );
}

function Refusal({ error }: { error: unknown }) {
  const refusal = queryRefusal(error);
  if (refusal === null) {
    return <EmptyState title="The query could not be run">The server could not be reached or failed. Try again.</EmptyState>;
  }
  return (
    <div className="query-page__refusal" role="alert">
      <strong>Refused: {refusal.code}</strong>
      <p>{refusal.message}</p>
      {refusal.path ? <p className="query-page__muted">At <code>{refusal.path}</code></p> : null}
    </div>
  );
}

function Answer({
  envelope,
  contract,
  displayTimeZoneId,
}: {
  envelope: QueryEnvelope;
  contract: QueryContract;
  displayTimeZoneId: string | undefined;
}) {
  return (
    <>
      <CoverageStatus envelope={envelope} />

      <Panel title="Answer">
        <Result envelope={envelope} displayTimeZoneId={displayTimeZoneId} />
      </Panel>

      <Panel title="Interpreted as">
        <p className="query-page__muted">
          The query exactly as the server resolved it (defaults stated, sets sorted). Fingerprint{' '}
          <code title={envelope.queryFingerprint}>{envelope.queryFingerprint.slice(0, 16)}…</code>
          {envelope.snapshot.visibilitySequence !== null ? `, snapshot ${envelope.snapshot.visibilitySequence}` : ''}.
        </p>
        <pre className="query-page__resolved" aria-label="Resolved query">{JSON.stringify(envelope.resolvedQuery, null, 2)}</pre>
        {envelope.identity.cameras.length > 0 ? (
          <ul className="query-page__muted">
            {envelope.identity.cameras.map((camera) => (
              <li key={camera.cameraId}>
                {camera.cameraCode}: {camera.sceneRevisionNumber === null ? 'no scene configured' : `scene revision ${camera.sceneRevisionNumber}`}, analytics {camera.algorithmVersion}
              </li>
            ))}
          </ul>
        ) : null}
        {envelope.identity.attributeDisclosure ? <p className="query-page__muted">Attributes: {envelope.identity.attributeDisclosure}.</p> : null}
        {envelope.identity.eventCatalogueVersion ? <p className="query-page__muted">Event catalogue {envelope.identity.eventCatalogueVersion}.</p> : null}
        <p className="query-page__muted">{contract.disclosure}</p>
      </Panel>
    </>
  );
}

/** The envelope's coverage in the words the Analytics and Events pages use; shared with Ask MAVI (ADR-026 §5). */
export function CoverageStatus({ envelope }: { envelope: QueryEnvelope }) {
  const gaps = envelope.coverage.components.flatMap((component) =>
    coverageComponentGaps(component).map((gap) => (component.window === 'baseline' ? `baseline: ${gap}` : gap)));
  const abstentions = envelope.coverage.components
    .flatMap((component) => component.attributes?.unknown ?? [])
    .filter((item) => item.tracks > 0);
  const unreadable = envelope.coverage.components
    .reduce((sum, component) => sum + (component.attributes?.unavailable ?? 0), 0);
  return (
    <div className={envelope.coverage.complete ? 'query-page__coverage' : 'query-page__coverage query-page__coverage--incomplete'} role="status">
      {envelope.coverage.complete
        ? 'Coverage complete for this scope.'
        : `Coverage incomplete: ${gaps.join('; ')}.`}
      {abstentions.length > 0
        ? ` Unknown, not counted either way: ${abstentions.map((item) => `${item.tracks} Track(s) for ${item.type}`).join(', ')}.`
        : ''}
      {unreadable > 0 ? ` ${unreadable} Track(s) could not be read for attributes and are not counted either way.` : ''}
    </div>
  );
}

/** The envelope's result as a figure, chart and table with drill-through; shared with Ask MAVI (ADR-026 §5). */
export function Result({ envelope, displayTimeZoneId }: { envelope: QueryEnvelope; displayTimeZoneId: string | undefined }) {
  const result = envelope.result;
  switch (result.kind) {
    case 'withheld':
      return (
        <p className="query-page__withheld">
          No figure: {result.message ?? 'not every part of the scope has been analysed.'} A gap is not shown as zero.
        </p>
      );
    case 'empty':
      return <p className="query-page__withheld">No data: {result.message ?? reasonText(result.reason ?? '')}</p>;
    case 'value':
      return (
        <p className="query-page__value" aria-label="Result value">
          <strong>{result.value}</strong>{' '}
          {result.dimension ? `distinct ${dimensionLabel(result.dimension).toLowerCase()}(s)` : UNIT_LABELS[envelope.unit].toLowerCase()}
        </p>
      );
    case 'comparison':
      return (
        <dl className="query-page__comparison">
          <dt>This window</dt><dd>{result.comparison!.current}</dd>
          <dt>Baseline</dt><dd>{result.comparison!.baseline}</dd>
          <dt>Difference</dt><dd>{result.comparison!.difference > 0 ? '+' : ''}{result.comparison!.difference}</dd>
        </dl>
      );
    case 'groups':
      return (
        <Bars
          caption={`${UNIT_LABELS[envelope.unit]} by ${dimensionLabel(result.dimension ?? '').toLowerCase()}`}
          rows={(result.groups ?? []).map((group) => ({ key: group.key ?? '(none)', label: group.label, count: group.count }))}
        />
      );
    case 'buckets':
      return (
        <Bars
          caption={`${UNIT_LABELS[envelope.unit]} per ${result.bucketSeconds! >= 3_600 ? `${result.bucketSeconds! / 3_600} h` : `${result.bucketSeconds! / 60} min`}`}
          rows={(result.buckets ?? []).map((bucket) => ({ key: bucket.startUtc, label: displayTimestamp(bucket.startUtc, displayTimeZoneId), count: bucket.count }))}
        />
      );
    case 'rows':
      return (
        <>
          {result.truncation ? <p className="query-page__muted">{truncationText(result.truncation)}</p> : null}
          {result.tracks && searchPath(envelope) ? (
            <p><Link to={searchPath(envelope)!}>Open these Tracks in Search</Link> to page through all of them.</p>
          ) : null}
          {result.tracks ? <TrackTable envelope={envelope} rows={result.tracks} displayTimeZoneId={displayTimeZoneId} /> : null}
          {result.events ? <EventTable envelope={envelope} rows={result.events} displayTimeZoneId={displayTimeZoneId} /> : null}
          {(result.tracks?.length ?? result.events?.length ?? 0) === 0 ? (
            <p>{envelope.coverage.complete ? 'Nothing matches in this scope.' : 'Nothing matches in the analysed part of the scope so far.'}</p>
          ) : null}
        </>
      );
    default:
      return null;
  }
}

/** What a row result shows of the matching set; under incomplete coverage the total is only "at least". */
export function truncationText(truncation: NonNullable<QueryEnvelope['result']['truncation']>): string {
  if (truncation.totalIsLowerBound) {
    return `Showing ${truncation.returned} of at least ${truncation.total} found so far: not every part of the scope has been analysed.`;
  }
  return truncation.truncated ? `Showing ${truncation.returned} of ${truncation.total}.` : `${truncation.total} found.`;
}

/**
 * The same Tracks in Search, for paging (ADR-024 §5): only for a query Search can express with its ordinary keys —
 * at most one camera, the window and the class, with no derived or geometric predicate. Otherwise null.
 */
export function searchPath(envelope: QueryEnvelope): string | null {
  const where = envelope.resolvedQuery.where;
  if (envelope.unit !== 'track' || (where.cameraIds?.length ?? 0) > 1 || where.zone || where.line || where.motion ||
    where.attributes || where.plateText || where.similarTo || where.objectSubclass || where.minDurationMs !== undefined ||
    where.minConfidence !== undefined) return null;
  const params = new URLSearchParams();
  if (where.cameraIds?.length === 1) params.set('cameraId', where.cameraIds[0]);
  if (where.objectClass) params.set('objectClass', where.objectClass);
  params.set('fromUtc', where.timeWindow.fromUtc);
  params.set('toUtc', where.timeWindow.toUtc);
  return `/search?${params.toString()}`;
}

/** Horizontal bars with a table twin, as the Analytics page draws them; the table is the accessible form. */
function Bars({ caption, rows }: { caption: string; rows: { key: string; label: string; count: number }[] }) {
  const maximum = Math.max(1, ...rows.map((row) => row.count));
  return (
    <figure className="query-page__bars">
      <figcaption>{caption}</figcaption>
      <div aria-hidden="true">
        {rows.map((row) => (
          <div key={row.key} className="query-page__bar-row">
            <span className="query-page__bar-label">{row.label}</span>
            <span className="query-page__bar" style={{ width: `${(row.count / maximum) * 100}%` }} />
            <span className="query-page__bar-value">{row.count}</span>
          </div>
        ))}
      </div>
      <table className="query-page__table">
        <thead><tr><th>{caption.split(' by ')[1] ?? 'From'}</th><th>Count</th></tr></thead>
        <tbody>
          {rows.map((row) => <tr key={row.key}><td>{row.label}</td><td>{row.count}</td></tr>)}
        </tbody>
      </table>
    </figure>
  );
}

/**
 * Review for one Track. A geometric query matched it against a resolved scene revision and analytics version; the
 * link pins that identity, as Track search and the Event links do, so Review shows the analytics the match rested on
 * even after the camera's active revision changes.
 */
export function trackReviewPath(row: QueryTrackRow, identity?: QueryCameraIdentity): string {
  const params = new URLSearchParams();
  params.set('trackId', row.trackId.toLowerCase());
  if (identity?.sceneRevisionId) {
    params.set('sceneRevisionId', identity.sceneRevisionId.toLowerCase());
    params.set('analyticsAlgorithmVersion', identity.algorithmVersion);
  }
  return `/review/video/${row.videoAssetId.toLowerCase()}?${params.toString()}`;
}

function TrackTable({ envelope, rows, displayTimeZoneId }: { envelope: QueryEnvelope; rows: QueryTrackRow[]; displayTimeZoneId: string | undefined }) {
  // Only a geometric Track query resolves a camera identity; any other Track query names none, and its links stay plain.
  const identityOf = (cameraId: string) => envelope.identity.cameras.find((camera) => camera.cameraId.toLowerCase() === cameraId.toLowerCase());
  return (
    <table className="query-page__table" aria-label="Tracks">
      <thead><tr><th>Start</th><th>Camera</th><th>Class</th><th>Duration</th>{rows.some((row) => row.similarityScore !== null) ? <th>Score</th> : null}<th /></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.trackId}>
            <td>{displayTimestamp(row.startTimestampUtc, displayTimeZoneId)}</td>
            <td>{row.cameraCode}</td>
            <td>{row.objectClass}{row.objectSubclass ? ` · ${row.objectSubclass}` : ''}</td>
            <td>{formatOffset(row.durationMs)}</td>
            {row.similarityScore !== null ? <td>{row.similarityScore.toFixed(3)}</td> : null}
            <td><Link to={trackReviewPath(row, identityOf(row.cameraId))}>Review Track</Link></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EventTable({ envelope, rows, displayTimeZoneId }: { envelope: QueryEnvelope; rows: QueryEventRow[]; displayTimeZoneId: string | undefined }) {
  const revisionOf = (cameraId: string) => envelope.identity.cameras.find((camera) => camera.cameraId === cameraId);
  return (
    <table className="query-page__table" aria-label="Events">
      <thead><tr><th>Time</th><th>Camera</th><th>Rule</th><th>Where</th><th /></tr></thead>
      <tbody>
        {rows.map((row) => {
          const identity = revisionOf(row.cameraId);
          const review = row.primaryTrackId && identity?.sceneRevisionId
            ? `/review/video/${row.videoAssetId.toLowerCase()}?${new URLSearchParams({
              trackId: row.primaryTrackId.toLowerCase(),
              sceneRevisionId: identity.sceneRevisionId.toLowerCase(),
              analyticsAlgorithmVersion: identity.algorithmVersion,
              seekMs: String(Math.max(0, Math.trunc(row.startOffsetMs))),
            }).toString()}`
            : null;
          return (
            <tr key={row.eventId}>
              <td>{displayTimestamp(row.startUtc, displayTimeZoneId)}</td>
              <td>{row.cameraCode}</td>
              <td>{row.ruleId} v{row.ruleVersion}{row.objectClass ? ` · ${row.objectClass}` : ''}</td>
              <td>{[row.zoneName, row.lineName, row.direction === 'AToB' ? 'A → B' : row.direction === 'BToA' ? 'B → A' : null].filter(Boolean).join(' ') || '—'}</td>
              <td className="query-page__links">
                {review ? <Link to={review}>Review at event</Link> : null}
                <Link to={`/cameras/${row.cameraId.toLowerCase()}/events`}>Camera events</Link>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
