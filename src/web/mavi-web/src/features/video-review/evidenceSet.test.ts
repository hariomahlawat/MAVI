import { describe, expect, it } from 'vitest';
import { TRACK_EVIDENCE_ROLES } from '../../api/tracks';
import {
  DISAGREEING_REPRESENTATIVE,
  evidenceObservation,
  evidenceSet,
  FULL_EVIDENCE_SET_ROLES,
} from '../../test/trackEvidenceFixtures';
import {
  EVIDENCE_ROLE_LABELS,
  evidenceMarkers,
  observationName,
  REPRESENTATIVE_MARKER_KIND,
  representativeObservation,
  SUPPLEMENTAL_MARKER_KIND,
} from './evidenceSet';

describe('the web Evidence Set contract', () => {
  it('pins the closed role vocabulary, its casing and its canonical order', () => {
    expect(TRACK_EVIDENCE_ROLES).toEqual(['Representative', 'NearView', 'EarlyDiverse', 'LateDiverse']);
    expect(Object.keys(EVIDENCE_ROLE_LABELS)).toEqual([...TRACK_EVIDENCE_ROLES]);
  });

  it('names roles in plain operator words, with no quality or qualification claim', () => {
    expect(EVIDENCE_ROLE_LABELS).toEqual({
      Representative: 'Representative',
      NearView: 'Near view',
      EarlyDiverse: 'Early diverse',
      LateDiverse: 'Late diverse',
    });
    for (const label of Object.values(EVIDENCE_ROLE_LABELS)) expect(label).not.toMatch(/qualif|verif|best/i);
  });

  it('names an Observation by its role and exact offset in tenths', () => {
    expect(observationName(evidenceObservation('NearView', 1, { videoOffsetMs: 12_345 }))).toBe('Near view · 00:12.3');
    expect(observationName(evidenceObservation('Representative', 0, { videoOffsetMs: 3_723_950 }))).toBe('Representative · 1:02:03.9');
  });
});

describe('representativeObservation, the one web Representative authority', () => {
  it('is rank 0 of the Evidence Set', () => {
    const observations = evidenceSet(FULL_EVIDENCE_SET_ROLES);
    expect(representativeObservation({ observations })).toBe(observations[0]);
  });

  it('is absent for the legacy shape with no Evidence Set', () => {
    expect(representativeObservation({ observations: [] })).toBeNull();
  });

  it('ignores the compatibility object entirely', () => {
    const observations = evidenceSet(['Representative', 'NearView']);
    const detail = { observations, representative: DISAGREEING_REPRESENTATIVE };
    expect(representativeObservation(detail)).toBe(observations[0]);
    // And a compatibility object alone never produces a Representative.
    expect(representativeObservation({ observations: [], representative: DISAGREEING_REPRESENTATIVE } as never)).toBeNull();
  });

  it('never presents a contradictory rank 0 as the Representative', () => {
    // The server refuses this set with a 500, so it is not reachable; the
    // selector still does not promote a supplemental into the Representative.
    expect(representativeObservation({ observations: [evidenceObservation('NearView', 0)] })).toBeNull();
    expect(representativeObservation({ observations: [evidenceObservation('Representative', 1)] })).toBeNull();
  });
});

describe('evidenceMarkers', () => {
  it('builds one exact-offset marker per Observation, in rank order', () => {
    const observations = evidenceSet(FULL_EVIDENCE_SET_ROLES);
    const markers = evidenceMarkers(observations);

    expect(markers.map((marker) => marker.offsetMs)).toEqual(observations.map((o) => o.videoOffsetMs));
    expect(markers.map((marker) => marker.label)).toEqual([
      'Representative frame',
      'Near view evidence',
      'Early diverse evidence',
      'Late diverse evidence',
    ]);
    expect(new Set(markers.map((marker) => marker.id)).size).toBe(4);
  });

  it('has exactly one Representative marker, and it is rank 0', () => {
    const markers = evidenceMarkers(evidenceSet(FULL_EVIDENCE_SET_ROLES));
    const representative = markers.filter((marker) => marker.kind === REPRESENTATIVE_MARKER_KIND);
    expect(representative).toHaveLength(1);
    expect(representative[0]).toBe(markers[0]);
    expect(markers.slice(1).every((marker) => marker.kind === SUPPLEMENTAL_MARKER_KIND)).toBe(true);
  });

  it('builds nothing for the legacy shape', () => {
    expect(evidenceMarkers([])).toEqual([]);
  });
});
