import type { TrackEvidenceObservation, TrackEvidenceRole } from '../../api/tracks';
import { formatOffset } from '../../shared/format/format';
import type { EvidenceTimelineMarker } from '../../shared/evidence/timeline';

/**
 * The one web Representative authority (S1.3 plan §8.1).
 *
 * The Representative is rank 0 of the Evidence Set, and nothing else. The
 * wire's compatibility `detail.representative` is derived from the same
 * Observation by the server, but the web never reads it: two read paths could
 * disagree, and then the crop, the player and the Track identity would each be
 * showing a different Representative.
 *
 * The server refuses a set whose rank 0 is not the Representative (HTTP 500),
 * so the check here is not a repair. It only makes sure a contradictory input
 * can never be presented as the Representative.
 */
export function representativeObservation(
  detail: { readonly observations: readonly TrackEvidenceObservation[] },
): TrackEvidenceObservation | null {
  const first = detail.observations[0];
  return first && first.evidenceRank === 0 && first.evidenceRole === 'Representative' ? first : null;
}

/** Operator wording for each role. Plain names: no quality or qualification claim. */
export const EVIDENCE_ROLE_LABELS: Record<TrackEvidenceRole, string> = {
  Representative: 'Representative',
  NearView: 'Near view',
  EarlyDiverse: 'Early diverse',
  LateDiverse: 'Late diverse',
};

/** Timeline wording: the Representative keeps its existing marker label. */
const MARKER_LABELS: Record<TrackEvidenceRole, string> = {
  Representative: 'Representative frame',
  NearView: 'Near view evidence',
  EarlyDiverse: 'Early diverse evidence',
  LateDiverse: 'Late diverse evidence',
};

/** `Near view · 00:12.3`: the one name an Observation has, in the strip and the inspection. */
export function observationName(observation: TrackEvidenceObservation): string {
  return `${EVIDENCE_ROLE_LABELS[observation.evidenceRole]} · ${formatOffset(observation.videoOffsetMs, 'tenths')}`;
}

/** Marker kind of the Representative: unchanged, so its tick keeps its look. */
export const REPRESENTATIVE_MARKER_KIND = 'representative';
/** Marker kind of every supplemental Observation. */
export const SUPPLEMENTAL_MARKER_KIND = 'evidence';

/**
 * One exact-seek timeline marker per Observation, in rank order.
 *
 * This is the only source of the Representative marker too, so a Track shows
 * one Representative marker and never a second one built from the
 * compatibility object.
 */
export function evidenceMarkers(observations: readonly TrackEvidenceObservation[]): EvidenceTimelineMarker[] {
  const representative = representativeObservation({ observations });
  return observations.map((observation) => ({
    id: 'observation-' + observation.observationId,
    offsetMs: observation.videoOffsetMs,
    label: MARKER_LABELS[observation.evidenceRole],
    kind: observation === representative ? REPRESENTATIVE_MARKER_KIND : SUPPLEMENTAL_MARKER_KIND,
  }));
}
