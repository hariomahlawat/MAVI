import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ApiError, isGuid } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { getTrack } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import { formatDuration } from '../../shared/format/duration';
import { formatInstant } from '../../shared/time/time';
import { seekVideoToTrack } from './seek';

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

function displayTimestamp(value: string | null | undefined, displayTimeZoneId?: string): string {
  if (!value) return '—';
  if (!displayTimeZoneId) return value + ' UTC';
  try {
    return formatInstant(value, displayTimeZoneId, {
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

export default function VideoReviewPage() {
  const { videoAssetId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const trackIds = searchParams.getAll('trackId');
  const trackId = trackIds.length === 1 ? trackIds[0] : '';
  const validVideoId = isGuid(videoAssetId);
  const validTrackId = trackIds.length === 1 && isGuid(trackId);

  const track = useQuery({
    queryKey: queryKeys.track(trackId),
    queryFn: ({ signal }) => getTrack(trackId, signal),
    enabled: validVideoId && validTrackId,
    retry: shouldRetryQuery,
  });

  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    enabled: validVideoId && validTrackId,
    staleTime: 60_000,
  });

  const detail = track.data;
  const identityMismatch = Boolean(detail && detail.videoAssetId.toLowerCase() !== videoAssetId.toLowerCase());
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [mediaFailed, setMediaFailed] = useState(false);
  const [thumbnailFailed, setThumbnailFailed] = useState(false);

  useEffect(() => {
    setMediaFailed(false);
  }, [detail?.video.videoContentUrl]);

  useEffect(() => {
    setThumbnailFailed(false);
  }, [detail?.representative?.thumbnailContentUrl]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !detail || identityMismatch) return;

    let active = true;
    const applySeek = () => {
      if (active) seekVideoToTrack(video, detail.startOffsetMs);
    };

    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      applySeek();
    } else {
      video.addEventListener('loadedmetadata', applySeek);
    }

    return () => {
      active = false;
      video.removeEventListener('loadedmetadata', applySeek);
    };
  }, [detail?.id, detail?.startOffsetMs, detail?.video.videoContentUrl, identityMismatch]);

  if (!validVideoId) {
    return (
      <section className="page-stack">
        <PageHeader title="Evidence Review" />
        <Alert tone="error">The video identifier in this route is invalid.</Alert>
      </section>
    );
  }

  if (!validTrackId) {
    return (
      <section className="page-stack">
        <PageHeader title="Evidence Review" />
        <Alert tone="error">
          Exactly one valid Track identifier is required in the trackId query parameter.
        </Alert>
      </section>
    );
  }

  if (track.error instanceof ApiError && track.error.status === 404) {
    return (
      <section className="page-stack">
        <PageHeader title="Evidence Review" />
        <Alert tone="error">Track was not found.</Alert>
      </section>
    );
  }

  if (identityMismatch) {
    return (
      <section className="page-stack">
        <PageHeader title="Evidence Review" />
        <Alert tone="error">
          The selected Track does not belong to the video identified by this review route.
        </Alert>
      </section>
    );
  }

  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId;

  return (
    <section className="page-stack">
      <PageHeader
        title="Evidence Review"
        description="Inspect the authoritative Track, representative evidence and source video around the detected interval."
        actions={<Link className="button button--secondary" to="/search">Visual Search</Link>}
      />

      {systemConfig.isError ? (
        <Alert tone="warning">
          Display timezone is unavailable. Absolute timestamps are shown explicitly in UTC.
        </Alert>
      ) : null}

      {track.isPending ? <LoadingState label="Loading Track evidence…" /> : null}
      {track.isError && !(track.error instanceof ApiError && track.error.status === 404) ? (
        <Alert tone="error">
          {track.error instanceof ApiError
            ? track.error.detail + ' (' + track.error.code + ')'
            : 'Track evidence could not be loaded.'}
        </Alert>
      ) : null}

      {detail ? (
        <div className="review-layout">
          <section className="panel review-player-panel">
            <div className="panel__header">
              <div>
                <h2>Source video</h2>
                <p>
                  Opens one second before Track start when possible. Playback uses the authoritative range-capable source-video endpoint.
                </p>
              </div>
              <span className="status-pill status-pill--muted">{detail.reviewStatus}</span>
            </div>

            <video
              key={detail.video.videoContentUrl}
              ref={videoRef}
              className="review-video"
              src={detail.video.videoContentUrl}
              controls
              preload="metadata"
              aria-label="Source video evidence"
              onError={() => setMediaFailed(true)}
            >
              Your browser does not support HTML video playback.
            </video>

            {mediaFailed ? (
              <Alert tone="error">Source video could not be loaded from the evidence API.</Alert>
            ) : null}

            <dl className="detail-grid review-video-meta">
              <div><dt>Track start</dt><dd>{displayTimestamp(detail.startTimestampUtc, displayTimeZoneId)}</dd></div>
              <div><dt>Track end</dt><dd>{displayTimestamp(detail.endTimestampUtc, displayTimeZoneId)}</dd></div>
              <div><dt>Track duration</dt><dd>{formatDuration(detail.durationMs)}</dd></div>
              <div><dt>Video duration</dt><dd>{formatDuration(detail.video.durationMs)}</dd></div>
              <div><dt>Resolution</dt><dd>{detail.video.width}×{detail.video.height}</dd></div>
              <div><dt>Display timezone</dt><dd><code>{displayTimeZoneId ?? 'UTC fallback'}</code></dd></div>
            </dl>
          </section>

          <aside className="review-sidebar">
            <section className="panel">
              <div className="panel__header">
                <div>
                  <h2>Representative evidence</h2>
                  <p>{detail.objectClass} · {detail.camera.code} · {detail.camera.name}</p>
                </div>
              </div>

              {detail.representative?.thumbnailContentUrl && !thumbnailFailed ? (
                <img
                  className="review-thumbnail"
                  src={detail.representative.thumbnailContentUrl}
                  alt={detail.objectClass + ' representative evidence from ' + detail.camera.code}
                  onError={() => setThumbnailFailed(true)}
                />
              ) : (
                <div className="review-thumbnail-placeholder" role="img" aria-label="Representative evidence unavailable">
                  Representative evidence unavailable
                </div>
              )}

              <dl className="detail-grid detail-grid--single review-details">
                <div><dt>Track ID</dt><dd><code>{detail.id}</code></dd></div>
                <div><dt>Local Track</dt><dd>{detail.localTrackNumber}</dd></div>
                <div><dt>Object class</dt><dd>{detail.objectClass}</dd></div>
                <div><dt>Detection count</dt><dd>{detail.detectionCount}</dd></div>
                <div><dt>Mean confidence</dt><dd>{(detail.meanConfidence * 100).toFixed(1)}%</dd></div>
                <div><dt>Max confidence</dt><dd>{(detail.maxConfidence * 100).toFixed(1)}%</dd></div>
                <div><dt>Review status</dt><dd>{detail.reviewStatus}</dd></div>
              </dl>
            </section>

            <section className="panel">
              <div className="panel__header">
                <div>
                  <h2>Processing provenance</h2>
                  <p>Stable operator-facing identities from the completed run.</p>
                </div>
              </div>
              <dl className="detail-grid detail-grid--single review-details">
                <div><dt>Pipeline</dt><dd>{detail.processing.pipelineVersion}</dd></div>
                <div><dt>Detector</dt><dd>{detail.processing.detectorName ?? '—'} · {detail.processing.detectorVersion ?? '—'}</dd></div>
                <div><dt>Tracker</dt><dd>{detail.processing.trackerName ?? '—'} · {detail.processing.trackerVersion ?? '—'}</dd></div>
                <div><dt>Completed</dt><dd>{displayTimestamp(detail.processing.completedAtUtc, displayTimeZoneId)}</dd></div>
                {detail.representative ? (
                  <>
                    <div><dt>Source frame</dt><dd>{detail.representative.sourceFrameNumber}</dd></div>
                    <div><dt>Video offset</dt><dd>{formatDuration(detail.representative.videoOffsetMs)}</dd></div>
                    <div><dt>Representative confidence</dt><dd>{(detail.representative.confidence * 100).toFixed(1)}%</dd></div>
                    <div><dt>Quality score</dt><dd>{detail.representative.qualityScore.toFixed(3)}</dd></div>
                  </>
                ) : null}
              </dl>
            </section>
          </aside>
        </div>
      ) : null}
    </section>
  );
}
