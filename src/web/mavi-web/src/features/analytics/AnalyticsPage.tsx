import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  ANALYTICS_CAMERA_NOT_FOUND,
  getAnalyticsAggregates,
  serializeAggregateQuery,
} from '../../api/analytics';
import { getCamera } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import LoadingState from '../../shared/components/LoadingState';
import StatusBadge from '../../shared/components/StatusBadge';
import Segmented from '../../shared/workspace/Segmented';
import ContextBar from '../../shared/workspace/ContextBar';
import Inspector from '../../shared/workspace/Inspector';
import { WorkbenchLayout } from '../../shared/workspace';
import ActivityChart from './ActivityChart';
import ActivityInspector from './ActivityInspector';
import AnalyticsControls from './AnalyticsControls';
import {
  initialQueryState,
  METRICS,
  presetWindow,
  queryProblem,
  readActivity,
  resolveSubject,
  scopePresence,
  subjectsFor,
  type AnalyticsMode,
  type AnalyticsQueryState,
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

  const camera = useQuery({
    queryKey: queryKeys.camera(cameraId),
    queryFn: ({ signal }) => getCamera(cameraId, signal),
    enabled: Boolean(cameraId),
  });

  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });
  // Null rather than a silent 'UTC' fallback: a time shown in the wrong zone
  // reads as a fact about when something happened.
  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId ?? null;
  const renderZoneId = displayTimeZoneId ?? 'UTC';

  const problem = queryProblem(state);
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
    enabled: Boolean(cameraId) && state.mode === 'activity' && problem === null,
  });

  const response = aggregates.data;
  const subjectId = useMemo(
    () => resolveSubject(response, state.metric, state.subjectId),
    [response, state.metric, state.subjectId],
  );
  const subjects = subjectsFor(response, state.metric);
  const reading = response ? readActivity(response, state.metric, subjectId) : null;

  const update = (patch: Partial<AnalyticsQueryState>) => setState((current) => ({ ...current, ...patch }));
  const applyPreset = (preset: WindowPresetId) => update(presetWindow(preset, new Date()));

  const cameraMissing = camera.isError && camera.error instanceof ApiError && camera.error.status === 404;
  const analyticsCameraMissing = aggregates.isError
    && aggregates.error instanceof ApiError
    && aggregates.error.code === ANALYTICS_CAMERA_NOT_FOUND;

  const crumbs = [
    { label: 'Cameras', to: '/cameras' },
    { label: camera.data ? `${camera.data.code} · ${camera.data.name}` : cameraId, to: `/cameras/${cameraId}/scene` },
    { label: 'Analytics' },
  ];

  return (
    <>
      <ContextBar
        crumbs={crumbs}
        status={response ? <CoverageChip complete={response.coverage.complete} /> : null}
        actions={<ButtonLink size="sm" variant="ghost" to={`/cameras/${cameraId}/scene`}>Scene configuration</ButtonLink>}
      />

      <WorkbenchLayout
        inspectorLabel="Analytics inspector"
        modes={(
          <div className="analytics-modes">
            <Segmented<AnalyticsMode>
              label="Analytics mode"
              value={state.mode}
              options={[
                { value: 'activity', label: 'Activity' },
                { value: 'heatmap', label: 'Heatmap' },
              ]}
              onChange={(mode) => update({ mode })}
            />
            {state.mode === 'activity' && subjects.length > 0 ? (
              <label className="analytics-modes__subject">
                <span className="visually-hidden">
                  {METRICS[state.metric].subject === 'zone' ? 'Zone' : 'Trip line'}
                </span>
                <select
                  value={subjectId ?? ''}
                  onChange={(event) => update({ subjectId: event.target.value })}
                >
                  {subjects.map((subject) => (
                    <option key={subject.id} value={subject.id}>{subject.label}</option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
        )}
        notices={(
          <>
            <AnalyticsControls
              state={state}
              displayTimeZoneId={displayTimeZoneId}
              problem={problem}
              refreshing={aggregates.isFetching}
              onChange={update}
              onPreset={applyPreset}
              onRefresh={() => void aggregates.refetch()}
            />
            {aggregates.isError && response ? (
              <Alert tone="stale" actions={<Button size="sm" onClick={() => void aggregates.refetch()}>Retry</Button>}>
                These figures are the last answer that arrived. A refresh since then has failed, so they may no
                longer be current.
              </Alert>
            ) : null}
          </>
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
                The window and interval above have to be changed before there is anything to read.
              </EmptyState>
            ) : state.mode === 'heatmap' ? (
              <EmptyState icon="info" title="Heatmap" compact>Select a window to build the density map.</EmptyState>
            ) : aggregates.isLoading ? (
              <LoadingState label="Reading analytics…" />
            ) : aggregates.isError && !response ? (
              <Alert tone="error" actions={<Button size="sm" onClick={() => void aggregates.refetch()}>Retry</Button>}>
                {aggregates.error instanceof ApiError ? aggregates.error.detail : 'Analytics could not be read.'}
              </Alert>
            ) : response ? (
              <ActivityStage
                response={response}
                reading={reading}
                displayTimeZoneId={renderZoneId}
                cameraId={cameraId}
              />
            ) : null}
          </div>
        )}
        inspector={(
          <Inspector label="Analytics inspector" title="Analytics">
            {response ? (
              <ActivityInspector response={response} reading={reading} displayTimeZoneId={renderZoneId} />
            ) : (
              <p className="faint">Figures appear once a window has been read.</p>
            )}
          </Inspector>
        )}
      />
    </>
  );
}

function CoverageChip({ complete }: { complete: boolean }) {
  // Persistent text, never colour alone: coverage is the difference between an
  // observation and an absence of one, and it has to survive a greyscale print.
  return (
    <StatusBadge tone={complete ? 'ok' : 'warn'}>
      {complete ? 'Coverage complete' : 'Coverage incomplete'}
    </StatusBadge>
  );
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
  reading,
  displayTimeZoneId,
  cameraId,
}: {
  response: Parameters<typeof ActivityInspector>[0]['response'];
  reading: ReturnType<typeof readActivity>;
  displayTimeZoneId: string;
  cameraId: string;
}) {
  if (response.sceneRevisionId === null) {
    return (
      <EmptyState
        icon="layers"
        title="No scene configured"
        actions={<ButtonLink to={`/cameras/${cameraId}/scene`}>Configure the scene</ButtonLink>}
      >
        Zones and trip lines have to exist before there is anything to count.
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
