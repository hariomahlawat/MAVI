import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { TrackDetail } from '../../api/tracks';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import { formatOffset } from '../../shared/format/format';
import { contentRect, isBoxVisibleAt, projectBox, projectPoint, type PixelRect } from './overlay';
import { seekVideoToTrack } from './seek';
import { trajectoryPositionAt, type TrajectoryPoint } from './trajectory';

type Props = {
  detail: TrackDetail;
  trajectory?: TrajectoryPoint[];
  trajectoryError?: boolean;
  /** Compact variant for the inspector pane. */
  compact?: boolean;
};

type Overlay = { showBox: boolean; showTrajectory: boolean };

/**
 * The source video with the Track's evidence drawn on it.
 *
 * Every overlay is derived from persisted evidence and nothing else: the
 * representative bounding box is drawn only while the playhead is within a few
 * hundred milliseconds of the frame it describes, and the trajectory is the
 * worker's own sampled centre path. Between samples the current position is
 * interpolated; outside the sampled range nothing is drawn.
 */
export default function TrackEvidencePlayer({ detail, trajectory, trajectoryError = false, compact = false }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [mediaFailed, setMediaFailed] = useState(false);
  const [currentMs, setCurrentMs] = useState(detail.startOffsetMs);
  const [box, setBox] = useState<PixelRect>({ x: 0, y: 0, width: 0, height: 0 });
  const [frame, setFrame] = useState<PixelRect>({ x: 0, y: 0, width: 0, height: 0 });
  const [overlay, setOverlay] = useState<Overlay>({ showBox: true, showTrajectory: true });

  useEffect(() => {
    setMediaFailed(false);
  }, [detail.video.videoContentUrl]);

  // Seek to one second before the Track when metadata is available. Re-runs
  // when the Track changes on the same video so a cached detail reseeks now.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    let active = true;
    const applySeek = () => {
      if (active) seekVideoToTrack(video, detail.startOffsetMs);
    };

    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      applySeek();
    } else {
      video.addEventListener('loadedmetadata', applySeek, { once: true });
    }
    return () => {
      active = false;
      video.removeEventListener('loadedmetadata', applySeek);
    };
  }, [detail.id, detail.startOffsetMs, detail.video.videoContentUrl]);

  // Overlay geometry follows the rendered element, not the intrinsic frame.
  const measure = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const width = video.clientWidth;
    const height = video.clientHeight;
    const intrinsicWidth = video.videoWidth || detail.video.width;
    const intrinsicHeight = video.videoHeight || detail.video.height;
    setBox({ x: 0, y: 0, width, height });
    setFrame(contentRect(width, height, intrinsicWidth, intrinsicHeight));
  }, [detail.video.width, detail.video.height]);

  useLayoutEffect(() => {
    measure();
    const video = videoRef.current;
    if (!video) return;
    video.addEventListener('loadedmetadata', measure);
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(measure);
      observer.observe(video);
    } else {
      window.addEventListener('resize', measure);
    }
    return () => {
      video.removeEventListener('loadedmetadata', measure);
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [measure]);

  // Track the playhead at frame rate while playing; `timeupdate` alone is too
  // coarse (~250 ms) for a box that is visible for 400 ms. Exactly one frame
  // loop exists per media element: `start` always cancels a previous loop,
  // seeking and time updates only publish the position, and pause/end/unmount
  // stop it. The <video> is keyed by source URL, so a source change unmounts
  // this element and the cleanup below runs.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let handle = 0;
    const publish = () => setCurrentMs(video.currentTime * 1000);
    const stop = () => {
      if (handle !== 0) window.cancelAnimationFrame(handle);
      handle = 0;
    };
    const tick = () => {
      publish();
      handle = !video.paused && !video.ended ? window.requestAnimationFrame(tick) : 0;
    };
    const start = () => {
      stop();
      handle = window.requestAnimationFrame(tick);
    };
    const onPlay = () => start();
    const onStop = () => { stop(); publish(); };
    const onSeeked = () => {
      publish();
      // A seek during playback keeps the loop; a seek while paused needs none.
      if (!video.paused && !video.ended && handle === 0) start();
    };
    video.addEventListener('play', onPlay);
    video.addEventListener('playing', onPlay);
    video.addEventListener('pause', onStop);
    video.addEventListener('ended', onStop);
    video.addEventListener('emptied', onStop);
    video.addEventListener('seeked', onSeeked);
    video.addEventListener('timeupdate', publish);
    return () => {
      stop();
      video.removeEventListener('play', onPlay);
      video.removeEventListener('playing', onPlay);
      video.removeEventListener('pause', onStop);
      video.removeEventListener('ended', onStop);
      video.removeEventListener('emptied', onStop);
      video.removeEventListener('seeked', onSeeked);
      video.removeEventListener('timeupdate', publish);
    };
  }, [detail.video.videoContentUrl]);

  const seekTo = useCallback((offsetMs: number) => {
    const video = videoRef.current;
    if (!video) return;
    const duration = Number.isFinite(video.duration) ? video.duration : detail.video.durationMs / 1000;
    video.currentTime = Math.min(Math.max(0, offsetMs / 1000), Math.max(0, duration - 0.001));
    setCurrentMs(video.currentTime * 1000);
  }, [detail.video.durationMs]);

  const representative = detail.representative;
  const boxVisible = Boolean(representative && overlay.showBox && isBoxVisibleAt(currentMs, representative.videoOffsetMs));
  const projected = representative ? projectBox(representative.boundingBox, frame) : null;
  const trajectoryPoints = overlay.showTrajectory && trajectory && trajectory.length > 1 ? trajectory : null;
  const current = trajectoryPoints ? trajectoryPositionAt(trajectoryPoints, currentMs) : null;

  const totalMs = detail.video.durationMs;
  const percent = (ms: number) => (totalMs > 0 ? `${Math.min(100, Math.max(0, (ms / totalMs) * 100))}%` : '0%');

  return (
    <div className="stack stack--tight">
      <div className={compact ? 'player player--fill' : 'player'} ref={frameRef}>
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

        {box.width > 0 && box.height > 0 ? (
          <svg
            className="player__overlay"
            viewBox={`0 0 ${box.width} ${box.height}`}
            width={box.width}
            height={box.height}
            aria-hidden="true"
            data-testid="evidence-overlay"
          >
            {trajectoryPoints ? (
              <polyline
                points={trajectoryPoints
                  .map((point) => projectPoint(point.centerX, point.centerY, frame))
                  .map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`)
                  .join(' ')}
              />
            ) : null}
            {current ? (
              <circle className="trajectory-current" r={5} cx={projectPoint(current.x, current.y, frame).x} cy={projectPoint(current.x, current.y, frame).y} />
            ) : null}
            {boxVisible && projected ? (
              <>
                <rect x={projected.x} y={projected.y} width={projected.width} height={projected.height} data-testid="bounding-box" />
                <text className="bbox-label" x={projected.x + 4} y={Math.max(12, projected.y - 6)}>
                  {detail.objectClass} · {(representative!.confidence * 100).toFixed(0)}%
                </text>
              </>
            ) : null}
          </svg>
        ) : null}
      </div>

      {mediaFailed ? <Alert tone="error">Source video could not be loaded from the evidence API.</Alert> : null}

      <div className="timeline" aria-hidden="true">
        <div className="timeline__track" />
        <div
          className="timeline__interval"
          style={{ left: percent(detail.startOffsetMs), width: `calc(${percent(detail.endOffsetMs)} - ${percent(detail.startOffsetMs)})` }}
          title="Track interval"
        />
        {representative ? <div className="timeline__marker" style={{ left: percent(representative.videoOffsetMs) }} title="Representative frame" /> : null}
        <div className="timeline__playhead" style={{ left: percent(currentMs) }} />
      </div>
      <div className="timeline__labels" aria-hidden="true">
        <span>0:00</span>
        <span>{formatOffset(currentMs)} / {formatOffset(totalMs)}</span>
      </div>

      <div className="player-controls">
        <Button size="sm" icon="skipStart" onClick={() => seekTo(detail.startOffsetMs)} title="Jump to Track start">
          Start {formatOffset(detail.startOffsetMs)}
        </Button>
        {representative ? (
          <Button size="sm" icon="target" onClick={() => seekTo(representative.videoOffsetMs)} title="Jump to the representative frame">
            Evidence {formatOffset(representative.videoOffsetMs)}
          </Button>
        ) : null}
        <Button size="sm" icon="skipEnd" onClick={() => seekTo(detail.endOffsetMs)} title="Jump to Track end">
          End {formatOffset(detail.endOffsetMs)}
        </Button>
        <span className="grow" />
        <label className="checkbox">
          <input type="checkbox" checked={overlay.showBox} onChange={(event) => setOverlay((value) => ({ ...value, showBox: event.target.checked }))} />
          Bounding box
        </label>
        <label className="checkbox" title={trajectory ? `${trajectory.length} samples` : undefined}>
          <input
            type="checkbox"
            checked={overlay.showTrajectory}
            disabled={!trajectory}
            onChange={(event) => setOverlay((value) => ({ ...value, showTrajectory: event.target.checked }))}
          />
          Trajectory{trajectoryError ? ' (unavailable)' : !detail.trajectoryArtifactId ? ' (none)' : ''}
        </label>
      </div>
    </div>
  );
}
