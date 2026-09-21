import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { searchTracks } from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import { ButtonLink } from '../../shared/components/Button';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import EmptyState from '../../shared/components/EmptyState';
import Icon from '../../shared/components/Icon';
import LoadingState from '../../shared/components/LoadingState';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence, formatCount } from '../../shared/format/format';
import { VIDEO_STATUSES } from '../../shared/status/status';
import { ContextBar, LedgerSummaryLayout } from '../../shared/workspace';
import { countByStatus } from '../videos/videoRows';

const RECENT_LIMIT = 8;

/**
 * Overview — the §4.1.1 Ledger-summary variant, and the only Ledger permitted
 * to stay centred at `--content-max`.
 *
 * It is a summary and attention surface: what the deployment currently holds,
 * and what was found most recently. The four readouts are deliberately not
 * cards. §11 is explicit that a summary or stat readout is neither a scroll
 * boundary nor an editable region, so it earns no border — and §30 lists
 * dashboard-card proliferation among the things the product must not drift
 * into. What is contained here is what genuinely is a container: the recent
 * Tracks list, and the media-status breakdown.
 *
 * Every section degrades on its own. Four independent requests feed this page,
 * and one of them failing must not blank the three that answered (§14).
 */
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

  // A figure the request failed to produce says so; it never renders as a
  // zero, which would read as an answer (§14).
  const cameraMeta = cameras.data ? `${activeCameras} active` : cameras.isError ? 'unavailable' : 'loading';
  const videoMeta = counts ? `${counts.Processed} processed` : videos.isError ? 'unavailable' : 'loading';

  return (
    <section className="page page--workspace">
      <ContextBar
        crumbs={[{ label: 'Overview' }]}
        status={<DisplayTimeZone timeZoneId={displayZone} />}
        actions={(
          <>
            <ButtonLink to="/import" icon="upload">Import video</ButtonLink>
            <ButtonLink to="/search" variant="primary" icon="search">Search tracks</ButtonLink>
          </>
        )}
      />

      <LedgerSummaryLayout
        notices={videos.isError ? (
          <Alert tone="error">Video inventory is unavailable; media figures cannot be shown.</Alert>
        ) : null}
      >
        <div className="summary-band">
          <Link to="/cameras" className="summary-band__item">
            <span className="summary-band__label">Cameras</span>
            <span className="summary-band__value">{cameras.data ? formatCount(cameras.data.length) : '—'}</span>
            <span className="summary-band__meta">{cameraMeta}</span>
          </Link>
          <Link to="/videos" className="summary-band__item">
            <span className="summary-band__label">Videos</span>
            <span className="summary-band__value">{videos.data ? formatCount(total) : '—'}</span>
            <span className="summary-band__meta">{videoMeta}</span>
          </Link>
          <Link to="/processing" className="summary-band__item">
            <span className="summary-band__label">Processing</span>
            <span className="summary-band__value">{counts ? formatCount(counts.Queued + counts.Processing) : '—'}</span>
            <span className="summary-band__meta">{counts ? `${counts.Failed} failed` : videoMeta}</span>
          </Link>
          <Link to="/videos?status=NotQueued" className="summary-band__item">
            <span className="summary-band__label">Not queued</span>
            <span className="summary-band__value">{counts ? formatCount(counts.NotQueued) : '—'}</span>
            <span className="summary-band__meta">awaiting processing</span>
          </Link>
        </div>

        <div className="overview-grid">
          <Panel
            body="flush"
            title="Recent tracks"
            actions={<ButtonLink size="sm" to="/search">All results</ButtonLink>}
          >
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
                    <span className="num">{formatCount(counts[status])}</span>
                    <div className="status-breakdown__bar">
                      <div className="status-breakdown__fill" style={{ width: total ? `${(counts[status] / total) * 100}%` : '0%' }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : videos.isError ? (
              <EmptyState icon="alert" title="Media status unavailable" compact hatched>
                The video inventory could not be read, so its distribution cannot be shown.
              </EmptyState>
            ) : <LoadingState label="Loading…" />}
          </Panel>
        </div>
      </LedgerSummaryLayout>
    </section>
  );
}
