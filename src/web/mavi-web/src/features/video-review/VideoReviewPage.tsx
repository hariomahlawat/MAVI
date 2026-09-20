import { useQuery } from '@tanstack/react-query';
import { useParams, useSearchParams } from 'react-router-dom';
import { ApiError, isGuid } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { getTrack } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { ProvenancePanel, RepresentativeEvidence, TrackIdentity, TrackSummary } from './TrackDetailsPanels';
import TrackEvidencePlayer from './TrackEvidencePlayer';
import { returnToSearchPath } from './returnContext';
import { useTrajectory } from './useTrajectory';

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

function Invalid({ message }: { message: string }) {
  return (
    <section className="page">
      <PageHeader title="Evidence Review" />
      <Alert tone="error">{message}</Alert>
    </section>
  );
}

export default function VideoReviewPage() {
  const { videoAssetId: rawVideoAssetId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const trackIds = searchParams.getAll('trackId');
  const rawTrackId = trackIds.length === 1 ? trackIds[0] : '';
  const validVideoId = isGuid(rawVideoAssetId);
  const validTrackId = trackIds.length === 1 && isGuid(rawTrackId);
  const videoAssetId = validVideoId ? rawVideoAssetId.toLowerCase() : '';
  const trackId = validTrackId ? rawTrackId.toLowerCase() : '';

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
  const trajectory = useTrajectory(
    detail && !identityMismatch ? detail.trajectoryArtifactId : null,
    detail && !identityMismatch ? detail.trajectoryContentUrl : null,
  );

  if (!validVideoId) return <Invalid message="The video identifier in this route is invalid." />;
  if (!validTrackId) return <Invalid message="Exactly one valid Track identifier is required in the trackId query parameter." />;
  if (track.error instanceof ApiError && track.error.status === 404) return <Invalid message="Track was not found." />;
  if (identityMismatch) return <Invalid message="The selected Track does not belong to the video identified by this review route." />;

  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId;
  const backToSearch = returnToSearchPath(searchParams.get('from'), videoAssetId, trackId);

  return (
    <section className="page">
      <PageHeader
        title={detail ? `${detail.objectClass} · Track ${detail.localTrackNumber}` : 'Evidence Review'}
        description={detail
          ? `${formatDuration(detail.durationMs)} of ${detail.video.width}×${detail.video.height} source video · ${detail.detectionCount} detections`
          : 'Inspect the authoritative Track, representative evidence and source video around the detected interval.'}
        actions={(
          <>
            <ButtonLink to={backToSearch} icon="chevronLeft">Back to search</ButtonLink>
            <ButtonLink to="/search" variant="ghost">Visual Search</ButtonLink>
          </>
        )}
      />

      {systemConfig.isError ? (
        <Alert tone="warning">
          <div className="inline-alert-actions">
            <span>Display timezone is unavailable. Absolute timestamps are shown explicitly in UTC.</span>
            <Button size="sm" onClick={() => void systemConfig.refetch()}>Retry display config</Button>
          </div>
        </Alert>
      ) : null}

      {track.isPending ? <LoadingState label="Loading Track evidence…" /> : null}
      {track.isError && !(track.error instanceof ApiError && track.error.status === 404) ? (
        <Alert tone="error">
          {track.error instanceof ApiError ? track.error.detail + ' (' + track.error.code + ')' : 'Track evidence could not be loaded.'}
        </Alert>
      ) : null}

      {detail ? (
        <div className="review-layout">
          <Panel
            title="Source video"
            description="Opens one second before Track start. Bounding box and trajectory are drawn from persisted evidence only."
            actions={<StatusBadge status={detail.reviewStatus} />}
          >
            <TrackEvidencePlayer detail={detail} trajectory={trajectory.data} trajectoryError={trajectory.isError} />
            <div style={{ marginTop: 'var(--s-4)' }}>
              <TrackSummary detail={detail} displayTimeZoneId={displayTimeZoneId} />
            </div>
          </Panel>

          <div className="stack">
            <Panel title="Representative evidence" description="Persisted representative frame and stable Track identity.">
              <div className="stack">
                <RepresentativeEvidence detail={detail} />
                <TrackIdentity detail={detail} displayTimeZoneId={displayTimeZoneId} />
              </div>
            </Panel>
            <ProvenancePanel detail={detail} displayTimeZoneId={displayTimeZoneId} />
          </div>
        </div>
      ) : null}
    </section>
  );
}
