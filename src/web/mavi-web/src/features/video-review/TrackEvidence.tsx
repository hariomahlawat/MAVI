import { useMemo } from 'react';
import type { TrackDetail } from '../../api/tracks';
import Alert from '../../shared/components/Alert';
import { formatOffset } from '../../shared/format/format';
import EvidencePlayer from '../../shared/evidence/EvidencePlayer';
import type { EvidenceDescription, EvidenceLayer } from '../../shared/evidence/layers';
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
  // Two different facts, and conflating them discarded valid evidence. The
  // worker finalises a Track on one observation — `finalization.py` requires
  // only `observation_count > 0` with a point per observation — so a
  // single-sample trajectory is a persisted position the operator is entitled
  // to see. What one sample cannot support is a *line*: a polyline needs two
  // points, and interpolation needs two to sit between.
  const hasTrajectoryEvidence = Boolean(trajectory && trajectory.length > 0);
  const canDrawTrajectoryPath = Boolean(trajectory && trajectory.length > 1);

  const layers: EvidenceLayer[] = useMemo(() => [
    {
      kind: 'spatial',
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
            + `width ${coordinate(box.width)}, height ${coordinate(box.height)}.`,
          // Applicability, not drawing: the box asserts a position only near the
          // one frame the detector claimed it for. Whether that is on screen
          // also depends on the layer toggle, which is the player's to know.
          appliesNow: isBoxVisibleAt(currentOffsetMs, representative.videoOffsetMs),
          inapplicableReason: 'the playhead is away from the frame it describes',
        }];
      },
    },
    {
      kind: 'spatial',
      id: 'trajectory',
      label: 'Trajectory',
      available: hasTrajectoryEvidence,
      unavailableReason: !detail.trajectoryArtifactId
        ? 'No trajectory was persisted for this Track.'
        : trajectoryError
          ? 'The persisted trajectory could not be loaded.'
          : !hasTrajectoryEvidence
            ? 'The persisted trajectory contains no samples.'
            : undefined,
      render: (frame, currentOffsetMs) => {
        if (!trajectory || trajectory.length === 0) return null;
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
            {/* No segment exists between one sample and itself, so none is
                drawn. A polyline of a single point would be a line the
                evidence does not contain. */}
            {canDrawTrajectoryPath ? (
              <polyline
                className="evidence-track"
                points={projected.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')}
              />
            ) : null}
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
        if (!trajectory || trajectory.length === 0) return [];
        const first = trajectory[0];
        const last = trajectory[trajectory.length - 1];
        const coordinate = (point: TrajectoryPoint) => `x ${point.centerX.toFixed(3)}, y ${point.centerY.toFixed(3)}`;
        const current = trajectoryPositionAt(trajectory, currentOffsetMs);
        // A real trajectory can carry thousands of samples, and an
        // accessibility tree with thousands of entries in it is not accessible.
        // The path is described by its extent and its ends, plus the one
        // position that is actually being asserted right now.
        const items: EvidenceDescription[] = [
          trajectory.length === 1
            ? {
              id: 'trajectory-path',
              label: 'Persisted trajectory',
              // One observation is a complete Track as far as the worker is
              // concerned, so this is evidence, not a degenerate case. It is
              // stated as the single position it is rather than as a path.
              detail: `One persisted sample of the Track centre, at `
                + `${formatOffset(first.offsetMs, 'tenths')}, at ${coordinate(first)}, `
                + 'normalised to the source frame. No line is drawn, because a line needs two samples.',
              appliesNow: true,
            }
            : {
              id: 'trajectory-path',
              label: 'Persisted trajectory',
              detail: `${trajectory.length} samples of the Track centre from `
                + `${formatOffset(first.offsetMs, 'tenths')} to ${formatOffset(last.offsetMs, 'tenths')}. `
                + `Starts at ${coordinate(first)} and ends at ${coordinate(last)}, normalised to the source frame.`,
              appliesNow: true,
            },
        ];
        // Stated in both directions. Outside the sampled range there is no
        // position, and saying so is evidence; dropping the item would leave
        // the operator unable to tell "nothing here" from "nothing described".
        items.push(current
          ? {
            id: 'trajectory-position',
            label: 'Position at the playhead',
            detail: `x ${current.x.toFixed(3)}, y ${current.y.toFixed(3)}, normalised to the source frame. `
              + (hasSampleAt(trajectory, currentOffsetMs)
                ? 'A persisted sample the worker recorded.'
                : 'Interpolated between the two surrounding samples, not a recorded position.'),
            appliesNow: true,
          }
          : {
            id: 'trajectory-position',
            label: 'Position at the playhead',
            detail: 'No position is asserted at this playhead.',
            appliesNow: false,
            inapplicableReason: trajectory.length === 1
              ? 'the playhead is not on the one persisted sample'
              : 'the playhead is outside the sampled range',
          });
        return items;
      },
    },
  ], [detail.objectClass, detail.trajectoryArtifactId, representative, trajectory, trajectoryError, hasTrajectoryEvidence, canDrawTrajectoryPath]);

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
