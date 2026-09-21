import { Link } from 'react-router-dom';
import type { TrackAnalyticsIdentity, TrackSearchItem } from '../../api/tracks';
import Icon from '../../shared/components/Icon';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence, formatOffset } from '../../shared/format/format';
import { selectControlProps, useKeepSelectedVisible } from './resultSelection';

/**
 * Route to the full review of a Track. `searchContext` is the canonical
 * committed search query (without selection); it travels in the URL as `from`
 * so that a refresh or a shared link still returns to the same committed
 * search with this Track selected. Without it the Review page falls back to
 * the Track's video scope.
 */
export function reviewPath(
  track: Pick<TrackSearchItem, 'id' | 'videoAssetId'>,
  searchContext?: string,
  analyticsIdentity?: TrackAnalyticsIdentity,
): string {
  const trackId = track.id.toLowerCase();
  let path = '/review/video/' + track.videoAssetId.toLowerCase() + '?trackId=' + encodeURIComponent(trackId);
  if (searchContext !== undefined) {
    const from = (searchContext ? searchContext + '&' : '') + 'track=' + trackId;
    path += '&from=' + encodeURIComponent(from);
  }
  // The identity the originating analytic search pinned travels beside the
  // return context, not inside it: Review reads the same facts the search
  // showed, and "Back to search" still restores the search as committed.
  if (analyticsIdentity?.sceneRevisionId) {
    path += '&sceneRevisionId=' + encodeURIComponent(analyticsIdentity.sceneRevisionId.toLowerCase());
    if (analyticsIdentity.analyticsAlgorithmVersion) {
      path += '&analyticsAlgorithmVersion=' + encodeURIComponent(analyticsIdentity.analyticsAlgorithmVersion);
    }
  }
  return path;
}

/**
 * One result. The row is a list item with two independent controls: a button
 * that selects the Track for in-place inspection and a link to the full review
 * page. Keeping them siblings (not nested) is what makes the row usable from a
 * keyboard and honest to assistive technology.
 *
 * The select button's identity comes from `resultSelection`, shared with the
 * Grid: the page's key handler knows that contract rather than this markup.
 */
function ResultRow({
  track,
  index,
  selected,
  displayTimeZoneId,
  searchContext,
  analyticsIdentity,
  onSelect,
}: {
  track: TrackSearchItem;
  index: number;
  selected: boolean;
  displayTimeZoneId?: string;
  searchContext?: string;
  analyticsIdentity?: TrackAnalyticsIdentity;
  onSelect: (id: string) => void;
}) {
  // Keeping the selected result on screen is the selection contract's, shared
  // with the Grid card, not this row's own idea (§22).
  const ref = useKeepSelectedVisible<HTMLLIElement>(selected);

  const title = `${track.objectClass} · ${track.cameraCode} · ${track.cameraName}`;
  const select = selectControlProps(track.id, `Select ${title}`, onSelect);

  return (
    <li ref={ref} className="result-row" aria-current={selected ? 'true' : undefined}>
      <button {...select} className={`${select.className} result-row__select`}>
        <span className="thumb-frame thumb-frame--md" aria-hidden="true">
          {track.thumbnailContentUrl ? (
            <img className="thumb" src={track.thumbnailContentUrl} alt="" loading="lazy" />
          ) : (
            <span className="thumb-placeholder">No evidence</span>
          )}
        </span>
        <span className="video-title" aria-hidden="true">
          <span className="result-row__title">
            <Icon name={track.objectClass === 'Vehicle' ? 'vehicle' : 'person'} size="sm" />
            <span className="truncate">{title}</span>
          </span>
          <span className="result-row__meta">
            <span><b>{formatDuration(track.durationMs)}</b> from {formatOffset(track.startOffsetMs)}</span>
            <span><b>{formatConfidence(track.meanConfidence, 'list')}</b> mean</span>
            <span><b>{track.detectionCount}</b> detections</span>
          </span>
        </span>
      </button>
      <div className="result-row__side">
        <time dateTime={track.startTimestampUtc}>{displayTimestamp(track.startTimestampUtc, displayTimeZoneId)}</time>
        <span className="row row--nowrap">
          <StatusBadge status={track.reviewStatus} />
          <Link className="btn btn--ghost btn--sm btn--icon" to={reviewPath(track, searchContext, analyticsIdentity)} title="Review evidence">
            <Icon name="external" size="sm" />
            <span className="visually-hidden">Review evidence</span>
          </Link>
        </span>
        <span className="result-row__index" aria-hidden="true">#{index + 1}</span>
      </div>
    </li>
  );
}

export default function TrackResultList({
  items,
  selectedId,
  displayTimeZoneId,
  searchContext,
  analyticsIdentity,
  onSelect,
}: {
  items: TrackSearchItem[];
  selectedId: string | null;
  displayTimeZoneId?: string;
  searchContext?: string;
  analyticsIdentity?: TrackAnalyticsIdentity;
  onSelect: (id: string) => void;
}) {
  return (
    <ul className="results__list" aria-label="Track results">
      {items.map((track, index) => (
        <ResultRow
          key={track.id}
          track={track}
          index={index}
          selected={selectedId !== null && track.id.toLowerCase() === selectedId}
          displayTimeZoneId={displayTimeZoneId}
          searchContext={searchContext}
          analyticsIdentity={analyticsIdentity}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}
