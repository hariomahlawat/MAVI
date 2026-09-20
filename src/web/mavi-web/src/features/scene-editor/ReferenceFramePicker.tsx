import type { VideoAsset } from '../../api/videos';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import { formatOffset } from '../../shared/format/format';

type Props = {
  videos: VideoAsset[];
  /** The video currently loaded in the canvas, which may not be the saved one. */
  previewVideoId: string | null;
  savedVideoId: string | null;
  savedOffsetMs: number | null;
  readOnly: boolean;
  mediaFailed: boolean;
  onPreviewVideo: (videoAssetId: string | null) => void;
  onUseCurrentFrame: () => void;
  onClear: () => void;
};

/**
 * Choosing the still the operator draws on.
 *
 * Scrubbing is exploration, not a decision: the reference instant changes only
 * when the operator says so. That keeps the saved offset the one they looked
 * at, rather than wherever the playhead drifted to afterwards.
 */
export default function ReferenceFramePicker({
  videos,
  previewVideoId,
  savedVideoId,
  savedOffsetMs,
  readOnly,
  mediaFailed,
  onPreviewVideo,
  onUseCurrentFrame,
  onClear,
}: Props) {
  const savedVideo = savedVideoId ? videos.find((video) => video.id === savedVideoId) ?? null : null;

  if (videos.length === 0) {
    return (
      <div className="stack stack--tight">
        <EmptyState icon="video" title="No videos imported for this camera" compact>
          Geometry can still be drawn on the neutral frame below, but without a still from this camera it is harder
          to place accurately.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="stack stack--tight">
      <label htmlFor="scene-reference-video">
        Reference video
        <select
          id="scene-reference-video"
          value={previewVideoId ?? ''}
          disabled={readOnly}
          onChange={(event) => onPreviewVideo(event.target.value || null)}
        >
          <option value="">No video</option>
          {videos.map((video) => (
            <option key={video.id} value={video.id}>{video.originalFileName}</option>
          ))}
        </select>
      </label>

      {mediaFailed ? (
        <Alert tone="error">
          The reference video could not be loaded. The scene and its reference metadata are unchanged.
        </Alert>
      ) : null}

      <div className="row">
        <Button
          size="sm"
          icon="target"
          disabled={readOnly || !previewVideoId}
          onClick={onUseCurrentFrame}
        >
          Use current frame
        </Button>
        {savedVideoId ? (
          <Button size="sm" variant="ghost" disabled={readOnly} onClick={onClear}>
            Clear reference
          </Button>
        ) : null}
      </div>

      <dl className="scene-properties__detail">
        <dt>Reference frame</dt>
        <dd>
          {savedVideoId && savedOffsetMs !== null
            ? `${savedVideo?.originalFileName ?? savedVideoId} at ${formatOffset(savedOffsetMs)}`
            : 'None set'}
        </dd>
      </dl>
      <p className="field-help">
        Scrub the video to the moment you want, then choose “Use current frame”. Moving the playhead afterwards does not
        change what is saved.
      </p>
    </div>
  );
}
