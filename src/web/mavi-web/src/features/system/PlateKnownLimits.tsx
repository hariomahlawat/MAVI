import Panel from '../../shared/components/Panel';

/**
 * The plate-reading capability's known limits (PoC S3, register row C4.3). The
 * numbers are the Development pilot's measurement on the H3 proxy holdout
 * (`docs/qualification/stage4/anpr-dev-pilot-2026-10-17.md`), cited verbatim;
 * nothing here is configured or fetched, so no installation can soften it. The
 * ADR-020 disclosure is part of the text for the same reason.
 */
export const PLATE_KNOWN_LIMITS = {
  allTextTracks: '52/110',
  oracleReadableTracks: '45/79',
  disclosure: 'Profile poc-single-host (ADR-020): not Production-qualified; evidence class Development.',
} as const;

export default function PlateKnownLimits() {
  return (
    <Panel title="Known limits: plate reading" headingId="system-known-limits-plates">
      <div className="system-page__limits" id="known-limits">
        <p><strong>{PLATE_KNOWN_LIMITS.disclosure}</strong></p>
        <ul>
          <li>
            Plates are read by PD5 (PP-OCRv5 mobile detection, Apache-2.0) and OC1-S (fast-plate-ocr
            cct-s-v2, MIT): unverified Development Model Packs, run on CPU.
          </li>
          <li>
            Measured on proxy data only (BDD100K dash-camera footage, the H3 holdout; Development pilot, 2026-10-17):
            exact plate search returned the right Track for <strong>{PLATE_KNOWN_LIMITS.allTextTracks}</strong>{' '}
            ground-truth vehicles with a usable plate text, and for <strong>{PLATE_KNOWN_LIMITS.oracleReadableTracks}</strong>{' '}
            of those whose plate the reference reader could read.
          </li>
          <li>No Indian plates: no Indian plate data has been measured, and no accuracy is claimed beyond these numbers.</li>
          <li>A plate reading is a candidate, not an identification: check it against its crop and source frame.</li>
        </ul>
      </div>
    </Panel>
  );
}
