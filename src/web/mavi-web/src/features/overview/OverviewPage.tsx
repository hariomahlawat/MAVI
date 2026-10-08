import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { searchTracks } from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { fromQuery } from '../../shared/async/fromQuery';
import { useEffect, useMemo, useState } from 'react';
import { hasFailure } from '../../shared/async/asyncState';
import StateRegion, { SupportingRequestNotice } from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import DisplayTimeZone from '../../shared/components/DisplayTimeZone';
import Icon from '../../shared/components/Icon';
import Panel from '../../shared/components/Panel';
import EvidencePlaceholder from '../../shared/evidence/EvidencePlaceholder';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence, formatCount } from '../../shared/format/format';
import { VIDEO_STATUSES } from '../../shared/status/status';
import { ContextBar, LedgerSummaryLayout } from '../../shared/workspace';
import { useVideoProcessing } from '../videos/useVideoProcessing';
import { countByStatus } from '../videos/videoRows';
import { attentionLookupIds, evaluateAttention } from './attention';
import AttentionRegion from './AttentionRegion';

const RECENT_LIMIT = 8;

/**
 * Overview — the §4.1.1 Ledger-summary variant, and the only Ledger permitted
 * to stay centred at `--content-max`.
 *
 * It is attention-first (§4.1.1, amended in v2.0): the first region is what
 * needs the operator's attention — failed processing, failed or stale scene
 * analytics, media awaiting processing — each row linking to the surface that
 * acts on it (`attention.ts` says what each condition rests on, and what is
 * deliberately not claimed). The status readouts and the recent Tracks follow.
 * The three readouts are deliberately not
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
  // A supporting request with no region of its own (§37.1): timestamps fall
  // back to explicit UTC, and the page says so once, with its own Retry.
  const zoneState = fromQuery(systemConfig);

  // The bounded status lookups the attention region reads, through the
  // per-video cache the Videos and Processing ledgers share.
  const lookupIds = useMemo(() => (videos.data ? attentionLookupIds(videos.data) : []), [videos.data]);
  const processing = useVideoProcessing(lookupIds);
  const evaluation = useMemo(() => {
    if (!videos.data) return null;
    const looked = new Set(lookupIds);
    return evaluateAttention({
      videos: videos.data,
      cameraCodes: cameras.data ? new Map(cameras.data.map((camera) => [camera.id, camera.code])) : null,
      lookup: (id) => (looked.has(id) ? processing.stateOf(id) : undefined),
    });
  }, [videos.data, cameras.data, lookupIds, processing]);

  /** Whether the attention region shows its final content: the inventory and its lookups have answered. */
  const attentionSettled = videos.isError || (evaluation !== null && evaluation.pendingLookups === 0);

  const counts = videos.data ? countByStatus(videos.data) : null;
  const total = videos.data?.length ?? 0;
  const activeCameras = cameras.data?.filter((camera) => camera.isActive).length ?? 0;

  // A figure the request failed to produce says so; it never renders as a
  // zero, which would read as an answer (§14).
  // Each figure is a row-level reading of its request (§37.1, row), selected
  // by the same normalized boundary as every region: loading says so, a failure
  // says unavailable, and only real data becomes a number.
  const camerasState = fromQuery(cameras);
  const videosState = fromQuery(videos);
  const figureMeta = (kind: 'loading' | 'unavailable' | 'ready', ready: string) =>
    kind === 'ready' ? ready : kind === 'unavailable' ? 'unavailable' : 'loading';
  const cameraMeta = figureMeta(camerasState.kind, `${formatCount(activeCameras)} active`);
  const videoMeta = figureMeta(videosState.kind, counts ? `${formatCount(counts.Processed)} processed` : '');

  /**
   * One notice for the whole partial failure of the summary band (§14).
   *
   * Overview is four independent requests, and any of them can fail on its own.
   * A dash and the word "unavailable" in a summary figure is not the treatment
   * §14 asks for — that is an alert, in the operator's words, with a retry — but
   * one alert per failed request stacks into noise the moment two fail. So the
   * band's failures are named together in a single notice with one retry, which
   * re-requests exactly the ones that failed. The two panels below are regions
   * of their own and carry their own state (§37.1).
   */
  type FailedSource = { readonly subject: string; readonly refetch: () => void };
  const failed: FailedSource[] = [
    camerasState.kind === 'unavailable' ? { subject: 'camera inventory', refetch: () => { void cameras.refetch(); } } : null,
    videosState.kind === 'unavailable' ? { subject: 'video inventory', refetch: () => { void videos.refetch(); } } : null,
  ].filter((entry): entry is FailedSource => entry !== null);

  const unavailableNotice = failed.length === 0 ? null : (
    <Alert
      tone="error"
      // One retry for the whole notice, re-requesting exactly what failed: a
      // per-source button would put the operator back in the alert stack this
      // notice exists to avoid.
      actions={<Button size="sm" onClick={() => failed.forEach((entry) => entry.refetch())}>Retry</Button>}
    >
      {failed.length === 1
        ? `The ${failed[0].subject} is unavailable; its figures cannot be shown.`
        : `The ${failed[0].subject} and the ${failed[1].subject} are unavailable; their figures cannot be shown.`}
    </Alert>
  );

  return (
    <section className="page page--workspace">
      <ContextBar
        surface="overview"
        status={<DisplayTimeZone timeZoneId={displayZone} />}
        actions={(
          <>
            <ButtonLink to="/import" icon="upload">Import video</ButtonLink>
            <ButtonLink to="/search" variant="primary" icon="search">Search tracks</ButtonLink>
          </>
        )}
      />

      <LedgerSummaryLayout
        notices={unavailableNotice || hasFailure(camerasState) || hasFailure(videosState) || hasFailure(zoneState) ? (
          <>
            {unavailableNotice}
            {/* The display timezone has no region of its own (§37.1): timestamps
                fall back to explicit UTC, and the page says so once. */}
            <SupportingRequestNotice
              state={zoneState}
              unavailableMessage="Display timezone is unavailable. Absolute timestamps are shown explicitly in UTC."
              degradedMessage="Display configuration could not be refreshed. The last known timezone remains in use."
              onRetry={() => void systemConfig.refetch()}
              retryLabel="Retry display config"
            />
            {/* A refresh that failed over figures still on screen: the figures
                stay, and say they may be out of date (§14.1, degraded). */}
            {camerasState.kind === 'ready' ? (
              <SupportingRequestNotice
                state={camerasState}
                unavailableMessage={null}
                degradedMessage="Showing the last known camera inventory; refreshing it failed."
                onRetry={() => void cameras.refetch()}
              />
            ) : null}
            {videosState.kind === 'ready' ? (
              <SupportingRequestNotice
                state={videosState}
                unavailableMessage={null}
                degradedMessage="Showing the last known video inventory; refreshing it failed."
                onRetry={() => void videos.refetch()}
              />
            ) : null}
          </>
        ) : null}
      >
        <AttentionRegion
          videos={videosState}
          evaluation={attentionSettled ? evaluation : null}
          onRetryLookups={() => processing.errors.forEach((_, id) => processing.retry(id))}
        />

        {/* Content arrival moves nothing (§36.3, §38): the attention region is
            first, and its height is known only once the video inventory and
            its bounded status lookups have answered — so the regions below it
            render then, rather than being pushed down when it grows. A failed
            inventory or lookup has answered too, so a failure never holds the
            rest of the page; on first load, recent Tracks wait for that answer. */}
        {attentionSettled ? (
          <>

          {/* The readouts summarise; what needs acting on — failures, media not
              yet queued — is the attention region's, and is stated there once. */}
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
              <span className="summary-band__meta">{counts ? 'queued or running' : videoMeta}</span>
            </Link>
          </div>

          <div className="overview-grid">
            <Panel
              body="flush"
              title="Recent tracks"
              actions={<ButtonLink size="sm" to="/search">All results</ButtonLink>}
            >
              <StateRegion
                kind="column"
                state={fromQuery(recent)}
                label="recent tracks"
                skeleton={{ rows: RECENT_LIMIT, pitch: 'compactList' }}
                isEmpty={(page) => page.items.length === 0}
                empty={{ icon: 'search', title: 'No tracks yet', body: 'Process a video to populate search results.' }}
                unavailableMessage={() => 'Recent tracks are unavailable.'}
                degradedMessage="Showing the last known recent tracks; refreshing failed."
                onRetry={() => recent.refetch()}
              >
                {(page) => (
                <div className="overview-recent">
                  {page.items.map((track) => (
                    <Link
                      key={track.id}
                      className="overview-recent__row"
                      to={`/search?videoAssetId=${track.videoAssetId.toLowerCase()}&track=${track.id.toLowerCase()}`}
                    >
                      <span className="thumb-frame thumb-frame--sm">
                        <RecentThumbnail url={track.thumbnailContentUrl} />
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
                )}
              </StateRegion>
            </Panel>

            <Panel title="Media by status">
              {/* The same request as the band's video figures; its one alert is
                  the band's notice above, so this region says only that it
                  cannot be drawn (§14.1: one cause, one alert). */}
              <StateRegion
                kind="panel"
                state={fromQuery(videos)}
                label="media status"
                causeAnnouncedElsewhere
                unavailableMessage={() => 'The video inventory could not be read, so its distribution cannot be shown.'}
              >
                {(all) => {
                  const byStatus = countByStatus(all);
                  return (
                <div className="status-breakdown">
                  {VIDEO_STATUSES.map((status) => (
                    <div key={status} className="status-breakdown__row">
                      <Link to={`/videos?status=${status}`}><StatusBadge status={status} /></Link>
                      <span className="num">{formatCount(byStatus[status])}</span>
                      <div className="status-breakdown__bar">
                        <div className="status-breakdown__fill" style={{ width: all.length ? `${(byStatus[status] / all.length) * 100}%` : '0%' }} />
                      </div>
                    </div>
                  ))}
                </div>
                  );
                }}
              </StateRegion>
            </Panel>
          </div>
          </>
        ) : null}
      </LedgerSummaryLayout>
    </section>
  );
}

/**
 * A recent Track's thumbnail. One that fails to load is the same condition as
 * one never persisted and reads the same: the evidence placeholder, never a
 * broken image (§37.1, media).
 */
function RecentThumbnail({ url }: { url: string | null | undefined }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [url]);
  return url && !failed
    ? <img className="thumb" src={url} alt="" loading="lazy" onError={() => setFailed(true)} />
    : <EvidencePlaceholder dense />;
}
