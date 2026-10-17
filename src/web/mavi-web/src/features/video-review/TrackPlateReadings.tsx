import { useEffect, useRef, useState } from 'react';
import type { TrackDetail, TrackPlateObservation } from '../../api/tracks';
import { EVIDENCE_PLAYER_ATTRIBUTE } from '../../shared/evidence/EvidencePlayer';
import { formatConfidence, formatOffset } from '../../shared/format/format';
import { EVIDENCE_ROLE_LABELS } from './evidenceSet';

type Props = {
  detail: TrackDetail;
  compact?: boolean;
  matchedText?: string;
  onSelectObservation?: (sourceObservationId: string, offsetMs: number) => void;
};

/**
 * Cuts only the detector's exact pixel rectangle from the accepted, server-URL
 * source crop. A mismatching decoded image is not a candidate for rescaling:
 * it is missing evidence, and the UI says "No image" instead.
 */
export function PlateRegion({ detail, plate }: { detail: TrackDetail; plate: TrackPlateObservation }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'missing'>('loading');
  const source = detail.observations.find((item) => item.observationId === plate.sourceObservationId);
  const url = source?.evidenceContentUrl;
  const box = plate.box;
  useEffect(() => {
    setState('loading');
    if (!url || !canvas.current || !Number.isInteger(box.x) || !Number.isInteger(box.y)
        || !Number.isInteger(box.width) || !Number.isInteger(box.height)
        || box.width < 1 || box.height < 1 || box.x < 0 || box.y < 0
        || box.x + box.width > box.cropWidth || box.y + box.height > box.cropHeight) {
      setState('missing');
      return;
    }
    let active = true;
    const image = new Image();
    image.onload = () => {
      if (!active) return;
      const element = canvas.current;
      if (!element || image.naturalWidth !== box.cropWidth || image.naturalHeight !== box.cropHeight) {
        setState('missing');
        return;
      }
      const context = element.getContext('2d');
      if (!context) { setState('missing'); return; }
      element.width = box.width;
      element.height = box.height;
      context.drawImage(image, box.x, box.y, box.width, box.height, 0, 0, box.width, box.height);
      setState('ready');
    };
    image.onerror = () => { if (active) setState('missing'); };
    image.src = url;
    return () => { active = false; image.onload = null; image.onerror = null; };
  }, [url, box.x, box.y, box.width, box.height, box.cropWidth, box.cropHeight]);
  return (
    <span className="plate-region" aria-label={state === 'ready' ? 'Plate region from accepted evidence' : 'Plate image'}>
      <canvas ref={canvas} role="img" aria-label="Detected plate region" hidden={state !== 'ready'}
        style={{ maxWidth: '100%', height: 'auto' }} />
      {state === 'missing' ? <span>No image</span> : state === 'loading' ? <span>Loading plate image…</span> : null}
    </span>
  );
}

/** The same operational evidence in Investigation and Review; no registration is asserted. */
export default function TrackPlateReadings({ detail, compact = false, matchedText, onSelectObservation }: Props) {
  const [expanded, setExpanded] = useState(false);
  const plates = detail.plates;
  if (!plates || detail.objectClass !== 'Vehicle') return null;
  const title = compact ? <h3>Plate readings</h3> : null;
  let message: string | undefined;
  switch (plates.readiness) {
    case 'Pending': message = 'Plate reading pending'; break;
    case 'Failed': message = 'Plate reading failed for this run'; break;
    case 'Stale': message = 'Plate readings are from an earlier configuration'; break;
    case 'NotConfigured': message = 'Plate reading is not configured in this installation'; break;
    case 'Ready':
      if (plates.trackOutcome === 'Unavailable')
        message = `Plate reading unavailable for this track · ${plates.unavailableReason ?? 'unknown'}`;
      else if (plates.observations.length === 0)
        message = 'No plate found in the evidence';
      break;
    default: message = 'Plate reading unavailable';
  }
  if (message) return (
    <section aria-label="Plate readings" className="stack" {...{ [EVIDENCE_PLAYER_ATTRIBUTE]: '' }}>
      {title}<p>{message}</p>
    </section>
  );

  const agreement = plates.agreement === 'consistent' ? 'Consistent readings'
    : plates.agreement === 'single' ? 'Single reading'
    : plates.agreement === 'conflicting' ? `Conflicting readings · ${plates.texts.length} texts`
    : 'No searchable reading';
  const shown = expanded ? plates.observations : plates.observations.slice(0, 5);
  const count = plates.observations.length;

  return (
    <section aria-label="Plate readings" className="stack" {...{ [EVIDENCE_PLAYER_ATTRIBUTE]: '' }}>
      {title}
      <p>{agreement}</p>
      {plates.texts.length ? (
        <ul aria-label="Searchable plate readings" className="stack">
          {plates.texts.map((text) => (
            <li key={text.normalisedText}>
              <strong className="mono">
                {matchedText === text.normalisedText ? <u>{text.normalisedText}</u> : text.normalisedText}
              </strong>
              {' · on '}{text.supportCount} of {count} plates
              {' · '}{formatConfidence(text.maxConfidence)}
            </li>
          ))}
        </ul>
      ) : null}
      <ul aria-label="Plate observations" className="stack">
        {shown.map((plate) => {
          const rank0 = plate.readings.find((item) => item.rank === 0);
          return (
            <li key={plate.plateObservationId} className="stack">
              <PlateRegion detail={detail} plate={plate} />
              <span>
                {EVIDENCE_ROLE_LABELS[plate.role]} · {formatOffset(plate.offsetMs, 'tenths')}
                {' · '}{formatConfidence(plate.detectorConfidence)} detector confidence
              </span>
              {plate.outcome === 'Unreadable' || !rank0 ? <span>Unreadable plate</span> : (
                <>
                  <span>Raw: <span className="mono" style={{ whiteSpace: 'pre-line' }}>{rank0.rawText}</span></span>
                  <span>{rank0.normalisationOutcome === 'ok'
                    ? <>Normalised: <span className="mono">{rank0.normalisedText}</span> · {formatConfidence(rank0.confidence)} reading confidence</>
                    : 'Not searchable — does not normalise to letters and digits'}
                  </span>
                  {plate.readings.length > 1 ? (
                    <details className="disclosure">
                      <summary>{plate.readings.length - 1} other reading{plate.readings.length === 2 ? '' : 's'}</summary>
                      <ul>{plate.readings.filter((item) => item.rank !== 0).map((item) => (
                        <li key={item.rank} className="mono">{item.rawText} · {formatConfidence(item.confidence)}</li>
                      ))}</ul>
                    </details>
                  ) : null}
                </>
              )}
              {onSelectObservation ? <button type="button" className="btn btn--sm"
                onClick={() => onSelectObservation(plate.sourceObservationId, plate.offsetMs)}>
                View source at {formatOffset(plate.offsetMs, 'tenths')}
              </button> : null}
            </li>
          );
        })}
      </ul>
      {count > 5 ? <button type="button" className="btn btn--sm" onClick={() => setExpanded((value) => !value)}>
        {expanded ? 'Show fewer plate observations' : `Show all ${count} plate observations`}
      </button> : null}
    </section>
  );
}
