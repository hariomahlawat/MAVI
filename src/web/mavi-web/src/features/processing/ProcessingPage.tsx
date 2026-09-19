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
import Button, { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import KeyValue from '../../shared/components/KeyValue';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import Panel from '../../shared/components/Panel';
import Progress from '../../shared/components/Progress';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, frameRateText } from '../../shared/format/format';
import { isActiveStatus, toneForStatus } from '../../shared/status/status';

function safeFormatTimestamp(value: string | null | undefined, timeZoneId: string | undefined): string {
  if (!value || !timeZoneId) return '—';
  return displayTimestamp(value, timeZoneId);
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

  if (!validId) {
    return (
      <section className="page">
        <PageHeader title="Processing" />
        <Alert tone="error">The video identifier in this route is invalid.</Alert>
      </section>
    );
  }

  const notFound = (video.error instanceof ApiError && video.error.status === 404)
    || (processing.error instanceof ApiError && processing.error.status === 404);

  if (notFound) {
    return (
      <section className="page">
        <PageHeader title="Processing" />
        <Alert tone="error">Video was not found.</Alert>
      </section>
    );
  }

  const state = processing.data;
  const run = state?.latestRun;
  const canRetry = state
    ? state.videoStatus === 'NotQueued' || state.videoStatus === 'Failed' || run?.status === 'Failed'
    : false;
  const processed = state?.videoStatus === 'Processed';
  const displayZone = systemConfig.data?.displayTimeZoneId;
  const navigationNotice = typeof location.state === 'object'
    && location.state !== null
    && 'notice' in location.state
    && typeof location.state.notice === 'string'
      ? location.state.notice
      : null;
  const lowerId = videoAssetId.toLowerCase();

  return (
    <section className="page">
      <PageHeader
        title={video.data?.originalFileName ?? 'Processing'}
        description={video.data ? (
          <>
            {camera.data ? `${camera.data.code} · ${camera.data.name}` : 'Loading camera…'} · recorded {safeFormatTimestamp(video.data.recordingStartUtc, displayZone)}
          </>
        ) : 'Authoritative queue and processing state for the selected source video.'}
        actions={(
          <>
            <ButtonLink to="/processing" variant="ghost" icon="chevronLeft">All processing</ButtonLink>
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
        <div className="split">
          <Panel
            title="Processing run"
            description={run ? `${run.pipeline} · ${run.pipelineVersion}` : 'No run has been queued.'}
            actions={run ? <StatusBadge status={run.status} /> : undefined}
          >
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
                    { label: 'Attempt', value: run.attemptCount },
                    { label: 'Queued', value: safeFormatTimestamp(run.queuedAtUtc, displayZone) },
                    { label: 'Started', value: safeFormatTimestamp(run.startedAtUtc, displayZone) },
                    { label: 'Completed', value: safeFormatTimestamp(run.completedAtUtc, displayZone) },
                    { label: 'Frames processed', value: run.status === 'Completed' ? run.framesProcessed.toLocaleString() : 'Final count after completion' },
                    { label: 'Tracks created', value: run.status === 'Completed' ? run.tracksCreated.toLocaleString() : 'Final count after completion' },
                  ]}
                />

                {run.failureCode ? (
                  <Alert tone="error">
                    <div className="inline-alert-actions">
                      <span>Processing failed with <code>{run.failureCode}</code>. Retrying queues a new run for this video.</span>
                    </div>
                  </Alert>
                ) : null}

                <details className="disclosure">
                  <summary>Diagnostics</summary>
                  <div className="disclosure__body">
                    <KeyValue
                      items={[
                        { label: 'Processing run', value: run.processingRunId, mono: true },
                        { label: 'Worker', value: run.workerId ?? '—', mono: true },
                        { label: 'Video', value: video.data.id, mono: true },
                        { label: 'Display timezone', value: displayZone ?? 'Loading…', mono: true },
                      ]}
                    />
                  </div>
                </details>
              </div>
            ) : (
              <EmptyState icon="activity" title="Not queued" compact>
                Use Queue processing to start the authoritative pipeline for this video.
              </EmptyState>
            )}
          </Panel>

          <div className="stack">
            <Panel title="Video" actions={<StatusBadge status={state.videoStatus} />}>
              <KeyValue
                items={[
                  { label: 'File', value: video.data.originalFileName },
                  { label: 'Camera', value: camera.data ? `${camera.data.code} · ${camera.data.name}` : 'Loading camera…' },
                  { label: 'Recorded', value: safeFormatTimestamp(video.data.recordingStartUtc, displayZone) },
                  { label: 'Duration', value: formatDuration(video.data.durationMs) },
                  { label: 'Resolution', value: `${video.data.width}×${video.data.height} · ${frameRateText(video.data.frameRateNumerator, video.data.frameRateDenominator)}` },
                  { label: 'Codec', value: video.data.codecName ?? '—' },
                  { label: 'Camera timezone', value: camera.data?.timeZoneId ?? video.data.recordingTimeZoneId, mono: true },
                ]}
              />
            </Panel>
            <p className="small faint">
              Video state is <StatusBadge status={state.videoStatus} plain tone={toneForStatus(state.videoStatus)} />
              {run ? <> · latest run <StatusBadge status={run.status} plain /></> : ' · no processing run yet'}
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}
