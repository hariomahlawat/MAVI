import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { getCamera } from '../../api/cameras';
import { ApiError, isGuid } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import {
  getProcessingStatus,
  getVideo,
  processingPollInterval,
  queueProcessing,
} from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
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
import { isActiveStatus } from '../../shared/status/status';
import { ContextBar, RecordLayout } from '../../shared/workspace';

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

  const notices = (
    <>
      {navigationNotice ? <Alert tone="info">{navigationNotice}</Alert> : null}
      {retry.isError && !(retry.error instanceof ApiError && retry.error.code === 'processing_already_active') ? (
        <Alert tone="error">
          {retry.error instanceof ApiError ? `${retry.error.detail} (${retry.error.code})` : 'Processing could not be queued.'}
        </Alert>
      ) : null}
      {video.isError ? <Alert tone="error">Video metadata is unavailable.</Alert> : null}
      {processing.isError ? <Alert tone="error">Processing status is unavailable.</Alert> : null}
    </>
  );
  const hasNotices = Boolean(navigationNotice) || retry.isError || video.isError || processing.isError;

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
            <Panel title="Diagnostics">
              <details className="disclosure">
                <summary>Identifiers</summary>
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

        {video.data && state ? (
          <Panel title="Processing run" actions={run ? <StatusBadge status={run.status} /> : undefined}>
            {run ? (
              <div className="stack">
                <Progress
                  value={run.progressPercent}
                  label={isActiveStatus(run.status) ? 'Progress' : run.status}
                  tone={run.status === 'Failed' ? 'err' : run.status === 'Completed' ? 'ok' : 'info'}
                />

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

                {run.failureCode ? (
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
      </RecordLayout>
    </section>
  );
}
