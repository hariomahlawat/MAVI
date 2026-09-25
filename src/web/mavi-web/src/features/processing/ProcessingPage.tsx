import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { getCamera } from '../../api/cameras';
import { ApiError, isGuid } from '../../api/client';
import {
  analyticsPollInterval,
  currentUnit,
  getRunAnalytics,
  latestFactBearingUnit,
  requestSceneReanalysis,
  retryRunAnalytics,
  type ProcessingRunAnalytics,
} from '../../api/sceneAnalytics';
import { getSystemConfig } from '../../api/system';
import {
  getProcessingStatus,
  getVideo,
  isFinalizationFailure,
  isFinalizing,
  processingPollInterval,
  queueProcessing,
  type AnalyticsReadiness,
} from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { analyticsReadinessText } from './analyticsReadiness';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import EmptyState from '../../shared/components/EmptyState';
import KeyValue from '../../shared/components/KeyValue';
import LoadingState from '../../shared/components/LoadingState';
import Panel from '../../shared/components/Panel';
import Progress from '../../shared/components/Progress';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatCount, frameRateText } from '../../shared/format/format';
import { FINALIZATION_FAILED_LABEL, isActiveStatus } from '../../shared/status/status';
import { ContextBar, RecordLayout } from '../../shared/workspace';

/**
 * A state coarsened to what it means operationally, so "the run disagrees with
 * the video" can be decided rather than guessed: `Processing` and `Running` are
 * the same answer in two vocabularies.
 */
function coarseState(status: string): string {
  if (isActiveStatus(status)) return 'active';
  if (status === 'Failed') return 'failed';
  if (status === 'Processed' || status === 'Completed') return 'completed';
  return status;
}

function safeFormatTimestamp(value: string | null | undefined, timeZoneId: string | undefined): string {
  if (!value || !timeZoneId) return '—';
  return displayTimestamp(value, timeZoneId);
}

/**
 * Processing detail — a Record (§4.2).
 *
 * The primary column is the run: what state it is in, how far it has got, and
 * what it produced. The facts rail is the video it ran over. Identifiers — the
 * run's, the video's, the worker's — live behind the Diagnostics disclosure
 * and nowhere else: §16 and §30 keep GUIDs out of ordinary operator content,
 * and a Record is ordinary operator content.
 *
 * The breadcrumb is the way back to the queue, so the "All processing" button
 * this page used to carry is gone rather than duplicated beside it.
 *
 * Deliberately absent: Scene Analytics readiness. It is excluded from UI-3 and
 * lands on this grammar in Slice 4 (§33.4).
 */
export default function ProcessingPage() {
  const { videoAssetId = '' } = useParams();
  const validId = isGuid(videoAssetId);
  const location = useLocation();
  const queryClient = useQueryClient();

  const video = useQuery({
    queryKey: queryKeys.video(videoAssetId),
    queryFn: ({ signal }) => getVideo(videoAssetId, signal),
    enabled: validId,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 1,
  });

  const processing = useQuery({
    queryKey: queryKeys.videoProcessing(videoAssetId),
    queryFn: ({ signal }) => getProcessingStatus(videoAssetId, signal),
    enabled: validId,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 1,
    refetchInterval: (query) => query.state.error ? false : processingPollInterval(query.state.data),
  });

  const cameraId = video.data?.cameraId ?? '';
  const camera = useQuery({
    queryKey: queryKeys.camera(cameraId),
    queryFn: ({ signal }) => getCamera(cameraId, signal),
    enabled: isGuid(cameraId),
  });

  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });

  const retry = useMutation({
    mutationFn: () => queueProcessing(videoAssetId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.video(videoAssetId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.videoProcessing(videoAssetId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.videos }),
      ]);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.code === 'processing_already_active') {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.video(videoAssetId) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.videoProcessing(videoAssetId) }),
        ]);
      }
    },
  });

  // Scene analytics readiness for the latest run (plan §S "Processing readiness
  // presentation"), read from the Slice 3 endpoint once the run has completed —
  // the endpoint answers only for completed, published runs — and polled only
  // while Pending, the one readiness that moves on its own.
  const latestRun = processing.data?.latestRun ?? null;
  const runId = latestRun?.status === 'Completed' ? latestRun.processingRunId : '';
  const analytics = useQuery({
    queryKey: queryKeys.runAnalytics(runId),
    queryFn: ({ signal }) => getRunAnalytics(runId, signal),
    enabled: runId !== '',
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 1,
    refetchInterval: (query) => query.state.error ? false : analyticsPollInterval(query.state.data),
  });

  const invalidateAnalytics = async () => {
    // Mutations invalidate both the processing readiness and the run analytics
    // (plan §S), so neither surface keeps saying what was true before the click.
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.videoProcessing(videoAssetId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.runAnalytics(runId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.videos }),
    ]);
  };

  const retryAnalytics = useMutation({
    mutationFn: () => retryRunAnalytics(runId),
    onSuccess: invalidateAnalytics,
    onError: invalidateAnalytics,
  });

  const reanalyse = useMutation({
    mutationFn: () => requestSceneReanalysis(cameraId, 'latestRuns'),
    onSuccess: invalidateAnalytics,
    onError: invalidateAnalytics,
  });

  const displayZone = systemConfig.data?.displayTimeZoneId;

  /** The Record's frame, so every terminal state keeps the surface's identity. */
  function frame(name: string, body: ReactNode) {
    return (
      <section className="page">
        <ContextBar crumbs={[{ label: 'Processing', to: '/processing' }, { label: name }]} />
        <RecordLayout>{body}</RecordLayout>
      </section>
    );
  }

  if (!validId) {
    return frame('Unknown video', <Alert tone="error">The video identifier in this route is invalid.</Alert>);
  }

  const notFound = (video.error instanceof ApiError && video.error.status === 404)
    || (processing.error instanceof ApiError && processing.error.status === 404);

  if (notFound) {
    return frame('Not found', <Alert tone="error">Video was not found.</Alert>);
  }

  const state = processing.data;
  const run = state?.latestRun;
  // The run's phase, not its status: `Running` covers inference and finalization.
  const finalizing = isFinalizing(run);
  const finalizationFailed = isFinalizationFailure(run);
  const canRetry = state
    ? state.videoStatus === 'NotQueued' || state.videoStatus === 'Failed' || run?.status === 'Failed'
    : false;
  const processed = state?.videoStatus === 'Processed';
  const navigationNotice = typeof location.state === 'object'
    && location.state !== null
    && 'notice' in location.state
    && typeof location.state.notice === 'string'
      ? location.state.notice
      : null;
  const lowerId = videoAssetId.toLowerCase();

  // `processing_already_active` is reconciled by refetching authoritative state
  // rather than reported: the video is already doing what the operator asked
  // for. The condition is computed once so that the region and its contents
  // cannot disagree — reading `retry.isError` here as well opened an empty
  // notices band for a failure this page deliberately never renders.
  const retryFailed = retry.isError
    && !(retry.error instanceof ApiError && retry.error.code === 'processing_already_active');
  const hasNotices = Boolean(navigationNotice) || retryFailed || video.isError || processing.isError;
  const notices = (
    <>
      {navigationNotice ? <Alert tone="info">{navigationNotice}</Alert> : null}
      {retryFailed ? (
        <Alert tone="error">
          {retry.error instanceof ApiError ? `${retry.error.detail} (${retry.error.code})` : 'Processing could not be queued.'}
        </Alert>
      ) : null}
      {video.isError ? <Alert tone="error">Video metadata is unavailable.</Alert> : null}
      {processing.isError ? <Alert tone="error">Processing status is unavailable.</Alert> : null}
    </>
  );

  return (
    <section className="page">
      <ContextBar
        crumbs={[{ label: 'Processing', to: '/processing' }, { label: video.data?.originalFileName ?? 'Video' }]}
        status={(
          <>
            {state ? <StatusBadge status={state.videoStatus} /> : null}
            <DisplayTimeZone timeZoneId={displayZone} />
          </>
        )}
        actions={(
          <>
            {processed ? (
              <ButtonLink to={`/search?videoAssetId=${lowerId}`} variant="primary" icon="search">Open results</ButtonLink>
            ) : null}
            {canRetry ? (
              <Button variant={processed ? 'secondary' : 'primary'} icon="play" onClick={() => retry.mutate()} disabled={retry.isPending}>
                {retry.isPending ? 'Queueing…' : state?.videoStatus === 'Failed' ? 'Retry processing' : 'Queue processing'}
              </Button>
            ) : null}
          </>
        )}
      />

      <RecordLayout
        notices={hasNotices ? notices : undefined}
        facts={video.data ? (
          <>
            <Panel title="Video">
              <KeyValue
                items={[
                  { label: 'File', value: video.data.originalFileName },
                  { label: 'Camera', value: camera.data ? `${camera.data.code} · ${camera.data.name}` : camera.isError ? 'Camera unavailable' : 'Loading camera…' },
                  { label: 'Recorded', value: safeFormatTimestamp(video.data.recordingStartUtc, displayZone) },
                  { label: 'Duration', value: formatDuration(video.data.durationMs) },
                  { label: 'Resolution', value: `${video.data.width}×${video.data.height} · ${frameRateText(video.data.frameRateNumerator, video.data.frameRateDenominator)}` },
                  { label: 'Codec', value: video.data.codecName ?? '—' },
                  { label: 'Camera timezone', value: camera.data?.timeZoneId ?? video.data.recordingTimeZoneId, mono: true },
                ]}
              />
            </Panel>

            {/* §16, §30: identifiers are not ordinary operator content. They
                are real and occasionally needed, so they are one disclosure
                away rather than absent. The display timezone is not repeated
                here — the Context Bar states it once for the surface (§24). */}
            <Panel>
              <details className="disclosure">
                <summary>Diagnostics</summary>
                <div className="disclosure__body">
                  <KeyValue
                    items={[
                      { label: 'Video', value: video.data.id, mono: true },
                      { label: 'Processing run', value: run?.processingRunId ?? '—', mono: true },
                      { label: 'Worker', value: run?.workerId ?? '—', mono: true },
                      { label: 'Pipeline', value: run ? `${run.pipeline} · ${run.pipelineVersion}` : '—', mono: true },
                    ]}
                  />
                </div>
              </details>
            </Panel>
          </>
        ) : undefined}
      >
        {(video.isPending || processing.isPending) ? <LoadingState label="Loading processing state…" /> : null}

        {/* §16: the run's own state is stated only where it differs from the
            video's, which the Context Bar already carries. Where they agree —
            the ordinary case — a second badge saying "Failed" beside a bar
            already labelled "Failed" is the duplicate §30 names. */}
        {video.data && state ? (
          <Panel
            title="Processing run"
            actions={finalizing
              // The video is still Processing, but the run is past inference:
              // that is a state that differs, so it is named (§16).
              ? <StatusBadge status="Finalizing" />
              : run && coarseState(run.status) !== coarseState(state.videoStatus)
                ? <StatusBadge status={run.status} />
                : undefined}
          >
            {run ? (
              <div className="stack">
                {/* Finalization has no percentage, and a full inference bar
                    would read as done, so a Finalizing run gets a sentence. */}
                {finalizing ? (
                  <p>Inference is complete. The results are being finalized and published; counts appear when publication completes.</p>
                ) : (
                  <Progress
                    value={run.progressPercent}
                    label={finalizationFailed ? FINALIZATION_FAILED_LABEL : isActiveStatus(run.status) ? 'Progress' : run.status}
                    tone={run.status === 'Failed' ? 'err' : run.status === 'Completed' ? 'ok' : 'info'}
                  />
                )}

                <KeyValue
                  grid
                  items={[
                    { label: 'Attempt', value: formatCount(run.attemptCount) },
                    { label: 'Queued', value: safeFormatTimestamp(run.queuedAtUtc, displayZone) },
                    { label: 'Started', value: safeFormatTimestamp(run.startedAtUtc, displayZone) },
                    { label: 'Completed', value: safeFormatTimestamp(run.completedAtUtc, displayZone) },
                    // Counts are only true once the run has finished; showing
                    // a running total would invite reading it as the answer.
                    { label: 'Frames processed', value: run.status === 'Completed' ? formatCount(run.framesProcessed) : 'Final count after completion' },
                    { label: 'Tracks created', value: run.status === 'Completed' ? formatCount(run.tracksCreated) : 'Final count after completion' },
                  ]}
                />

                {finalizationFailed ? (
                  <Alert tone="error">
                    {FINALIZATION_FAILED_LABEL} after inference completed · <code>{run.failureCode}</code>. Retrying queues a new run for this video.
                  </Alert>
                ) : run.failureCode ? (
                  <Alert tone="error">
                    Processing failed with <code>{run.failureCode}</code>. Retrying queues a new run for this video.
                  </Alert>
                ) : null}
              </div>
            ) : (
              <EmptyState icon="activity" title="Not queued" compact>
                Use Queue processing to start the authoritative pipeline for this video.
              </EmptyState>
            )}
          </Panel>
        ) : null}

        {/* Scene analytics for the completed run: readiness as text — the run's
            one badge already sits in the Context Bar (§16) — with the action the
            state calls for. Failed retries the unit; Stale offers the camera-level
            re-analysis that exists, stating its camera-wide consequence before the
            click (§15). */}
        {video.data && run && run.status === 'Completed' ? (
          <Panel title="Scene analytics">
            <SceneAnalyticsPanel
              readiness={run.analyticsReadiness}
              analytics={analytics.data}
              analyticsUnavailable={analytics.isError}
              cameraId={cameraId}
              cameraLabel={camera.data ? `${camera.data.code} · ${camera.data.name}` : 'this camera'}
              displayZone={displayZone}
              onRetry={() => retryAnalytics.mutate()}
              retrying={retryAnalytics.isPending}
              retryError={retryAnalytics.error}
              onReanalyse={() => reanalyse.mutate()}
              reanalysing={reanalyse.isPending}
              reanalyseResult={reanalyse.data}
              reanalyseError={reanalyse.error}
            />
          </Panel>
        ) : null}
      </RecordLayout>
    </section>
  );
}


function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? `${error.detail} (${error.code})` : fallback;
}

/**
 * What the six readiness states mean for this run, and what the operator can do.
 *
 * Ready names the revision and engine that analysed it and the Track counts;
 * Pending shows the unit's own progress; Failed exposes Retry analytics; Stale
 * explains that the current geometry or engine has not been applied and offers
 * the camera-wide re-analysis, saying exactly what that re-analyses; Disabled
 * and NotConfigured stay distinct and point at the Scene Editor.
 */
function SceneAnalyticsPanel({
  readiness,
  analytics,
  analyticsUnavailable,
  cameraId,
  cameraLabel,
  displayZone,
  onRetry,
  retrying,
  retryError,
  onReanalyse,
  reanalysing,
  reanalyseResult,
  reanalyseError,
}: {
  readiness: AnalyticsReadiness;
  analytics: ProcessingRunAnalytics | undefined;
  analyticsUnavailable: boolean;
  cameraId: string;
  cameraLabel: string;
  displayZone: string | undefined;
  onRetry: () => void;
  retrying: boolean;
  retryError: unknown;
  onReanalyse: () => void;
  reanalysing: boolean;
  reanalyseResult: { created: number; runsInScope: number } | undefined;
  reanalyseError: unknown;
}) {
  // The lifecycle endpoint is the richer source; the status endpoint's readiness
  // is what the row already said. They agree by construction, and when the richer
  // one is unavailable the readiness word still stands.
  const effective = analytics?.readiness ?? readiness;
  const unit = analytics ? currentUnit(analytics) : undefined;
  const previous = analytics ? latestFactBearingUnit(analytics) : undefined;
  const sceneLink = isGuid(cameraId) ? `/cameras/${cameraId.toLowerCase()}/scene` : '/cameras';

  return (
    <div className="stack">
      <KeyValue
        items={[
          { label: 'Readiness', value: <span className="analytics-state" data-readiness={effective}>{analyticsReadinessText(effective)}</span> },
          ...(effective === 'Ready' && unit
            ? [
              { label: 'Analysed with', value: `Revision ${unit.sceneRevisionNumber} · ${unit.algorithmVersion}` },
              { label: 'Tracks analysed', value: formatCount(unit.analysedTrackCount) },
              { label: 'Tracks unavailable', value: formatCount(unit.unavailableTrackCount) },
              { label: 'Completed', value: safeFormatTimestamp(unit.completedAtUtc, displayZone) },
            ]
            : []),
          ...(effective === 'Pending' && unit
            ? [{ label: 'Unit', value: `${unit.status} · attempt ${formatCount(unit.attemptCount)}` }]
            : []),
          ...(effective === 'Failed' && unit
            ? [
              { label: 'Attempts', value: formatCount(unit.attemptCount) },
              { label: 'Failure', value: <code>{unit.failureCode ?? 'unknown'}</code> },
            ]
            : []),
          ...(effective === 'Stale' && previous
            ? [{ label: 'Analysed with', value: `Revision ${previous.sceneRevisionNumber} · ${previous.algorithmVersion}` }]
            : []),
        ]}
      />

      {analyticsUnavailable ? (
        <Alert tone="warning">Analysis details are unavailable; the readiness above is from the processing status.</Alert>
      ) : null}

      {effective === 'Pending' ? (
        <p className="small faint">The analytics host will analyse this run against the active scene revision; this page keeps refreshing until it does.</p>
      ) : null}

      {effective === 'Failed' ? (
        <div className="inline-alert-actions">
          <Alert tone="error">Scene analytics failed for this run. Retrying starts a new attempt cycle on the same analysis; existing facts are kept until it succeeds.</Alert>
          <Button variant="primary" icon="refresh" onClick={onRetry} disabled={retrying}>
            {retrying ? 'Retrying…' : 'Retry analytics'}
          </Button>
        </div>
      ) : null}
      {retryError ? <Alert tone="error">{errorText(retryError, 'The analysis could not be retried.')}</Alert> : null}

      {effective === 'Stale' ? (
        <div className="inline-alert-actions">
          <Alert tone="stale">
            The current scene geometry or analytics engine has not been applied to this run; the earlier facts are kept and stay searchable by their revision.
            Re-analysing queues the latest completed run of <strong>every video of {cameraLabel}</strong> against the active revision, not just this one.
          </Alert>
          <Button variant="secondary" icon="refresh" onClick={onReanalyse} disabled={reanalysing}>
            {reanalysing ? 'Queueing…' : 'Re-analyse camera'}
          </Button>
        </div>
      ) : null}
      {reanalyseResult ? (
        <Alert tone="info">
          Re-analysis requested: {formatCount(reanalyseResult.created)} of {formatCount(reanalyseResult.runsInScope)} runs queued; the rest were already analysed, queued or need an explicit retry.
        </Alert>
      ) : null}
      {reanalyseError ? <Alert tone="error">{errorText(reanalyseError, 'Re-analysis could not be requested.')}</Alert> : null}

      {effective === 'Disabled' ? (
        <div className="inline-alert-actions">
          <Alert tone="info">The active scene revision enables no zone or trip line, so analytics are switched off for this camera on purpose.</Alert>
          <ButtonLink size="sm" to={sceneLink}>Open Scene Editor</ButtonLink>
        </div>
      ) : null}
      {effective === 'NotConfigured' ? (
        <div className="inline-alert-actions">
          <Alert tone="info">This camera has no scene configuration yet, so there is nothing to analyse against.</Alert>
          <ButtonLink size="sm" to={sceneLink}>Open Scene Editor</ButtonLink>
        </div>
      ) : null}
    </div>
  );
}
