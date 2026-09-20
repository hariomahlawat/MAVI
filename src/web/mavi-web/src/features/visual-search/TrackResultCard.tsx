import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { TrackSearchItem } from '../../api/tracks';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence } from '../../shared/format/format';
import { reviewPath } from './TrackResultList';

export default function TrackResultCard({
  track,
  displayTimeZoneId,
  selected = false,
  searchContext,
  onSelect,
}: {
  track: TrackSearchItem;
  displayTimeZoneId?: string;
  selected?: boolean;
  searchContext?: string;
  onSelect?: (id: string) => void;
}) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false);

  useEffect(() => {
    setThumbnailFailed(false);
  }, [track.thumbnailContentUrl]);

  const className = ['track-card', onSelect ? 'is-selectable' : '', selected ? 'is-selected' : ''].filter(Boolean).join(' ');

  return (
    <article
      className={className}
      aria-current={selected ? 'true' : undefined}
      onClick={onSelect ? () => onSelect(track.id.toLowerCase()) : undefined}
    >
      <div className="track-card__media">
        {track.thumbnailContentUrl && !thumbnailFailed ? (
          <img
            src={track.thumbnailContentUrl}
            alt={track.objectClass + ' representative evidence from ' + track.cameraCode}
            loading="lazy"
            onError={() => setThumbnailFailed(true)}
          />
        ) : (
          <div className="track-card__placeholder" role="img" aria-label="Representative evidence unavailable">
            Evidence unavailable
          </div>
        )}
      </div>

      <div className="track-card__body">
        <div className="track-card__title-row">
          <strong>{track.objectClass}</strong>
          <StatusBadge status={track.reviewStatus} />
        </div>
        <div className="track-card__camera">{track.cameraCode} · {track.cameraName}</div>
        <time dateTime={track.startTimestampUtc}>
          {displayTimestamp(track.startTimestampUtc, displayTimeZoneId)}
        </time>

        <dl className="track-card__metrics">
          <div><dt>Duration</dt><dd>{formatDuration(track.durationMs)}</dd></div>
          <div><dt>Mean confidence</dt><dd>{formatConfidence(track.meanConfidence, 'list')}</dd></div>
          <div><dt>Detections</dt><dd>{track.detectionCount}</dd></div>
        </dl>

        <Link
          className="btn btn--sm track-card__action"
          to={reviewPath(track, searchContext)}
          onClick={(event) => event.stopPropagation()}
        >
          Review evidence
        </Link>
      </div>
    </article>
  );
}
