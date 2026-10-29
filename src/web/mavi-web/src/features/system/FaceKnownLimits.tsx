import { POC_PROFILE } from '../../api/deployment';
import Panel from '../../shared/components/Panel';

/**
 * Face intelligence's known limits (PoC S6, register rows C5A.1–C5A.5), cited
 * from `docs/qualification/poc/known-limits.md`, `s6-face-coverage.md` and
 * `s6-face-embedder-spike.md`. Every number lives in this one constant, so a
 * re-measurement (coverage v2) changes one place, and a test holds it to the
 * documents. Nothing here is configured or fetched.
 */
export const FACE_KNOWN_LIMITS = {
  coverage: '2 of 110',
  coverageClip: 's2-12 (2 of 9)',
  lfwNative: '99.8 %',
  lfw32: '99.7 %',
  referenceThreshold: '0.2121',
  disclosure: 'Profile poc-single-host (ADR-020): not Production-qualified; evidence class Development.',
  unprofiled: 'Development capability: not Production-qualified.',
} as const;

export default function FaceKnownLimits({ profile }: { profile: string }) {
  const limits = FACE_KNOWN_LIMITS;
  return (
    <Panel title="Known limits: face intelligence" headingId="system-known-limits-faces">
      <div className="system-page__limits">
        <p><strong>{profile === POC_PROFILE ? limits.disclosure : limits.unprofiled}</strong></p>
        <ul>
          <li>
            Face candidates, not identification: every result is a cosine score beside the reference threshold and the
            model identity. Nothing stores a match or states who a person is (ADR-022).
          </li>
          <li>
            Usable faces are rare in the demo corpus: <strong>{limits.coverage}</strong> Person Tracks have a face of at
            least 32 px at detector score 0.9, all in {limits.coverageClip}. Most Person Tracks are Unknown (no usable
            face): not analysable, never &quot;no match&quot;.
          </li>
          <li>Face analysis is opt-in per camera and off by default.</li>
          <li>
            AdaFace IR-50 scores <strong>{limits.lfwNative}</strong> on LFW (10-fold) and <strong>{limits.lfw32}</strong>{' '}
            with faces downscaled to 32 px. The reference threshold <strong>{limits.referenceThreshold}</strong> is the
            32-px operating point at 0.1 % false accepts on LFW: not calibrated on CCTV, and LFW may overlap the training
            identities.
          </li>
          <li>
            The AdaFace checkpoint follows WebFace4M&apos;s non-commercial research terms: research-only, Development-only
            and for non-commercial demonstration only. SFace (Apache-2.0) is the built fallback.
          </li>
          <li>Face templates, the gallery and query images stay in this installation&apos;s database; uninstall removes them.</li>
        </ul>
      </div>
    </Panel>
  );
}
