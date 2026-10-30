import type { TrackDetail } from '../../api/tracks';
import KeyValue from '../../shared/components/KeyValue';
import { attributeDisclosure, attributeTypeLabel, attributeValueLabel } from '../visual-search/attributeSearch';
import { EVIDENCE_ROLE_LABELS } from './evidenceSet';

type Props = {
  detail: TrackDetail;
  compact?: boolean;
};

const READINESS_TEXT: Record<string, string> = {
  NotConfigured: 'Attribute analysis is not configured in this installation.',
  NotApplicable: 'Attribute analysis does not apply to this run.',
  Pending: 'Attribute analysis has not finished for this run.',
  Failed: 'Attribute analysis failed for this run.',
  Stale: 'Only an earlier attribute analysis exists for this run; it is not shown.',
};

/** An abstention-normalised score (0.5 is the threshold), shown as such and never as a percentage. */
export function formatAttributeScore(score: number): string {
  return score.toFixed(2);
}

/**
 * A Track's visual attributes (UI/UX §14, §29; PoC S5), as inspector key/value
 * rows. Each applicable attribute reads as one of three explicit, non-colour
 * states: an Observed value with its score and supporting crop; "Analysed ·
 * value unknown" (the model abstained — never a negative); or the Track's
 * Unavailable reason. A run that is not Ready says why in words. The pipeline's
 * disclosure (PoC: "zero-shot, Development") heads the panel, and the producing
 * analysis is in the Provenance disclosure (tier 3).
 */
export default function TrackAttributesPanel({ detail, compact = false }: Props) {
  const attributes = detail.attributes;
  if (!attributes) return null;
  const disclosure = attributeDisclosure(attributes.disclosure, attributes.developmentOnly);
  const roleOf = (observationId: string | undefined) => {
    const observation = detail.observations.find((item) => item.observationId === observationId);
    return observation ? EVIDENCE_ROLE_LABELS[observation.evidenceRole] : undefined;
  };

  let body;
  if (attributes.readiness !== 'Ready') {
    body = <p>{READINESS_TEXT[attributes.readiness] ?? 'Attribute analysis is not available.'}</p>;
  } else if (attributes.trackOutcome !== 'Analysed') {
    body = <p>Attributes unavailable for this Track{attributes.unavailableReason ? ` (${attributes.unavailableReason.replace(/_/g, ' ')})` : ''}.</p>;
  } else {
    body = (
      <KeyValue
        items={attributes.attributes.map((row) => ({
          label: attributeTypeLabel(row.attributeType),
          value: row.outcome === 'Observed' && row.value !== undefined
            ? `${attributeValueLabel(row.value)} · score ${formatAttributeScore(row.confidence ?? 0)}`
              + (roleOf(row.supportingObservationId) ? ` · ${roleOf(row.supportingObservationId)} crop` : '')
            : 'Analysed · value unknown',
        }))}
      />
    );
  }

  return (
    <section aria-label="Attributes" className="stack">
      {compact ? <h3>Attributes</h3> : <h2>Attributes</h2>}
      {disclosure ? <p>{disclosure}: candidate values, not verified facts.</p> : null}
      {body}
      {attributes.provenance ? (
        <details className="disclosure">
          <summary>Attribute provenance</summary>
          <div className="disclosure__body">
            <KeyValue items={[
              { label: 'Analysis', value: attributes.provenance.analysisId, mono: true },
              { label: 'Pipeline', value: `${attributes.provenance.pipelineId} ${attributes.provenance.pipelineVersion}` },
              { label: 'Schema', value: `${attributes.provenance.attributeSchemaId} ${attributes.provenance.attributeSchemaVersion}` },
              { label: 'Aggregation', value: `${attributes.provenance.aggregationPolicyId} ${attributes.provenance.aggregationPolicyVersion}` },
              { label: 'Model packs', value: attributes.provenance.capabilities, mono: true },
              { label: 'Identity', value: attributes.provenance.identityFingerprint, mono: true },
            ]} />
          </div>
        </details>
      ) : null}
    </section>
  );
}
