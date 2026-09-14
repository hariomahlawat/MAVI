import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { TrackSearchItem } from '../../api/tracks';
import { formatDuration } from '../../shared/format/duration';
import { formatInstant } from '../../shared/time/time';

function displayTimestamp(value: string, displayTimeZoneId?: string): string {
  if (!displayTimeZoneId) return value + ' UTC';
  try {
    return formatInstant(value, displayTimeZoneId, {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
  } catch {
    return 'Invalid timestamp';
  }
}

export default function TrackResultCard({
  track,
  displayTimeZoneId,
}: {
  track: TrackSearchItem;
  displayTimeZoneId?: string;
}) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false);

  useEffect(() => {
    setThumbnailFailed(false);
  }, [track.thumbnailContentUrl]);

  return (
    <article className="track-card">
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
          <span className="status-pill status-pill--muted">{track.reviewStatus}</span>
        </div>
        <div className="track-card__camera">{track.cameraCode} · {track.cameraName}</div>
        <time dateTime={track.startTimestampUtc}>
          {displayTimestamp(track.startTimestampUtc, displayTimeZoneId)}
        </time>

        <dl className="track-card__metrics">
          <div><dt>Duration</dt><dd>{formatDuration(track.durationMs)}</dd></div>
          <div><dt>Mean confidence</dt><dd>{(track.meanConfidence * 100).toFixed(1)}%</dd></div>
          <div><dt>Detections</dt><dd>{track.detectionCount}</dd></div>
        </dl>

        <Link
          className="button button--secondary track-card__action"
          to={'/review/video/' + track.videoAssetId + '?trackId=' + encodeURIComponent(track.id)}
        >
          Review evidence
        </Link>
      </div>
    </article>
  );
}
