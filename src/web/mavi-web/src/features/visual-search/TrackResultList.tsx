import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { TrackSearchItem } from '../../api/tracks';
import Icon from '../../shared/components/Icon';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence, formatOffset } from '../../shared/format/format';

export function reviewPath(track: TrackSearchItem): string {
  return '/review/video/' + track.videoAssetId.toLowerCase() + '?trackId=' + encodeURIComponent(track.id.toLowerCase());
}

/**
 * One result. The row is a list item with two independent controls: a
 * button that selects the Track for in-place inspection and a link to the
 * full review page. Keeping them siblings (not nested) is what makes the row
 * usable from a keyboard and honest to assistive technology.
 */
function ResultRow({
  track,
  index,
  selected,
  displayTimeZoneId,
  onSelect,
}: {
  track: TrackSearchItem;
  index: number;
  selected: boolean;
  displayTimeZoneId?: string;
  onSelect: (id: string) => void;
}) {
  const ref = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView?.({ block: 'nearest' });
  }, [selected]);

  const title = `${track.objectClass} · ${track.cameraCode} · ${track.cameraName}`;

  return (
    <li ref={ref} className="result-row" aria-current={selected ? 'true' : undefined} data-track-id={track.id.toLowerCase()}>
      <button type="button" className="result-row__select" aria-label={`Select ${title}`} onClick={() => onSelect(track.id.toLowerCase())}>
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
            <span><b>{formatConfidence(track.meanConfidence)}</b> mean</span>
            <span><b>{track.detectionCount}</b> detections</span>
          </span>
        </span>
      </button>
      <div className="result-row__side">
        <time dateTime={track.startTimestampUtc}>{displayTimestamp(track.startTimestampUtc, displayTimeZoneId)}</time>
        <span className="row row--nowrap">
          <StatusBadge status={track.reviewStatus} />
          <Link className="btn btn--ghost btn--sm btn--icon" to={reviewPath(track)} title="Review evidence">
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
  onSelect,
}: {
  items: TrackSearchItem[];
  selectedId: string | null;
  displayTimeZoneId?: string;
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
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}
