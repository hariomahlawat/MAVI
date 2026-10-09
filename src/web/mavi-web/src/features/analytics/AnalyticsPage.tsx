import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  ANALYTICS_CAMERA_NOT_FOUND,
  getAnalyticsAggregates,
  getAnalyticsHeatmap,
  heatmapScopeRefusal,
  serializeAggregateQuery,
  serializeHeatmapQuery,
} from '../../api/analytics';
import { getCamera } from '../../api/cameras';
import { getCameraScene } from '../../api/scene';
import { ApiError, isGuid } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { queryKeys } from '../../app/queryClient';
import { fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Button, { ButtonLink } from '../../shared/components/Button';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import EmptyState from '../../shared/components/EmptyState';
import StatusBadge from '../../shared/components/StatusBadge';
import { ContextBar, Inspector, Segmented, Toolbar, WorkbenchLayout } from '../../shared/workspace';
import ActivityChart from './ActivityChart';
import ActivityInspector from './ActivityInspector';
import AnalyticsControls from './AnalyticsControls';
import HeatmapInspector from './HeatmapInspector';
import HeatmapStage from './HeatmapStage';
import {
  ACTIVITY_METRICS,
  coverageStatus,
  initialQueryState,
  revisionAnalyticsEnabled,
  METRICS,
  presetWindow,
  bucketProblem,
  queryProblem,
  readActivity,
  resolveSubject,
  windowProblem,
  scopePresence,
  subjectsFor,
  type ActivityMetric,
  type AnalyticsMode,
  type AnalyticsQueryState,
  type CoverageStatus,
  type WindowPresetId,
} from './analyticsState';

/**
 * The Analytics Workbench: what this camera's scene saw over a window.
 *
 * Camera-first by design. There is no cross-camera aggregate here, because the
 * analytical identity — scene revision, engine version, visibility snapshot —
 * is per camera, and a figure summed across cameras would be summed across
 * different geometry answering different questions.
 *
 * The state grammar is the point of the surface. "Loading", "unavailable",
 * "nothing configured", "nothing analysed yet" and "analysed, and the answer is
 * zero" are five different things, and only the last of them is an observation.
 */
export default function AnalyticsPage() {
  const { cameraId = '' } = useParams();
  const [state, setState] = useState<AnalyticsQueryState>(() => initialQueryState(new Date()));
  const [opacity, setOpacity] = useState(0.75);

  const camera = useQuery({
    queryKey: queryKeys.camera(cameraId),
    queryFn: ({ signal }) => getCamera(cameraId, signal),
    enabled: Boolean(cameraId),
  });

  // The scene the Context Bar already links to. Read for one fact the answer
  // does not carry: whether the revision it was resolved against enables
  // analytics, which the run counters cannot say for a window with no runs
  // (F25). Unread or failed, it decides nothing — the counters still do.
  const scene = useQuery({
    queryKey: queryKeys.cameraScene(cameraId),
    queryFn: ({ signal }) => getCameraScene(cameraId, signal),
    enabled: Boolean(cameraId),
  });
  const enabledFor = (revisionId: string | null) => revisionAnalyticsEnabled(scene.data, revisionId);

  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });
  // Null rather than a silent 'UTC' fallback: a time shown in the wrong zone
  // reads as a fact about when something happened. Every figure this surface
  // reports is stamped with an instant, so until the zone is known there is
  // nothing here that can be rendered truthfully — the results wait for it
  // rather than being formatted against a guess.
  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId ?? null;

  // Split, because the heatmap takes no interval: a window it would answer must
  // not be refused because Activity's leftover interval would overflow its axis.
  const problem = queryProblem(state);
  const bucketRefusal = state.mode === 'activity' ? bucketProblem(state) : null;

  /**
   * Whether the mode currently in view has a question worth asking.
   *
   * This is the *one* definition of executability on this surface, and it is
   * already mode-aware: `queryProblem` applies Activity's bucket bound only in
   * Activity, so a window the heatmap would answer is never refused here for an
   * interval the heatmap does not use. Every path that can start a request —
   * automatic or manual — is gated on this same value, because a second,
   * slightly different predicate for the manual path is how the two drift apart.
   */
  const canRunQuery = problem === null;
  const aggregateQuery = {
    fromUtc: state.fromUtc,
    toUtc: state.toUtc,
    bucketSeconds: state.bucketSeconds,
    ...(state.objectClass ? { objectClass: state.objectClass } : {}),
  };
  const fingerprint = serializeAggregateQuery(aggregateQuery);

  const aggregates = useQuery({
    queryKey: queryKeys.cameraAnalyticsAggregates(cameraId, fingerprint),
    queryFn: ({ signal }) => getAnalyticsAggregates(cameraId, aggregateQuery, signal),
    // A question the contract will refuse is not asked. The operator is told
    // what to change instead of being shown a failure they caused and cannot
    // read the cause of.
    enabled: Boolean(cameraId) && state.mode === 'activity' && canRunQuery,
  });

  const heatmapRequest = {
    fromUtc: state.fromUtc,
    toUtc: state.toUtc,
    gridWidth: state.gridWidth,
    ...(state.objectClass ? { objectClass: state.objectClass } : {}),
  };

  const heatmap = useQuery({
    queryKey: queryKeys.cameraAnalyticsHeatmap(cameraId, serializeHeatmapQuery(heatmapRequest)),
    queryFn: ({ signal }) => getAnalyticsHeatmap(cameraId, heatmapRequest, signal),
    enabled: Boolean(cameraId) && state.mode === 'heatmap' && canRunQuery,
    // Reading sealed evidence is expensive and the answer is pinned to a
    // snapshot, so it is not refetched behind the operator's back.
    staleTime: Infinity,
    retry: false,
  });

  const response = aggregates.data;
  const subjectId = useMemo(
    () => resolveSubject(response, state.metric, state.subjectId),
    [response, state.metric, state.subjectId],
  );
  const subjects = subjectsFor(response, state.metric);
  const reading = response ? readActivity(response, state.metric, subjectId) : null;

  /**
   * The manual execution path, obeying the same rule as the automatic one.
   *
   * `enabled: false` stops TanStack Query from running a query on its own, but
   * it does not stop `refetch()`, which is imperative and runs regardless. So a
   * surface that promises "a question the contract will refuse is not asked"
   * has to restate the gate here, or pressing Refresh on a refused window sends
   * exactly the request the refusal said it would not.
   *
   * Defined during render rather than memoised: it closes over this render's
   * query objects, so it cannot act on a stale `enabled` decision.
   */
  const refresh = () => {
    if (!canRunQuery) return;
    void active.refetch();
  };

  const update = (patch: Partial<AnalyticsQueryState>) => setState((current) => ({ ...current, ...patch }));
  const applyPreset = (preset: WindowPresetId) => update(presetWindow(preset, new Date()));

  const active = state.mode === 'heatmap' ? heatmap : aggregates;
  const cameraMissing = camera.isError && camera.error instanceof ApiError && camera.error.status === 404;
  const analyticsCameraMissing = active.isError
    && active.error instanceof ApiError
    && active.error.code === ANALYTICS_CAMERA_NOT_FOUND;


  return (
    // One `.page` surface like every routed surface (§4, D9): full width, and a
    // workspace column so the Workbench below owns the height and the page
    // does not scroll (§4.3.2) — the wrapper the Scene Editor Workbench uses.
    <section className="page page--full page--workspace">
      <ContextBar
        surface="analytics"
        // The camera this route names (§5: `Cameras › {camera} › Analytics`):
        // its code and name once read, otherwise its identifier shortened —
        // never the full GUID, and never dropped while it loads or fails.
        object={isGuid(cameraId) || camera.data
          ? { label: camera.data ? `${camera.data.code} · ${camera.data.name}` : `Camera ${cameraId.toLowerCase().slice(0, 8)}…`, to: `/cameras/${cameraId}/scene` }
          : undefined}
        status={(() => {
          const answer = state.mode === 'heatmap' ? heatmap.data : response;
          return (
            <>
              {answer ? <CoverageChip status={coverageStatus(answer.sceneRevisionId, answer.coverage, enabledFor(answer.sceneRevisionId))} /> : null}
              {/* §24: the zone every time on this surface is read in, once. */}
              <DisplayTimeZone timeZoneId={displayTimeZoneId} />
            </>
          );
        })()}
        actions={<ButtonLink size="sm" variant="ghost" to={`/cameras/${cameraId}/scene`}>Scene configuration</ButtonLink>}
      />

      <WorkbenchLayout
        inspectorLabel="Analytics inspector"
        // F22: two 32px bands, each with one job — what is asked (mode,
        // metric, subject; Refresh asks it again) and over what (the window
        // and its filters) — instead of a form of labelled fields above the
        // chart. The question band is the Workbench's mode strip (§4.3).
        modes={(
          <Toolbar
            label="Analytics question"
            actions={(
              // Disabled while the query is refused, rather than left enabled
              // over a callback that silently declines: the reason is stated
              // in the window band on the field that repairs it, and `title`
              // carries it to anyone who reaches the button first.
              <Button
                size="sm"
                variant="ghost"
                icon="refresh"
                onClick={refresh}
                disabled={active.isFetching || !canRunQuery}
                title={canRunQuery ? undefined : 'Adjust the window before refreshing.'}
              >
                {active.isFetching ? 'Refreshing…' : 'Refresh'}
              </Button>
            )}
          >
            <Segmented<AnalyticsMode>
              label="Analytics mode"
              value={state.mode}
              options={[
                { value: 'activity', label: 'Activity' },
                { value: 'heatmap', label: 'Heatmap' },
              ]}
              onChange={(mode) => update({ mode })}
            />
            {state.mode === 'activity' ? (
              <>
                <label className="visually-hidden" htmlFor="analytics-metric">Metric</label>
                <select
                  id="analytics-metric"
                  value={state.metric}
                  onChange={(event) => update({ metric: event.target.value as ActivityMetric })}
                >
                  {ACTIVITY_METRICS.map((metric) => (
                    <option key={metric} value={metric}>{METRICS[metric].label}</option>
                  ))}
                </select>
              </>
            ) : null}
            {state.mode === 'activity' && subjects.length > 0 ? (
              <>
                <label className="visually-hidden" htmlFor="analytics-subject">
                  {METRICS[state.metric].subject === 'zone' ? 'Zone' : 'Trip line'}
                </label>
                <select
                  id="analytics-subject"
                  value={subjectId ?? ''}
                  onChange={(event) => update({ subjectId: event.target.value })}
                >
                  {subjects.map((subject) => (
                    <option key={subject.id} value={subject.id}>{subject.label}</option>
                  ))}
                </select>
              </>
            ) : null}
          </Toolbar>
        )}
        notices={(
          <AnalyticsControls
            state={state}
            displayTimeZoneId={displayTimeZoneId}
            windowProblem={windowProblem(state)}
            bucketProblem={bucketRefusal}
            onChange={update}
            onPreset={applyPreset}
          />
        )}
        stage={(
          <div className="analytics-stage">
            {cameraMissing || analyticsCameraMissing ? (
              <EmptyState
                icon="camera"
                title="This camera does not exist"
                actions={<ButtonLink to="/cameras">Go to Cameras</ButtonLink>}
              >
                It may have been removed since this link was made.
              </EmptyState>
            ) : problem !== null ? (
              <EmptyState icon="info" title="Adjust the window">
                {state.mode === 'activity' && bucketRefusal !== null
                  ? 'The window and interval above have to be changed before there is anything to read.'
                  : 'The window above has to be changed before there is anything to read.'}
              </EmptyState>
            ) : (
              // The stage is one column region on two requests in sequence
              // (§37.1): every figure is stamped with an instant, so nothing
              // is read until the configured display timezone is known, and
              // then the mode's own request is the region's state.
              <StateRegion
                kind="column"
                state={fromQuery(systemConfig)}
                label="the configured display timezone"
                loadingLabel="Reading the configured timezone…"
                unavailableMessage={() => 'The configured display timezone is unavailable. Every figure here is stamped with an instant, so none of them can be shown until it is known.'}
                degradedMessage="Using the last known display timezone; refreshing the configuration failed."
                onRetry={() => void systemConfig.refetch()}
              >
                {(config) => state.mode === 'heatmap' ? (
                  <HeatmapPane
                    query={heatmap}
                    cameraId={cameraId}
                    enabledFor={enabledFor}
                    opacity={opacity}
                    onOpacityChange={setOpacity}
                    onNarrow={() => applyPreset('lastHour')}
                    onRetry={refresh}
                  />
                ) : (
                  <StateRegion
                    kind="column"
                    state={fromQuery(aggregates)}
                    label="analytics"
                    loadingLabel="Reading analytics…"
                    unavailableMessage={(error) => error instanceof ApiError ? error.detail : 'Analytics could not be read.'}
                    degradedMessage="These figures are the last answer that arrived. A refresh since then has failed, so they may no longer be current."
                    onRetry={refresh}
                  >
                    {(answer) => (
                      <ActivityStage
                        response={answer}
                        analyticsEnabled={enabledFor(answer.sceneRevisionId)}
                        reading={reading}
                        displayTimeZoneId={config.displayTimeZoneId}
                        cameraId={cameraId}
                      />
                    )}
                  </StateRegion>
                )}
              </StateRegion>
            )}
          </div>
        )}
        inspector={(
          <Inspector label="Analytics inspector" title="Analytics">
            {displayTimeZoneId === null ? (
              <p className="faint">
                Figures appear once the configured display timezone is known.
              </p>
            ) : state.mode === 'heatmap' ? (
              heatmap.data
                ? <HeatmapInspector response={heatmap.data} displayTimeZoneId={displayTimeZoneId} />
                : <p className="faint">Figures appear once a density map has been built.</p>
            ) : response ? (
              <ActivityInspector response={response} reading={reading} displayTimeZoneId={displayTimeZoneId} />
            ) : (
              <p className="faint">Figures appear once a window has been read.</p>
            )}
          </Inspector>
        )}
      />
    </section>
  );
}

/**
 * The heatmap's own answers, which are not the aggregate's.
 *
 * Two of them are specific to reading sealed evidence: a scope the server
 * refuses to open before it opens anything, and evidence it could not read.
 * Neither is an empty map. A map drawn from the artefacts that happened to open
 * would be a map of which files survived, not of where anything went.
 */
function HeatmapPane({
  query,
  cameraId,
  enabledFor,
  opacity,
  onOpacityChange,
  onNarrow,
  onRetry,
}: {
  query: ReturnType<typeof useQuery<Awaited<ReturnType<typeof getAnalyticsHeatmap>>>>;
  cameraId: string;
  enabledFor: (revisionId: string | null) => boolean | null;
  opacity: number;
  onOpacityChange: (value: number) => void;
  onNarrow: () => void;
  /** The page's guarded refresh, so this retry cannot bypass the gate either. */
  onRetry: () => void;
}) {
  const refusal = heatmapScopeRefusal(query.error);
  if (refusal) {
    const dimension = refusal.dimension === 'coveredRuns' ? 'processing runs'
      : refusal.dimension === 'candidateTracks' ? 'analysed Tracks'
        : 'covered work';
    return (
      <EmptyState
        icon="info"
        title="This window covers too much to map"
        actions={<Button onClick={onNarrow}>Use the last hour</Button>}
      >
        {refusal.limit === null
          ? `The window covers more ${dimension} than a single map is allowed to read.`
          : `The window covers more than ${refusal.limit.toLocaleString()} ${dimension}, which is the most a single `
            + 'map is allowed to read. Narrow the window and try again.'}
      </EmptyState>
    );
  }

  // The refusal above is a domain answer, not a failure (§14); everything else
  // is the density map's region state (§37.1).
  return (
    <StateRegion
      kind="column"
      state={fromQuery(query)}
      label="the density map"
      loadingLabel="Reading trajectory evidence…"
      unavailableMessage={(error) => error instanceof ApiError && error.status === 503
        ? 'Trajectory evidence for an analysed Track could not be read, so no map was built. '
          + 'A partial map would show where the readable files went, not where anything went.'
        : error instanceof ApiError ? error.detail : 'The density map could not be built.'}
      degradedMessage="This map is the last one that was built. A refresh since then has failed, so it may no longer be current."
      onRetry={onRetry}
    >
      {(map) => coverageStatus(map.sceneRevisionId, map.coverage, enabledFor(map.sceneRevisionId)) === 'not-configured' ? (
        <EmptyState
          icon="layers"
          title="No scene configured"
          hatched
          actions={<ButtonLink to={`/cameras/${cameraId}/scene`}>Configure the scene</ButtonLink>}
        >
          There is no scene to read trajectories against, so there is no map to draw.
        </EmptyState>
      ) : coverageStatus(map.sceneRevisionId, map.coverage, enabledFor(map.sceneRevisionId)) === 'disabled' ? (
        <EmptyState icon="layers" title="Analytics disabled by the scene" hatched>
          The scene revision in force has no enabled geometry, so no run in this window was analysed.
        </EmptyState>
      ) : scopePresence(map.coverage) === 'incomplete' ? (
        <EmptyState
          icon="clock"
          title="Not every run in this window has been analysed"
          actions={<ButtonLink to="/processing">Go to Processing</ButtonLink>}
        >
          No map is drawn rather than a partial one: an empty region would read as somewhere nothing went,
          when it may simply be somewhere nothing has been analysed yet.
        </EmptyState>
      ) : (
        <HeatmapStage response={map} opacity={opacity} onOpacityChange={onOpacityChange} />
      )}
    </StateRegion>
  );
}

/**
 * The scope's condition, named (F25). Persistent text, never colour alone:
 * coverage is the difference between an observation and an absence of one, and
 * it has to survive a greyscale print. A camera with no scene is not configured
 * — not "coverage incomplete", which would send the operator to Processing for
 * runs that have nothing to be analysed against.
 */
const COVERAGE_CHIP: Record<CoverageStatus, { tone: 'ok' | 'warn' | 'neutral'; text: string }> = {
  complete: { tone: 'ok', text: 'Coverage complete' },
  incomplete: { tone: 'warn', text: 'Coverage incomplete' },
  stale: { tone: 'warn', text: 'Coverage stale' },
  disabled: { tone: 'neutral', text: 'Analytics disabled' },
  'not-configured': { tone: 'neutral', text: 'No scene configured' },
};

function CoverageChip({ status }: { status: CoverageStatus }) {
  const { tone, text } = COVERAGE_CHIP[status];
  return <StatusBadge tone={tone}>{text}</StatusBadge>;
}

/**
 * The stage's five distinguishable answers.
 *
 * The one that matters is the last pair: a complete scope holding no facts is a
 * real observation and is drawn as zero, and an incomplete one never is. An
 * empty chart for an incomplete scope would assert that the runs still waiting
 * to be analysed hold nothing, which is precisely what is not known.
 */
function ActivityStage({
  response,
  analyticsEnabled,
  reading,
  displayTimeZoneId,
  cameraId,
}: {
  response: Parameters<typeof ActivityInspector>[0]['response'];
  analyticsEnabled: boolean | null;
  reading: ReturnType<typeof readActivity>;
  displayTimeZoneId: string;
  cameraId: string;
}) {
  const status = coverageStatus(response.sceneRevisionId, response.coverage, analyticsEnabled);
  // Not configured and disabled are domain states, hatched (§14), never
  // partial coverage: there was nothing to analyse against, not something left.
  if (status === 'not-configured') {
    return (
      <EmptyState
        icon="layers"
        title="No scene configured"
        hatched
        actions={<ButtonLink to={`/cameras/${cameraId}/scene`}>Configure the scene</ButtonLink>}
      >
        Zones and trip lines have to exist before there is anything to count.
      </EmptyState>
    );
  }

  if (status === 'disabled') {
    return (
      <EmptyState icon="layers" title="Analytics disabled by the scene" hatched>
        The scene revision in force has no enabled geometry, so no run in this window was analysed.
      </EmptyState>
    );
  }

  if (scopePresence(response.coverage) === 'incomplete') {
    return (
      <EmptyState
        icon="clock"
        title="Not every run in this window has been analysed"
        actions={<ButtonLink to="/processing">Go to Processing</ButtonLink>}
      >
        Figures are withheld rather than shown partially: a chart drawn from part of the window would read
        as an observation about all of it. The inspector lists what is outstanding.
      </EmptyState>
    );
  }

  if (!reading) {
    return (
      <EmptyState icon="info" title="Nothing to count for this metric" compact>
        The resolved scene revision has no enabled geometry for this measurement, so it was never evaluated.
      </EmptyState>
    );
  }

  return <ActivityChart reading={reading} displayTimeZoneId={displayTimeZoneId} />;
}
