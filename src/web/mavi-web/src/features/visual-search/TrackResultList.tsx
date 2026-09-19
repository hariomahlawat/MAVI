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
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView?.({ block: 'nearest' });
  }, [selected]);

  return (
    <div
      ref={ref}
      role="option"
      aria-selected={selected}
      tabIndex={-1}
      className="result-row"
      onClick={() => onSelect(track.id.toLowerCase())}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect(track.id.toLowerCase());
        }
      }}
      data-track-id={track.id.toLowerCase()}
    >
      <span className="thumb-frame thumb-frame--md">
        {track.thumbnailContentUrl ? (
          <img className="thumb" src={track.thumbnailContentUrl} alt="" loading="lazy" />
        ) : (
          <span className="thumb-placeholder">No evidence</span>
        )}
      </span>
      <div className="video-title">
        <span className="result-row__title">
          <Icon name={track.objectClass === 'Vehicle' ? 'vehicle' : 'person'} size="sm" />
          <span className="truncate">{track.objectClass} · {track.cameraCode} · {track.cameraName}</span>
        </span>
        <span className="result-row__meta">
          <span><b>{formatDuration(track.durationMs)}</b> from {formatOffset(track.startOffsetMs)}</span>
          <span><b>{formatConfidence(track.meanConfidence)}</b> mean</span>
          <span><b>{track.detectionCount}</b> detections</span>
        </span>
      </div>
      <div className="result-row__side">
        <time dateTime={track.startTimestampUtc}>{displayTimestamp(track.startTimestampUtc, displayTimeZoneId)}</time>
        <span className="row row--nowrap">
          <StatusBadge status={track.reviewStatus} />
          <Link
            className="btn btn--ghost btn--sm btn--icon"
            to={reviewPath(track)}
            onClick={(event) => event.stopPropagation()}
            title="Review evidence"
          >
            <Icon name="external" size="sm" />
            <span className="visually-hidden">Review evidence</span>
          </Link>
        </span>
        <span className="result-row__index">#{index + 1}</span>
      </div>
    </div>
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
    <div className="results__list" role="listbox" aria-label="Track results">
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
    </div>
  );
}
