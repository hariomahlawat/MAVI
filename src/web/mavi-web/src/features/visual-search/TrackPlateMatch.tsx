import type { TrackItemPlate } from '../../api/tracks';
import { formatConfidence } from '../../shared/format/format';

/**
 * The facts that qualify a matched reading: how many of the Track's plates
 * support it, its best confidence, and how many other texts were read. The
 * visible line and the result's accessible name are both built from this, so
 * a screen reader hears the same uncertainty the operator sees.
 */
export function plateMatchFacts(plate: TrackItemPlate): string {
  const others = Math.max(0, plate.distinctTextCount - 1);
  return `on ${plate.supportCount} of ${plate.plateObservationCount} plates`
    + ` · ${formatConfidence(plate.maxConfidence, 'list')}`
    + (others > 0 ? ` · ${others} other reading${others === 1 ? '' : 's'}` : '');
}

/** The accessible-name suffix of a plate-matched result, e.g. "Read as X · on 1 of 4 plates · 41% · 2 other readings". */
export function plateMatchAccessibleText(plate: TrackItemPlate): string {
  return `Read as ${plate.matchedText} · ${plateMatchFacts(plate)}`;
}

/** A reading explains a candidate search match; it never confirms a registration. */
export default function TrackPlateMatch({ plate, searchContext }: {
  plate: TrackItemPlate;
  searchContext?: string;
}) {
  const query = searchContext ? new URLSearchParams(searchContext).get('plateText') ?? '' : '';
  const text = plate.matchedText;
  const start = query ? text.indexOf(query) : -1;
  const end = start >= 0 ? start + query.length : 0;
  return (
    <span className="track-plate-match">
      Read as{' '}
      <span className="mono">
        {start >= 0
          ? <>{text.slice(0, start)}<strong><u>{text.slice(start, end)}</u></strong>{text.slice(end)}</>
          : <strong>{text}</strong>}
      </span>
      {' · '}{plateMatchFacts(plate)}
    </span>
  );
}
