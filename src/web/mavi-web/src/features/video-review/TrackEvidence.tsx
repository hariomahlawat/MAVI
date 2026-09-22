import { useMemo } from 'react';
import type { TrackDetail } from '../../api/tracks';
import Alert from '../../shared/components/Alert';
import { formatOffset } from '../../shared/format/format';
import EvidencePlayer from '../../shared/evidence/EvidencePlayer';
import type { EvidenceLayer } from '../../shared/evidence/layers';
import { isBoxVisibleAt, projectBox, projectPoint } from '../../shared/evidence/projection';
import type { EvidenceTimelineInterval, EvidenceTimelineMarker } from '../../shared/evidence/timeline';
import { SUBJECT_LANE } from '../../shared/evidence/timeline';
import { calculateReviewSeekSeconds } from './seek';
import { hasSampleAt, trajectoryPositionAt, type TrajectoryPoint } from './trajectory';

type Props = {
  detail: TrackDetail;
  trajectory?: TrajectoryPoint[];
  /** The trajectory artefact exists but could not be fetched or parsed. */
  trajectoryError?: boolean;
  /** Denser presentation for the Investigation inspector. */
  compact?: boolean;
};

/**
 * Track evidence, composed onto the shared Evidence Player.
 *
 * Everything Track-specific lives here: which overlays exist, what the subject
 * interval is, where the representative frame sits. The player itself knows
 * none of it, which is what lets Scene Analytics add its own layers later
 * without touching the media controller.
 *
 * Every overlay is derived from persisted evidence and nothing else. The
 * representative bounding box is drawn only while the playhead is within a few
 * hundred milliseconds of the frame it describes, because that is the only
 * frame the detector asserted it for. The trajectory is the worker's own
 * sampled centre path; between samples the position is interpolated and says
 * so, and outside the sampled range nothing is drawn at all.
 */
export default function TrackEvidence({ detail, trajectory, trajectoryError = false, compact = false }: Props) {
  const representative = detail.representative;
  const hasTrajectory = Boolean(trajectory && trajectory.length > 1);

  const layers: EvidenceLayer[] = useMemo(() => [
    {
      id: 'bounding-box',
      label: 'Bounding box',
      available: representative !== null,
      unavailableReason: representative === null ? 'No representative frame was persisted for this Track.' : undefined,
      render: (frame, currentOffsetMs) => {
        if (!representative) return null;
        if (!isBoxVisibleAt(currentOffsetMs, representative.videoOffsetMs)) return null;
        const projected = projectBox(representative.boundingBox, frame);
        return (
          <>
            <rect
              className="evidence-box"
              x={projected.x}
              y={projected.y}
              width={projected.width}
              height={projected.height}
              data-testid="bounding-box"
            />
            <text className="evidence-box__label" x={projected.x + 4} y={Math.max(12, projected.y - 6)}>
              {detail.objectClass} · {(representative.confidence * 100).toFixed(0)}%
            </text>
          </>
        );
      },
      describe: (currentOffsetMs) => {
        if (!representative) return [];
        const box = representative.boundingBox;
        const coordinate = (value: number) => value.toFixed(3);
        return [{
          id: 'representative-box',
          label: `${detail.objectClass} representative bounding box`,
          // Normalised source-frame coordinates, which are the evidence; the
          // projected pixels describe this viewport and nothing else.
          detail: `persisted for the frame at ${formatOffset(representative.videoOffsetMs, 'tenths')}, `
            + `${(representative.confidence * 100).toFixed(0)}% confidence. `
            + `Normalised source frame: x ${coordinate(box.x)}, y ${coordinate(box.y)}, `
            + `width ${coordinate(box.width)}, height ${coordinate(box.height)}. `
            + (isBoxVisibleAt(currentOffsetMs, representative.videoOffsetMs)
              ? 'Drawn at the current position.'
              : 'Not drawn here: the playhead is away from the frame it describes.'),
        }];
      },
    },
    {
      id: 'trajectory',
      label: 'Trajectory',
      available: hasTrajectory,
      unavailableReason: !detail.trajectoryArtifactId
        ? 'No trajectory was persisted for this Track.'
        : trajectoryError
          ? 'The persisted trajectory could not be loaded.'
          : !hasTrajectory
            ? 'The persisted trajectory has too few samples to draw.'
            : undefined,
      render: (frame, currentOffsetMs) => {
        if (!trajectory || trajectory.length < 2) return null;
        const projected = trajectory.map((point) => projectPoint(point.centerX, point.centerY, frame));
        // Only a position strictly between two samples is interpolated. On a
        // sample the filled disc already says what the evidence is, and drawing
        // the hollow ring there would present a recorded position in the visual
        // language reserved for a derived one.
        const current = trajectoryPositionAt(trajectory, currentOffsetMs);
        const interpolated = current && !hasSampleAt(trajectory, currentOffsetMs)
          ? projectPoint(current.x, current.y, frame)
          : null;
        return (
          <>
            <polyline
              className="evidence-track"
              points={projected.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')}
            />
            {/*
              Persisted samples are filled discs; the interpolated position between
              them is a hollow ring. The distinction is shape, not opacity: faded
              evidence reads as a rendering fault rather than as uncertainty, and
              confidence is stated as text elsewhere.
            */}
            {projected.map((point, index) => (
              <circle
                key={trajectory[index].offsetMs}
                className="evidence-track__sample"
                r={2.5}
                cx={point.x}
                cy={point.y}
                data-testid="trajectory-sample"
              />
            ))}
            {interpolated ? (
              <circle
                className="evidence-track__interpolated"
                r={5}
                cx={interpolated.x}
                cy={interpolated.y}
                data-testid="trajectory-interpolated"
              />
            ) : null}
          </>
        );
      },
      describe: (currentOffsetMs) => {
        if (!trajectory || trajectory.length < 2) return [];
        const first = trajectory[0];
        const last = trajectory[trajectory.length - 1];
        const coordinate = (point: TrajectoryPoint) => `x ${point.centerX.toFixed(3)}, y ${point.centerY.toFixed(3)}`;
        const current = trajectoryPositionAt(trajectory, currentOffsetMs);
        // A real trajectory can carry thousands of samples, and an
        // accessibility tree with thousands of entries in it is not accessible.
        // The path is described by its extent and its ends, plus the one
        // position that is actually being asserted right now.
        const items = [{
          id: 'trajectory-path',
          label: 'Persisted trajectory',
          detail: `${trajectory.length} samples of the Track centre from `
            + `${formatOffset(first.offsetMs, 'tenths')} to ${formatOffset(last.offsetMs, 'tenths')}. `
            + `Starts at ${coordinate(first)} and ends at ${coordinate(last)}, normalised to the source frame. `
            + 'Nothing is drawn outside that range.',
        }];
        if (current) {
          const exact = hasSampleAt(trajectory, currentOffsetMs);
          items.push({
            id: 'trajectory-position',
            label: 'Position at the playhead',
            detail: `x ${current.x.toFixed(3)}, y ${current.y.toFixed(3)}, normalised to the source frame. `
              + (exact
                ? 'A persisted sample the worker recorded.'
                : 'Interpolated between the two surrounding samples, not a recorded position.'),
          });
        }
        return items;
      },
    },
  ], [detail.objectClass, detail.trajectoryArtifactId, representative, trajectory, trajectoryError, hasTrajectory]);

  const intervals: EvidenceTimelineInterval[] = useMemo(() => [
    {
      id: 'track-' + detail.id,
      startOffsetMs: detail.startOffsetMs,
      endOffsetMs: detail.endOffsetMs,
      label: `Track ${detail.localTrackNumber} interval`,
      lane: SUBJECT_LANE,
    },
  ], [detail.id, detail.startOffsetMs, detail.endOffsetMs, detail.localTrackNumber]);

  const markers: EvidenceTimelineMarker[] = useMemo(() => (
    representative
      ? [{
        id: 'representative-' + representative.observationId,
        offsetMs: representative.videoOffsetMs,
        label: 'Representative frame',
        kind: 'representative',
      }]
      : []
  ), [representative]);

  return (
    <EvidencePlayer
      sourceUrl={detail.video.videoContentUrl}
      declaredDurationMs={detail.video.durationMs}
      declaredWidth={detail.video.width}
      declaredHeight={detail.video.height}
      frameRate={{ numerator: detail.video.frameRateNumerator, denominator: detail.video.frameRateDenominator }}
      subject={{
        label: `${detail.objectClass} Track ${detail.localTrackNumber}`,
        startOffsetMs: detail.startOffsetMs,
        endOffsetMs: detail.endOffsetMs,
      }}
      // No poster. The specification asks for the representative frame as the
      // poster so the frame is never black before metadata, but the only
      // persisted image is the representative *crop*: the worker stores the
      // bounding box cut out of the frame. A poster is stretched across the
      // whole canvas, so that crop would be shown as if it were the source
      // frame, with full-frame overlay coordinates drawn over unrelated pixels
      // — and on a slow or failed load it would stay there. A black matte is
      // honest; false evidence is not. The divergence is declared rather than
      // papered over, and closes when a full-frame artifact exists.
      representative={representative ? { offsetMs: representative.videoOffsetMs } : undefined}
      layers={layers}
      intervals={intervals}
      markers={markers}
      preferenceScope="track"
      compact={compact}
      // Review opens one second before the Track so the operator sees it enter.
      initialOffsetMs={calculateReviewSeekSeconds(detail.startOffsetMs) * 1000}
      seekKey={detail.id}
      notices={trajectoryError ? (
        <Alert tone="warning">
          The persisted trajectory could not be loaded. The Track and its representative frame are unaffected.
        </Alert>
      ) : null}
    />
  );
}
