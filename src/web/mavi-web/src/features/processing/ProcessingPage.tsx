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
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import { hasFailure } from '../../shared/async/asyncState';
import StateRegion, { SupportingRequestNotice } from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import EmptyState from '../../shared/components/EmptyState';
import KeyValue from '../../shared/components/KeyValue';
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

/**
 * A timestamp in the display timezone. While that timezone is still loading the
 * value waits; once it has failed to load, the instant is still stated —
 * explicitly in UTC, as every other surface does — rather than as "—", which
 * would read as "not happened yet" (§14.1: a failure is never an empty answer).
 */
/**
 * What a run's final counts say before, or instead of, existing (§36.2, F19).
 * Counts are recorded only when a run completes, so an active run is told when
 * they arrive and a failed one is told that they never will — never "after
 * completion" for a run that is terminal, never an invented zero, and never a
 * running total that would read as the answer.
 */
function finalCountText(run: { status: string }, finalizing: boolean, finalizationFailed: boolean): string | null {
  if (run.status === 'Completed') return null;
  if (finalizing) return 'Final count after publication';
  if (finalizationFailed) return 'Not published';
  if (run.status === 'Failed') return 'Not produced';
  return 'Final count after completion';
}

function safeFormatTimestamp(value: string | null | undefined, timeZoneId: string | undefined, zoneUnavailable: boolean): string {
  if (!value) return '—';
  if (!timeZoneId) return zoneUnavailable ? displayTimestamp(value) : '—';
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
 * Scene analytics readiness for a completed run is the second primary panel:
 * readiness as text, the facts that readiness supports, and the one action the
 * state calls for. It is the Record archetype's reference (R3).
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
  const zoneState = fromQuery(systemConfig);
  const zoneUnavailable = zoneState.kind === 'unavailable';

  /** The Record's frame, so every terminal state keeps the surface's identity. */
  function frame(name: string, body: ReactNode) {
    return (
      <section className="page">
        <ContextBar surface="processing-detail" object={{ label: name }} />
        <RecordLayout>{body}</RecordLayout>
      </section>
    );
  }

  if (!validId) {
    return frame('Unknown video', <Alert tone="error">The video identifier in this route is invalid.</Alert>);
  }

  // The video this route names, before (or without) its file name: loading, a
  // failed read and a 404 all keep `Processing › {video}` (§5), named by its
  // identifier rather than by a state word or a bare `Video` (§14).
  const videoLabel = video.data?.originalFileName ?? `Video ${videoAssetId.toLowerCase().slice(0, 8)}…`;

  const notFound = (video.error instanceof ApiError && video.error.status === 404)
    || (processing.error instanceof ApiError && processing.error.status === 404);

  if (notFound) {
    // `Not found` is the video's state, said by the alert, not its identity.
    return frame(videoLabel, <Alert tone="error">Video was not found.</Alert>);
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
  const pendingCount = run ? finalCountText(run, finalizing, finalizationFailed) : null;
  // The two requests are two regions (§37.1): the processing status is the
  // primary column, the video metadata is the facts rail. Each states its own
  // failure inside the region it replaces, so neither is reported here.
  // The display timezone is a supporting request with no region of its own:
  // its failure is one notice for the page, with its own Retry (§37.1).
  const hasNotices = Boolean(navigationNotice) || retryFailed || hasFailure(zoneState);
  const notices = (
    <>
      {navigationNotice ? <Alert tone="info">{navigationNotice}</Alert> : null}
      <SupportingRequestNotice
        state={zoneState}
        unavailableMessage="Display timezone is unavailable. Absolute timestamps are shown explicitly in UTC."
        degradedMessage="Display configuration could not be refreshed. The last known timezone remains in use."
        onRetry={() => void systemConfig.refetch()}
        retryLabel="Retry display config"
      />
      {retryFailed ? (
        <Alert tone="error">
          {describeError(retry.error, `Processing could not be queued for ${videoLabel}.`)}
        </Alert>
      ) : null}
    </>
  );

  return (
    <section className="page">
      <ContextBar
        surface="processing-detail"
        object={{ label: videoLabel }}
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
        // The Video facts are this run's identity (file, camera, recorded
        // time): at Tier C they lead (§4.2, §25).
        factsCarryIdentity
        notices={hasNotices ? notices : undefined}
        facts={(
          <>
            <Panel title="Video">
              <StateRegion
                kind="panel"
                state={fromQuery(video)}
                label="video metadata"
                skeleton={{ rows: 7, pitch: 'keyValue' }}
                unavailableMessage={() => 'Video metadata is unavailable.'}
                degradedMessage="Showing the last known video metadata; refreshing failed."
                onRetry={() => video.refetch()}
              >
                {(asset) => (
                  <KeyValue
                    items={[
                      { label: 'File', value: asset.originalFileName },
                      {
                        label: 'Camera',
                        value: (
                          <StateRegion
                            kind="row"
                            state={fromQuery(camera)}
                            label="camera"
                            unavailableMessage={() => 'Camera unavailable'}
                            onRetry={() => camera.refetch()}
                          >
                            {(owner) => `${owner.code} · ${owner.name}`}
                          </StateRegion>
                        ),
                      },
                      { label: 'Recorded', value: safeFormatTimestamp(asset.recordingStartUtc, displayZone, zoneUnavailable) },
                      { label: 'Duration', value: formatDuration(asset.durationMs) },
                      { label: 'Resolution', value: `${asset.width}×${asset.height} · ${frameRateText(asset.frameRateNumerator, asset.frameRateDenominator)}` },
                      { label: 'Codec', value: asset.codecName ?? '—' },
                      { label: 'Camera timezone', value: camera.data?.timeZoneId ?? asset.recordingTimeZoneId, mono: true },
                    ]}
                  />
                )}
              </StateRegion>
            </Panel>

            {/* §16, §30: identifiers are not ordinary operator content. They
                are real and occasionally needed, so they are one disclosure
                away rather than absent. The display timezone is not repeated
                here — the Context Bar states it once for the surface (§24). */}
            {video.data ? (
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
            ) : null}
          </>
        )}
      >

        {/* §16: the run's own state is stated only where it differs from the
            video's, which the Context Bar already carries. Where they agree —
            the ordinary case — a second badge saying "Failed" beside a bar
            already labelled "Failed" is the duplicate §30 names. */}
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
            <StateRegion
              kind="panel"
              state={fromQuery(processing)}
              label="processing status"
              loadingLabel="Loading processing state…"
              unavailableMessage={() => 'Processing status is unavailable.'}
              degradedMessage="Showing the last known processing status; refreshing failed."
              onRetry={() => processing.refetch()}
            >
              {() => run ? (
              <div className="stack">
                {/* A failure leads: it is what the operator came for, and its
                    code and the consequence of retrying sit with it (§15). */}
                {finalizationFailed ? (
                  <Alert tone="error">
                    {FINALIZATION_FAILED_LABEL} after inference completed · <code>{run.failureCode}</code>. Retrying queues a new run for this video.
                  </Alert>
                ) : run.failureCode ? (
                  <Alert tone="error">
                    Processing failed with <code>{run.failureCode}</code>. Retrying queues a new run for this video.
                  </Alert>
                ) : null}

                {/* Finalization has no percentage, and a full inference bar
                    would read as done — or, captioned with a finalization
                    failure, as a bar about publication — so neither a
                    Finalizing run nor a failed finalization draws one. */}
                {finalizing ? (
                  <p>Inference is complete. The results are being finalized and published.</p>
                ) : finalizationFailed ? null : (
                  <Progress
                    value={run.progressPercent}
                    label={isActiveStatus(run.status) ? 'Progress' : run.status}
                    tone={run.status === 'Failed' ? 'err' : run.status === 'Completed' ? 'ok' : 'info'}
                  />
                )}

                <KeyValue
                  grid
                  items={[
                    { label: 'Attempt', value: formatCount(run.attemptCount) },
                    { label: 'Queued', value: safeFormatTimestamp(run.queuedAtUtc, displayZone, zoneUnavailable) },
                    { label: 'Started', value: safeFormatTimestamp(run.startedAtUtc, displayZone, zoneUnavailable) },
                    // A failed run's end is when it failed, not a completion.
                    { label: run.status === 'Failed' ? 'Failed' : 'Completed', value: safeFormatTimestamp(run.completedAtUtc, displayZone, zoneUnavailable) },
                    { label: 'Frames processed', value: pendingCount ?? formatCount(run.framesProcessed) },
                    { label: 'Tracks created', value: pendingCount ?? formatCount(run.tracksCreated) },
                  ]}
                />
              </div>
            ) : (
              <EmptyState icon="activity" title="Not queued" compact>
                Queue processing to make this video searchable.
              </EmptyState>
            )}
            </StateRegion>
          </Panel>

        {/* Scene analytics for the completed run: readiness as text — the run's
            one badge already sits in the Context Bar (§16) — with the action the
            state calls for. Failed retries the unit; Stale offers the camera-level
            re-analysis that exists, stating its camera-wide consequence before the
            click (§15). */}
        {/* Its request is the run's, not the video record's (§37.1: a region
            that does not depend on a failed request still renders). Only the
            camera-wide re-analysis needs the video's camera, so only it waits
            for the facts rail's retry. */}
        {run && run.status === 'Completed' ? (
          <Panel title="Scene analytics">
            <SceneAnalyticsPanel
              readiness={run.analyticsReadiness}
              analytics={analytics.data}
              analyticsUnavailable={fromQuery(analytics).kind === 'unavailable'}
              // A failed poll over details already shown stops polling
              // (`refetchInterval` returns false on error), so it is stated with
              // its retry rather than left reading as "keeps refreshing".
              analyticsRefreshFailed={hasFailure(fromQuery(analytics)) && analytics.data !== undefined}
              // A 404 is the one answer retrying cannot change.
              onRetryAnalyticsDetails={analytics.error instanceof ApiError && analytics.error.status === 404
                ? undefined
                : () => void analytics.refetch()}
              cameraId={cameraId}
              cameraLabel={camera.data ? `${camera.data.code} · ${camera.data.name}` : 'this camera'}
              displayZone={displayZone}
              zoneUnavailable={zoneUnavailable}
              onRetry={() => retryAnalytics.mutate()}
              retrying={retryAnalytics.isPending}
              retryError={retryAnalytics.error}
              onReanalyse={isGuid(cameraId) ? () => reanalyse.mutate() : undefined}
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
  analyticsRefreshFailed = false,
  onRetryAnalyticsDetails,
  cameraId,
  cameraLabel,
  displayZone,
  zoneUnavailable,
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
  /** Details are on screen but their latest refresh failed, so polling has stopped. */
  analyticsRefreshFailed?: boolean;
  /** Re-requests the analysis details whose failure the warning reports. */
  onRetryAnalyticsDetails?: () => void;
  cameraId: string;
  cameraLabel: string;
  displayZone: string | undefined;
  /** The display timezone failed to load: timestamps fall back to explicit UTC. */
  zoneUnavailable: boolean;
  onRetry: () => void;
  retrying: boolean;
  retryError: unknown;
  /** Absent while the video's camera is unknown: the re-analysis is camera-wide. */
  onReanalyse?: () => void;
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
  // The Scene Editor is per camera, and the camera is the video record's. While
  // that record is unavailable there is no editor to open — the camera ledger
  // is not this camera's editor — so the action waits for the facts rail's
  // retry, as the camera-wide re-analysis does.
  const sceneLink = isGuid(cameraId) ? `/cameras/${cameraId.toLowerCase()}/scene` : undefined;

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
              { label: 'Completed', value: safeFormatTimestamp(unit.completedAtUtc, displayZone, zoneUnavailable) },
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
        <Alert tone="warning" actions={onRetryAnalyticsDetails ? <Button size="sm" onClick={onRetryAnalyticsDetails}>Retry</Button> : undefined}>
          Analysis details are unavailable; the readiness above is from the processing status.
        </Alert>
      ) : null}
      {analyticsRefreshFailed ? (
        <Alert tone="warning" actions={onRetryAnalyticsDetails ? <Button size="sm" onClick={onRetryAnalyticsDetails}>Retry</Button> : undefined}>
          Analysis details could not be refreshed, so this page has stopped checking for progress. The details above are the last known
          {onRetryAnalyticsDetails ? '; Retry resumes.' : '.'}
        </Alert>
      ) : null}

      {/* Polling stops on any analytics failure — a first load or a refresh —
          so the page says it keeps refreshing only while it actually does. */}
      {effective === 'Pending' && !analyticsRefreshFailed && !analyticsUnavailable ? (
        <p className="small faint">The analytics host will analyse this run against the active scene revision; this page keeps refreshing until it does.</p>
      ) : null}

      {effective === 'Failed' ? (
        <div className="inline-alert-actions">
          {/* The failure itself is the readiness and its code above; this says
              what the action does before the click (§15). */}
          <Alert tone="error">Retrying starts a new attempt cycle on the same analysis; existing facts are kept until it succeeds.</Alert>
          {/* Secondary (§8.1): analytics exist only for a processed video, whose
              surface primary is the Context Bar's `Open results`. */}
          <Button icon="refresh" onClick={onRetry} disabled={retrying}>
            {retrying ? 'Retrying…' : 'Retry analytics'}
          </Button>
        </div>
      ) : null}
      {retryError ? <Alert tone="error">{describeError(retryError, 'Scene analytics could not be retried.')}</Alert> : null}

      {effective === 'Stale' ? (
        <div className="inline-alert-actions">
          <Alert tone="stale">
            The current scene geometry or analytics engine has not been applied to this run; the earlier facts are kept and stay searchable by their revision.
            {onReanalyse ? <> Re-analysing queues the latest completed run of <strong>every video of {cameraLabel}</strong> against the active revision, not just this one.</> : null}
          </Alert>
          {onReanalyse ? (
            <Button variant="secondary" icon="refresh" onClick={onReanalyse} disabled={reanalysing}>
              {reanalysing ? 'Queueing…' : 'Re-analyse camera'}
            </Button>
          ) : null}
        </div>
      ) : null}
      {reanalyseResult ? (
        <Alert tone="info">
          Re-analysis requested: {formatCount(reanalyseResult.created)} of {formatCount(reanalyseResult.runsInScope)} runs queued; the rest were already analysed, queued or need an explicit retry.
        </Alert>
      ) : null}
      {reanalyseError ? <Alert tone="error">{describeError(reanalyseError, `Re-analysis of ${cameraLabel} could not be requested.`)}</Alert> : null}

      {effective === 'Disabled' ? (
        <div className="inline-alert-actions">
          <Alert tone="info">The active scene revision enables no zone or trip line, so analytics are switched off for this camera on purpose.</Alert>
          {sceneLink ? <ButtonLink size="sm" to={sceneLink}>Open Scene Editor</ButtonLink> : null}
        </div>
      ) : null}
      {effective === 'NotConfigured' ? (
        <div className="inline-alert-actions">
          <Alert tone="info">This camera has no scene configuration yet, so there is nothing to analyse against.</Alert>
          {sceneLink ? <ButtonLink size="sm" to={sceneLink}>Open Scene Editor</ButtonLink> : null}
        </div>
      ) : null}
    </div>
  );
}
