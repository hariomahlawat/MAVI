import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import { formatDuration } from '../../shared/format/duration';
import { formatInstant } from '../../shared/time/time';

function safeFormatTimestamp(value: string | null | undefined, timeZoneId: string | undefined): string {
  if (!value || !timeZoneId) return '—';
  try {
    return formatInstant(value, timeZoneId, {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
  } catch {
    return 'Invalid timestamp';
  }
}

function statusTone(status: string): string {
  if (status === 'Processed' || status === 'Completed') return 'status-pill--ok';
  if (status === 'Failed') return 'status-pill--error';
  if (status === 'Queued' || status === 'Processing' || status === 'Running') return 'status-pill--active';
  return 'status-pill--muted';
}

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
    refetchInterval: (query) => processingPollInterval(query.state.data),
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

  if (!validId) {
    return (
      <section className="page-stack">
        <PageHeader title="Processing" />
        <Alert tone="error">The video identifier in this route is invalid.</Alert>
      </section>
    );
  }

  const notFound = (video.error instanceof ApiError && video.error.status === 404)
    || (processing.error instanceof ApiError && processing.error.status === 404);

  if (notFound) {
    return (
      <section className="page-stack">
        <PageHeader title="Processing" />
        <Alert tone="error">Video was not found.</Alert>
      </section>
    );
  }

  const state = processing.data;
  const run = state?.latestRun;
  const progress = Math.min(100, Math.max(0, run?.progressPercent ?? 0));
  const canRetry = state
    ? state.videoStatus === 'NotQueued'
      || state.videoStatus === 'Failed'
      || run?.status === 'Failed'
    : false;
  const displayZone = systemConfig.data?.displayTimeZoneId;
  const navigationNotice = typeof location.state === 'object'
    && location.state !== null
    && 'notice' in location.state
    && typeof location.state.notice === 'string'
      ? location.state.notice
      : null;

  return (
    <section className="page-stack">
      <PageHeader
        title="Processing"
        description="Authoritative queue and processing state for the selected source video."
        actions={canRetry ? (
          <button className="button button--primary" type="button" onClick={() => retry.mutate()} disabled={retry.isPending}>
            {retry.isPending ? 'Queueing…' : state?.videoStatus === 'Failed' ? 'Retry processing' : 'Queue processing'}
          </button>
        ) : undefined}
      />

      {navigationNotice ? <Alert tone="info">{navigationNotice}</Alert> : null}
      {retry.isError && !(retry.error instanceof ApiError && retry.error.code === 'processing_already_active') ? (
        <Alert tone="error">
          {retry.error instanceof ApiError ? `${retry.error.detail} (${retry.error.code})` : 'Processing could not be queued.'}
        </Alert>
      ) : null}
      {video.isError && !notFound ? <Alert tone="error">Video metadata is unavailable.</Alert> : null}
      {processing.isError && !notFound ? <Alert tone="error">Processing status is unavailable.</Alert> : null}

      {(video.isPending || processing.isPending) ? <LoadingState label="Loading processing state…" /> : null}

      {video.data && state ? (
        <>
          <div className="summary-grid">
            <section className="panel metric-card">
              <span className="metric-card__label">Video</span>
              <strong>{video.data.originalFileName}</strong>
              <span>{formatDuration(video.data.durationMs)} · {video.data.width}×{video.data.height}</span>
            </section>
            <section className="panel metric-card">
              <span className="metric-card__label">Camera</span>
              <strong>{camera.data ? `${camera.data.code} · ${camera.data.name}` : 'Loading camera…'}</strong>
              <span>{camera.data?.timeZoneId ?? video.data.recordingTimeZoneId}</span>
            </section>
            <section className="panel metric-card">
              <span className="metric-card__label">Video state</span>
              <strong><span className={`status-pill ${statusTone(state.videoStatus)}`}>{state.videoStatus}</span></strong>
              <span>{run ? `Latest run: ${run.status}` : 'No processing run yet'}</span>
            </section>
          </div>

          <section className="panel">
            <div className="panel__header">
              <div>
                <h2>Processing run</h2>
                <p>{run ? `${run.pipeline} · ${run.pipelineVersion}` : 'No run has been queued.'}</p>
              </div>
              {run ? <span className={`status-pill ${statusTone(run.status)}`}>{run.status}</span> : null}
            </div>

            {run ? (
              <>
                <div className="progress-block">
                  <div className="progress-block__label">
                    <span>Progress</span>
                    <strong>{progress.toFixed(progress % 1 === 0 ? 0 : 1)}%</strong>
                  </div>
                  <progress max="100" value={progress}>{progress}%</progress>
                </div>

                <dl className="detail-grid">
                  <div><dt>Attempt</dt><dd>{run.attemptCount}</dd></div>
                  <div><dt>Queued</dt><dd>{safeFormatTimestamp(run.queuedAtUtc, displayZone)}</dd></div>
                  <div><dt>Started</dt><dd>{safeFormatTimestamp(run.startedAtUtc, displayZone)}</dd></div>
                  <div><dt>Completed</dt><dd>{safeFormatTimestamp(run.completedAtUtc, displayZone)}</dd></div>
                  <div><dt>Display timezone</dt><dd><code>{displayZone ?? 'Loading…'}</code></dd></div>
                  <div><dt>Failure code</dt><dd>{run.failureCode ?? '—'}</dd></div>
                </dl>

                {run.workerId ? (
                  <details className="diagnostics">
                    <summary>Diagnostics</summary>
                    <dl className="detail-grid">
                      <div><dt>Processing run ID</dt><dd><code>{run.processingRunId}</code></dd></div>
                      <div><dt>Worker ID</dt><dd><code>{run.workerId}</code></dd></div>
                    </dl>
                  </details>
                ) : null}
              </>
            ) : (
              <div className="empty-state">
                <strong>Not queued</strong>
                <span>Use Queue processing to start the authoritative pipeline.</span>
              </div>
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}
