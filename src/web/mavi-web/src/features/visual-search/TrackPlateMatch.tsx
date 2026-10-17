import type { TrackItemPlate } from '../../api/tracks';
import { formatConfidence } from '../../shared/format/format';

/** A reading explains a candidate search match; it never confirms a registration. */
export default function TrackPlateMatch({ plate, searchContext }: {
  plate: TrackItemPlate;
  searchContext?: string;
}) {
  const query = searchContext ? new URLSearchParams(searchContext).get('plateText') ?? '' : '';
  const text = plate.matchedText;
  const start = query ? text.indexOf(query) : -1;
  const end = start >= 0 ? start + query.length : 0;
  const others = Math.max(0, plate.distinctTextCount - 1);
  return (
    <span className="track-plate-match">
      Read as{' '}
      <span className="mono">
        {start >= 0
          ? <>{text.slice(0, start)}<strong><u>{text.slice(start, end)}</u></strong>{text.slice(end)}</>
          : <strong>{text}</strong>}
      </span>
      {' · on '}{plate.supportCount} of {plate.plateObservationCount} plates
      {' · '}{formatConfidence(plate.maxConfidence, 'list')}
      {others > 0 ? ` · ${others} other reading${others === 1 ? '' : 's'}` : null}
    </span>
  );
}
