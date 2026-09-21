import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { TrackAnalyticsIdentity, TrackSearchItem } from '../../api/tracks';
import StatusBadge from '../../shared/components/StatusBadge';
import { formatDuration } from '../../shared/format/duration';
import { displayTimestamp, formatConfidence } from '../../shared/format/format';
import { reviewPath } from './TrackResultList';
import { selectControlProps, useKeepSelectedVisible } from './resultSelection';

/**
 * One result, as a card.
 *
 * Selection used to be an `onClick` on the `<article>`, with the review link
 * nested inside it calling `stopPropagation` to escape. That is unreachable
 * from a keyboard, invisible to assistive technology, and gave the Grid a
 * different selection contract from the List — which is why the page's Enter
 * handler knew the List's class by name and the Grid not at all.
 *
 * The card now carries a real button, the same one `resultSelection` defines
 * for the row. It is a grid item spanning the media and body rows, behind them
 * rather than around them: the heading, time and metrics stay ordinary readable
 * content instead of becoming a button's label, and the card is still one click
 * target. The review link sits in its own row, which the button does not cover,
 * so the two controls do not overlap at all — no stacking order to get right
 * and no `stopPropagation` to escape with.
 *
 * It also keeps itself on screen while selected, through the same hook the row
 * uses. Without it `j` in a dense Grid moved the URL, the inspector and the
 * highlight while leaving the selected card outside the results viewport.
 */
export default function TrackResultCard({
  track,
  displayTimeZoneId,
  selected = false,
  searchContext,
  analyticsIdentity,
  onSelect,
}: {
  track: TrackSearchItem;
  displayTimeZoneId?: string;
  selected?: boolean;
  searchContext?: string;
  analyticsIdentity?: TrackAnalyticsIdentity;
  onSelect?: (id: string) => void;
}) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false);

  useEffect(() => {
    setThumbnailFailed(false);
  }, [track.thumbnailContentUrl]);

  const className = ['track-card', onSelect ? 'is-selectable' : '', selected ? 'is-selected' : ''].filter(Boolean).join(' ');
  const title = `${track.objectClass} · ${track.cameraCode} · ${track.cameraName}`;
  const select = onSelect ? selectControlProps(track.id, `Select ${title}`, onSelect) : null;
  const ref = useKeepSelectedVisible<HTMLElement>(selected);

  return (
    <article ref={ref} className={className} aria-current={selected ? 'true' : undefined}>
      {select ? <button {...select} className={`${select.className} track-card__select`} /> : null}
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

      </div>

      <div className="track-card__foot">
        <Link className="btn btn--sm track-card__action" to={reviewPath(track, searchContext, analyticsIdentity)}>
          Review evidence
        </Link>
      </div>
    </article>
  );
}
