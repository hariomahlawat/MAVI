import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { searchTracks } from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import { ButtonLink } from '../../shared/components/Button';
import EmptyState from '../../shared/components/EmptyState';
import Icon from '../../shared/components/Icon';
import LoadingState from '../../shared/components/LoadingState';
import PageHeader from '../../shared/components/PageHeader';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence } from '../../shared/format/format';
import { VIDEO_STATUSES } from '../../shared/status/status';
import { countByStatus } from '../videos/videoRows';

const RECENT_LIMIT = 8;

export default function OverviewPage() {
  const cameras = useQuery({ queryKey: queryKeys.cameras, queryFn: ({ signal }) => listCameras(signal) });
  const videos = useQuery({ queryKey: queryKeys.videos, queryFn: ({ signal }) => listVideos(signal) });
  const systemConfig = useQuery({
    queryKey: queryKeys.systemConfig,
    queryFn: ({ signal }) => getSystemConfig(signal),
    staleTime: 60_000,
  });
  const recent = useQuery({
    queryKey: queryKeys.trackSearch(`overview:limit=${RECENT_LIMIT}`),
    queryFn: ({ signal }) => searchTracks({ limit: RECENT_LIMIT }, signal),
  });
  const displayZone = systemConfig.data?.displayTimeZoneId;

  const counts = videos.data ? countByStatus(videos.data) : null;
  const total = videos.data?.length ?? 0;
  const activeCameras = cameras.data?.filter((camera) => camera.isActive).length ?? 0;

  return (
    <section className="page">
      <PageHeader
        title="Overview"
        description="Where the media stands and what was found most recently."
        actions={(
          <>
            <ButtonLink to="/import" icon="upload">Import video</ButtonLink>
            <ButtonLink to="/search" variant="primary" icon="search">Search tracks</ButtonLink>
          </>
        )}
      />

      {videos.isError ? <Alert tone="error">Video inventory is unavailable.</Alert> : null}

      <div className="stats">
        <Link to="/cameras" className="stat stat--link">
          <span className="stat__label">Cameras</span>
          <span className="stat__value">{cameras.data ? cameras.data.length : '—'}</span>
          <span className="stat__meta">{cameras.data ? `${activeCameras} active` : cameras.isError ? 'unavailable' : 'loading'}</span>
        </Link>
        <Link to="/videos" className="stat stat--link">
          <span className="stat__label">Videos</span>
          <span className="stat__value">{videos.data ? total : '—'}</span>
          <span className="stat__meta">{counts ? `${counts.Processed} processed` : 'loading'}</span>
        </Link>
        <Link to="/processing" className="stat stat--link">
          <span className="stat__label">Processing</span>
          <span className="stat__value">{counts ? counts.Queued + counts.Processing : '—'}</span>
          <span className="stat__meta">{counts ? `${counts.Failed} failed` : 'loading'}</span>
        </Link>
        <Link to="/videos?status=NotQueued" className="stat stat--link">
          <span className="stat__label">Not queued</span>
          <span className="stat__value">{counts ? counts.NotQueued : '—'}</span>
          <span className="stat__meta">awaiting processing</span>
        </Link>
      </div>

      <div className="overview-grid">
        <Panel body="flush" title="Recent tracks" description="Newest completed detections across all cameras" actions={<ButtonLink size="sm" to="/search">All results</ButtonLink>}>
          {recent.isPending ? <div className="panel__body"><LoadingState label="Loading recent tracks…" /></div> : null}
          {recent.isError ? <div className="panel__body"><Alert tone="error">Recent tracks could not be loaded.</Alert></div> : null}
          {recent.data && recent.data.items.length === 0 ? (
            <EmptyState icon="search" title="No tracks yet" compact>Process a video to populate search results.</EmptyState>
          ) : null}
          {recent.data && recent.data.items.length > 0 ? (
            <div className="overview-recent">
              {recent.data.items.map((track) => (
                <Link
                  key={track.id}
                  className="overview-recent__row"
                  to={`/search?videoAssetId=${track.videoAssetId.toLowerCase()}&track=${track.id.toLowerCase()}`}
                >
                  <span className="thumb-frame thumb-frame--sm">
                    {track.thumbnailContentUrl ? (
                      <img className="thumb" src={track.thumbnailContentUrl} alt="" loading="lazy" />
                    ) : <span className="thumb-placeholder">—</span>}
                  </span>
                  <span className="video-title">
                    <span className="overview-recent__title">
                      <Icon name={track.objectClass === 'Vehicle' ? 'vehicle' : 'person'} size="sm" />
                      {track.objectClass}
                      <span className="faint small">{track.cameraCode} · {track.cameraName}</span>
                    </span>
                    <span className="overview-recent__meta">
                      {displayTimestamp(track.startTimestampUtc, displayZone)} · {formatDuration(track.durationMs)} · {formatConfidence(track.meanConfidence, 'list')}
                    </span>
                  </span>
                  <StatusBadge status={track.reviewStatus} />
                </Link>
              ))}
            </div>
          ) : null}
        </Panel>

        <Panel title="Media by status">
          {counts ? (
            <div className="status-breakdown">
              {VIDEO_STATUSES.map((status) => (
                <div key={status} className="status-breakdown__row">
                  <Link to={`/videos?status=${status}`}><StatusBadge status={status} /></Link>
                  <span className="num">{counts[status]}</span>
                  <div className="status-breakdown__bar">
                    <div className="status-breakdown__fill" style={{ width: total ? `${(counts[status] / total) * 100}%` : '0%' }} />
                  </div>
                </div>
              ))}
            </div>
          ) : <LoadingState label="Loading…" />}
        </Panel>
      </div>
    </section>
  );
}
