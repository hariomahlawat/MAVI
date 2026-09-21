import { useQuery } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import { getTrack, type TrackSearchItem } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import LoadingState from '../../shared/components/LoadingState';
import StatusBadge from '../../shared/components/StatusBadge';
import { Inspector } from '../../shared/workspace';
import { RepresentativeEvidence, TrackSummary } from '../video-review/TrackDetailsPanels';
import TrackEvidencePlayer from '../video-review/TrackEvidencePlayer';
import { useTrajectory } from '../video-review/useTrajectory';
import { reviewPath } from './TrackResultList';

type Props = {
  trackId: string;
  position: number; // 0-based index in loaded results, -1 when not in the list
  total: number;
  hasMore: boolean;
  displayTimeZoneId?: string;
  /** Canonical committed search query, carried into the full review link. */
  searchContext?: string;
  summary?: TrackSearchItem;
  onPrevious: () => void;
  onNext: () => void;
  onClose: () => void;
};

/**
 * In-place review of the selected result. The player and evidence panels are
 * the same components the full Review page uses, so what the operator sees
 * here is exactly what they will see there — just narrower.
 *
 * UI-4 moves it onto the shared `Inspector` shell: the boundary, the padding
 * and the single scrolling body are the archetype's (§20), and what is shown
 * inside is this feature's. It also settles where the camera line lives. The
 * old panel put it in the header as a description, which made the header two
 * lines tall in a drawer that has 480px to work with; it is a fact about the
 * Track rather than chrome naming the region, so it now opens the body.
 */
export default function TrackInspector({
  trackId,
  position,
  total,
  hasMore,
  displayTimeZoneId,
  searchContext,
  summary,
  onPrevious,
  onNext,
  onClose,
}: Props) {
  const track = useQuery({
    queryKey: queryKeys.track(trackId),
    queryFn: ({ signal }) => getTrack(trackId, signal),
    retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1,
  });
  const detail = track.data;
  const trajectory = useTrajectory(detail?.trajectoryArtifactId ?? null, detail?.trajectoryContentUrl ?? null);

  const title = detail ? `${detail.objectClass} · Track ${detail.localTrackNumber}` : summary ? `${summary.objectClass}` : 'Track';
  const canPrevious = position > 0;
  const canNext = position >= 0 && (position < total - 1 || hasMore);

  const cameraLine = detail
    ? `${detail.camera.code} · ${detail.camera.name}`
    : summary ? `${summary.cameraCode} · ${summary.cameraName}` : null;

  return (
    <Inspector
      label="Track inspector"
      title={title}
      actions={(
        <div className="track-inspector__nav">
          <Button size="sm" iconOnly icon="chevronLeft" onClick={onPrevious} disabled={!canPrevious} title="Previous result (k / ↑)">Previous result</Button>
          <span className="track-inspector__pos" aria-live="polite">{position >= 0 ? `${position + 1} / ${total}${hasMore ? '+' : ''}` : '— / ' + total}</span>
          <Button size="sm" iconOnly icon="chevronRight" onClick={onNext} disabled={!canNext} title="Next result (j / ↓)">Next result</Button>
          {detail ? (
            <ButtonLink size="sm" to={reviewPath({ id: detail.id, videoAssetId: detail.videoAssetId }, searchContext)} icon="external" title="Open full review (Enter)">
              Open
            </ButtonLink>
          ) : null}
          <Button size="sm" iconOnly icon="x" onClick={onClose} title="Close inspector (Esc)">Close inspector</Button>
        </div>
      )}
    >
      <div className="stack">
        {cameraLine ? <p className="track-inspector__camera">{cameraLine}</p> : null}
        {track.isPending ? <LoadingState label="Loading Track evidence…" /> : null}
        {track.isError ? (
          // §14.1: a failed request is a state the operator can act on. A 404
          // is the one failure retrying cannot mend — the Track is not there —
          // so that one is stated without a control that would only fail again.
          <Alert
            tone="error"
            actions={track.error instanceof ApiError && track.error.status === 404
              ? undefined
              : <Button size="sm" icon="refresh" onClick={() => void track.refetch()}>Retry</Button>}
          >
            {track.error instanceof ApiError
              ? track.error.status === 404 ? 'Track was not found.' : `${track.error.detail} (${track.error.code})`
              : 'Track evidence could not be loaded.'}
          </Alert>
        ) : null}
        {detail ? (
          <>
            <TrackEvidencePlayer detail={detail} trajectory={trajectory.data} trajectoryError={trajectory.isError} compact />
            <div className="row row--between">
              <StatusBadge status={detail.reviewStatus} />
              <span className="small faint">Local track {detail.localTrackNumber} · <code>{detail.id.slice(0, 8)}…</code></span>
            </div>
            <TrackSummary detail={detail} displayTimeZoneId={displayTimeZoneId} />
            <details className="disclosure">
              <summary>Representative frame</summary>
              <div className="disclosure__body">
                <RepresentativeEvidence detail={detail} />
              </div>
            </details>
          </>
        ) : null}
      </div>
    </Inspector>
  );
}
