import { useCallback, useEffect, useState, type RefObject } from 'react';
import type { VideoAsset } from '../../api/videos';
import Button from '../../shared/components/Button';
import { formatOffset } from '../../shared/format/format';

type Props = {
  videos: VideoAsset[];
  videoRef: RefObject<HTMLVideoElement | null>;
  previewVideoId: string | null;
  savedVideoId: string | null;
  savedOffsetMs: number | null;
  readOnly: boolean;
  onPreviewVideo: (videoAssetId: string | null) => void;
  /** Called with the instant the operator is looking at, read from the element itself. */
  onUseCurrentFrame: (offsetMs: number) => void;
  onClear: () => void;
};

/**
 * Media transport, kept off the spatial surface.
 *
 * Scrubbing and editing are different activities, so they have different
 * controls in different places: the frame above is only for geometry, and
 * everything that moves the playhead lives here.
 *
 * The playhead and the saved reference frame are shown as two separate
 * readings, because they are two separate things. The reference moves only when
 * the operator says "Use current frame"; afterwards they can scrub freely and
 * still see, and return to, what will actually be saved.
 */
export default function ReferenceFrameBar({
  videos,
  videoRef,
  previewVideoId,
  savedVideoId,
  savedOffsetMs,
  readOnly,
  onPreviewVideo,
  onUseCurrentFrame,
  onClear,
}: Props) {
  const [playheadMs, setPlayheadMs] = useState(0);
  const [durationMs, setDurationMs] = useState(0);
  const [playing, setPlaying] = useState(false);

  // `timeupdate` is coarse but this is a scrubber, not an overlay: a few
  // updates a second is the right rate and costs nothing.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) {
      setPlayheadMs(0);
      setDurationMs(0);
      setPlaying(false);
      return;
    }
    const publish = () => setPlayheadMs(Number.isFinite(video.currentTime) ? video.currentTime * 1000 : 0);
    const publishDuration = () => setDurationMs(Number.isFinite(video.duration) ? video.duration * 1000 : 0);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);

    publish();
    publishDuration();
    video.addEventListener('timeupdate', publish);
    video.addEventListener('seeked', publish);
    video.addEventListener('loadedmetadata', publishDuration);
    video.addEventListener('durationchange', publishDuration);
    video.addEventListener('play', onPlay);
    video.addEventListener('playing', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('ended', onPause);
    return () => {
      video.removeEventListener('timeupdate', publish);
      video.removeEventListener('seeked', publish);
      video.removeEventListener('loadedmetadata', publishDuration);
      video.removeEventListener('durationchange', publishDuration);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('playing', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('ended', onPause);
    };
  }, [videoRef, previewVideoId]);

  const seekTo = useCallback((offsetMs: number) => {
    const video = videoRef.current;
    if (!video) return;
    const limit = Number.isFinite(video.duration) ? Math.max(0, video.duration - 0.001) : Number.POSITIVE_INFINITY;
    video.currentTime = Math.min(Math.max(0, offsetMs / 1000), limit);
    setPlayheadMs(video.currentTime * 1000);
  }, [videoRef]);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play()?.catch(() => undefined);
    else video.pause();
  }, [videoRef]);

  const selectedVideo = videos.find((item) => item.id === previewVideoId);
  const savedVideo = savedVideoId ? videos.find((item) => item.id === savedVideoId) : undefined;
  const total = durationMs || selectedVideo?.durationMs || 0;
  const referencePinned = savedVideoId !== null && savedOffsetMs !== null;
  const showingReference = referencePinned
    && savedVideoId === previewVideoId
    && Math.abs(playheadMs - (savedOffsetMs as number)) < 250;

  if (videos.length === 0) {
    return (
      <div className="scene-reference scene-reference--empty">
        <span>No imported video for this camera. Geometry is still saved in normalised coordinates.</span>
      </div>
    );
  }

  return (
    <div className="scene-reference">
      <label className="scene-reference__video">
        <span className="visually-hidden">Reference video</span>
        <select
          aria-label="Reference video"
          value={previewVideoId ?? ''}
          disabled={readOnly}
          onChange={(event) => onPreviewVideo(event.target.value || null)}
        >
          <option value="">No video</option>
          {videos.map((item) => (
            <option key={item.id} value={item.id}>{item.originalFileName}</option>
          ))}
        </select>
      </label>

      <Button
        size="sm"
        iconOnly
        icon="play"
        disabled={!previewVideoId}
        aria-pressed={playing}
        title={playing ? 'Pause' : 'Play'}
        onClick={togglePlay}
      >
        {playing ? 'Pause' : 'Play'}
      </Button>

      <input
        className="scene-reference__scrub"
        type="range"
        aria-label="Reference video timeline"
        min={0}
        max={Math.max(1, Math.round(total))}
        step={40}
        value={Math.min(Math.round(playheadMs), Math.max(1, Math.round(total)))}
        disabled={!previewVideoId}
        onChange={(event) => seekTo(Number(event.target.value))}
      />

      <span className="scene-reference__time">
        <span className="visually-hidden">Playhead </span>
        {formatOffset(playheadMs)}
      </span>

      <Button
        size="sm"
        icon="target"
        disabled={readOnly || !previewVideoId}
        onClick={() => {
          // Read the element rather than the polled state: a seek that has not
          // yet fired timeupdate must still pin the frame the operator sees.
          const video = videoRef.current;
          const current = video && Number.isFinite(video.currentTime) ? video.currentTime * 1000 : playheadMs;
          onUseCurrentFrame(Math.max(0, Math.round(current)));
        }}
      >
        Use current frame
      </Button>

      <span className="scene-reference__pinned">
        {referencePinned ? (
          <>
            <span className={`scene-reference__badge${showingReference ? ' is-current' : ''}`}>
              Reference · {formatOffset(savedOffsetMs as number)}
            </span>
            <span className="scene-reference__file">{savedVideo?.originalFileName ?? 'video unavailable'}</span>
          </>
        ) : (
          <span className="scene-reference__badge is-empty">No reference frame</span>
        )}
      </span>

      {referencePinned && !readOnly ? (
        <>
          <Button
            size="sm"
            variant="ghost"
            disabled={showingReference}
            onClick={() => {
              // The operator is most likely to want this when they are lost,
              // which includes being on the wrong video. Switching back is
              // part of going there; the seek follows once the metadata for
              // the reference video has arrived.
              if (savedVideoId !== previewVideoId) onPreviewVideo(savedVideoId);
              else seekTo(savedOffsetMs as number);
            }}
          >
            Go to reference
          </Button>
          <Button size="sm" variant="ghost" icon="x" iconOnly onClick={onClear}>Clear reference frame</Button>
        </>
      ) : null}
    </div>
  );
}
