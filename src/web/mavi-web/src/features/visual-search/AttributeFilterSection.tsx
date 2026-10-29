import type { AttributeVocabulary, TrackObjectClass } from '../../api/tracks';
import Field from '../../shared/components/Field';
import {
  attributeDisclosure,
  attributeTypeLabel,
  attributeValueLabel,
  parsePredicate,
  predicatesFromDraft,
  withPredicate,
} from './attributeSearch';

type Props = {
  /** The canonical comma-joined predicates of the draft. */
  value: string;
  objectClass: '' | TrackObjectClass;
  vocabulary: AttributeVocabulary | undefined;
  vocabularyUnavailable: boolean;
  error?: string;
  onChange: (patch: { attribute: string; objectClass?: TrackObjectClass }) => void;
};

const CLASS_OF: Record<'person' | 'vehicle', TrackObjectClass> = { person: 'Person', vehicle: 'Vehicle' };

/**
 * The Attributes section of the filter rail (UI/UX §29; PoC S5): one choice per
 * attribute type the bound schema offers, "Any" by default. Choosing a value
 * states the type's object class, and a type of the other class is cleared, so
 * the rail can only commit a search the server accepts. The section states the
 * pipeline's disclosure (PoC: "zero-shot, Development"), because these values
 * are candidate evidence from a zero-shot model, not observed facts.
 */
export default function AttributeFilterSection({ value, objectClass, vocabulary, vocabularyUnavailable, error, onChange }: Props) {
  const disclosure = vocabulary ? attributeDisclosure(vocabulary.disclosure, vocabulary.developmentOnly) : null;
  const chosen = new Map(predicatesFromDraft(value).map((raw) => {
    const predicate = parsePredicate(raw);
    return [predicate?.attributeType ?? raw, predicate?.value ?? ''] as const;
  }));
  const offered = vocabulary?.attributes.filter((item) =>
    objectClass === '' || CLASS_OF[item.objectClass] === objectClass || chosen.has(item.attributeType)) ?? [];

  // A chosen attribute of the other class (the operator changed Object class after choosing it) cannot be searched:
  // say so on the section, in words, rather than let the server refuse the whole search.
  const mismatched = objectClass === '' ? [] : [...chosen.keys()].filter((type) => {
    const definition = vocabulary?.attributes.find((item) => item.attributeType === type);
    return definition !== undefined && CLASS_OF[definition.objectClass] !== objectClass;
  });

  function choose(attributeType: string, objectClassOfType: 'person' | 'vehicle', next: string) {
    let text = value;
    if (next) {
      // A type of the other class cannot stand beside this one.
      for (const [other] of chosen) {
        const definition = vocabulary?.attributes.find((item) => item.attributeType === other);
        if (definition && definition.objectClass !== objectClassOfType) text = withPredicate(text, other, '');
      }
    }
    text = withPredicate(text, attributeType, next);
    onChange(next ? { attribute: text, objectClass: CLASS_OF[objectClassOfType] } : { attribute: text });
  }

  return (
    <section className="filter-rail__section" aria-labelledby="filter-attributes">
      <h2 id="filter-attributes">Attributes</h2>
      {disclosure ? <p className="filter-rail__hint">Attribute values: {disclosure}</p> : null}
      {mismatched.length > 0 ? (
        <p className="filter-rail__hint" role="alert">
          {mismatched.map(attributeTypeLabel).join(', ')} does not apply to {objectClass} Tracks. Set it to Any, or change Object class.
        </p>
      ) : null}
      {vocabularyUnavailable ? (
        <p className="filter-rail__hint">The attribute vocabulary is unavailable, so attribute filters cannot be edited.</p>
      ) : !vocabulary ? (
        <p className="filter-rail__hint">Loading the attribute vocabulary…</p>
      ) : !vocabulary.configured ? (
        <p className="filter-rail__hint">Attribute search is not configured in this installation.</p>
      ) : (
        offered.map((item, index) => (
          <Field
            key={item.attributeType}
            label={attributeTypeLabel(item.attributeType)}
            error={index === 0 ? error : undefined}
          >
            {(control) => (
              <select
                {...control}
                value={chosen.get(item.attributeType) ?? ''}
                onChange={(event) => choose(item.attributeType, item.objectClass, event.target.value)}
              >
                <option value="">Any</option>
                {item.values.map((option) => (
                  <option key={option} value={option}>{attributeValueLabel(option)}</option>
                ))}
              </select>
            )}
          </Field>
        ))
      )}
    </section>
  );
}
