import { useState } from 'react';
import type { TrackDetail, TrackEvidenceObservation } from '../../api/tracks';
import { EVIDENCE_PLAYER_ATTRIBUTE } from '../../shared/evidence/EvidencePlayer';
import { formatConfidence, formatOffset } from '../../shared/format/format';
import { EVIDENCE_ROLE_LABELS, observationName } from './evidenceSet';

type Props = {
  detail: TrackDetail;
  /** The Investigation inspector: no host panel, so the set names itself. */
  compact?: boolean;
};

/**
 * The Track's Evidence Set: a bounded strip of its accepted Observations and
 * one region inspecting the selected crop (S1.3 plan §8).
 *
 * One implementation for Review's evidence rail and the Investigation
 * inspector. It is secondary evidence: the source video stays in the Evidence
 * Player, and nothing here seeks, plays or pauses it. Selecting a crop only
 * changes what is inspected here. The timeline markers are the way to seek the
 * video to an Observation.
 *
 * Each crop is a subject crop cut from its source frame. It is never presented
 * as the frame itself, so it is shown contained in its own matte and never
 * stretched over the player.
 *
 * Keyboard: this is rendered outside the player's root, so the player's
 * grammar (J, L, arrows, Home, End, E) never sees a key pressed here. The root
 * carries the player's exported subtree attribute so Investigation's window
 * result navigation refuses J and K from here too, which is the existing
 * contract rather than a second suppression mechanism. The crop controls are
 * plain buttons: Enter and Space select, and no other key is redefined.
 */
export default function TrackEvidenceSet({ detail, compact = false }: Props) {
  const observations = detail.observations;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Keyed by URL, so a failure belongs to the bytes that failed and not to a
  // position in a strip that another Track may reuse.
  const [failedUrls, setFailedUrls] = useState<ReadonlySet<string>>(() => new Set());

  // Rank 0 until the operator chooses otherwise, and again whenever the choice
  // no longer names an Observation of this Track.
  const selected = observations.find((observation) => observation.observationId === selectedId) ?? observations[0];

  const markFailed = (url: string) => setFailedUrls((current) => (current.has(url) ? current : new Set(current).add(url)));
  const imageState = (observation: TrackEvidenceObservation): 'available' | 'absent' | 'failed' => {
    const url = observation.evidenceContentUrl;
    if (!url) return 'absent';
    return failedUrls.has(url) ? 'failed' : 'available';
  };

  return (
    <section
      className={compact ? 'evidence-set evidence-set--compact' : 'evidence-set'}
      aria-label="Evidence Set"
      {...{ [EVIDENCE_PLAYER_ATTRIBUTE]: '' }}
    >
      {compact ? <h3 className="evidence-set__title">Evidence Set</h3> : null}

      {selected ? (
        // The inspected crop beside the rank-ordered list, so the whole set
        // costs the height of one crop rather than a crop plus a gallery.
        <div className="evidence-set__body">
          <Inspection
            observation={selected}
            state={imageState(selected)}
            onError={markFailed}
          />
          <ul className="evidence-set__strip" aria-label="Evidence Set observations">
            {/* Rank order is the order: the server returns it and nothing here re-sorts. */}
            {observations.map((observation) => {
              const isSelected = observation.observationId === selected.observationId;
              const state = imageState(observation);
              const name = observationName(observation);
              return (
                <li key={observation.observationId} className="evidence-set__item">
                  <button
                    type="button"
                    className="evidence-set__control"
                    // The inspected Observation, as the result list marks its selection.
                    aria-current={isSelected ? 'true' : undefined}
                    aria-label={name + (state === 'available' ? '' : ', evidence image unavailable')}
                    data-role={observation.evidenceRole}
                    onClick={() => setSelectedId(observation.observationId)}
                  >
                    <span className="evidence-set__thumb">
                      {state === 'available' ? (
                        <img
                          src={observation.evidenceContentUrl!}
                          alt={`${name} crop`}
                          decoding="async"
                          onError={() => markFailed(observation.evidenceContentUrl!)}
                        />
                      ) : null}
                    </span>
                    <span className="evidence-set__role">{EVIDENCE_ROLE_LABELS[observation.evidenceRole]}</span>
                    <span className="evidence-set__offset">
                      {formatOffset(observation.videoOffsetMs, 'tenths')}
                      {/* Said in words, beside the empty box: never colour or absence alone. */}
                      {state === 'available' ? null : <span className="evidence-set__missing"> · Image unavailable</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        // A legacy Track with no persisted Representative. Readable history,
        // not an error, and nothing is fabricated in its place.
        <p className="evidence-set__empty">No Evidence Set was persisted for this Track.</p>
      )}
    </section>
  );
}

/**
 * The one inspected crop. A fixed matte, so the region does not change height
 * while an image loads or when it fails.
 */
function Inspection({
  observation,
  state,
  onError,
}: {
  observation: TrackEvidenceObservation;
  state: 'available' | 'absent' | 'failed';
  onError: (url: string) => void;
}) {
  const name = observationName(observation);
  return (
    <figure className="evidence-set__inspection" aria-label={`Inspecting ${name}`}>
      <div className="evidence-set__crop">
        {state === 'available' ? (
          <img
            // Keyed so a newly selected crop never shows the previous one's
            // bytes while its own load.
            key={observation.evidenceContentUrl}
            src={observation.evidenceContentUrl!}
            alt={`${name} evidence crop`}
            decoding="async"
            onError={() => onError(observation.evidenceContentUrl!)}
          />
        ) : (
          <p className="evidence-set__missing">
            {state === 'absent'
              ? 'No evidence image was persisted for this observation.'
              : 'Evidence image unavailable.'}
          </p>
        )}
      </div>
      <figcaption className="evidence-set__caption">
        <strong>{EVIDENCE_ROLE_LABELS[observation.evidenceRole]}</strong>
        <span>{formatOffset(observation.videoOffsetMs, 'tenths')}</span>
        <span>Frame {observation.sourceFrameNumber}</span>
        <span>{formatConfidence(observation.confidence)} confidence</span>
      </figcaption>
    </figure>
  );
}
