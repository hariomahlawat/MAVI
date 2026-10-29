/**
 * Visual-attribute search helpers (PoC S5; Stage-2 plan §16, UI/UX §29).
 *
 * A predicate is `type:value` of schema tokens. A search carries one to four of
 * them with distinct types, ANDed, in canonical (ordinal type) order — the order
 * the URL, the cache key and the server's cursor fingerprint all use, so the same
 * predicates in any order are one search. The vocabulary itself is never copied
 * here: the rail reads it from the server (`GET /api/visual-attributes/vocabulary`).
 */

export const MAX_ATTRIBUTE_PREDICATES = 4;

/** The disclosure shown when the server states none for a Development pipeline. */
export const ATTRIBUTE_DEVELOPMENT_FALLBACK = 'Development';

const TOKEN = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;

export type AttributePredicate = { attributeType: string; value: string };

export function parsePredicate(raw: string): AttributePredicate | null {
  const parts = raw.split(':');
  if (parts.length !== 2) return null;
  const [attributeType, value] = parts;
  if (attributeType.length > 64 || value.length > 64 || !TOKEN.test(attributeType) || !TOKEN.test(value)) return null;
  return { attributeType, value };
}

function compareOrdinal(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

/** Canonical predicates, or null when any is malformed, a type repeats or there are too many. */
export function canonicalPredicates(raw: readonly string[]): string[] | null {
  if (raw.length > MAX_ATTRIBUTE_PREDICATES) return null;
  const parsed: AttributePredicate[] = [];
  for (const item of raw) {
    const predicate = parsePredicate(item);
    if (!predicate) return null;
    parsed.push(predicate);
  }
  parsed.sort((left, right) => compareOrdinal(left.attributeType, right.attributeType));
  for (let index = 1; index < parsed.length; index += 1) {
    if (parsed[index - 1].attributeType === parsed[index].attributeType) return null;
  }
  return parsed.map((item) => item.attributeType + ':' + item.value);
}

/** The draft holds the predicates as one comma-joined canonical string, like every other draft field. */
export function predicatesFromDraft(text: string): string[] {
  return text ? text.split(',') : [];
}

export function draftFromPredicates(predicates: readonly string[] | undefined): string {
  return predicates && predicates.length > 0 ? (canonicalPredicates(predicates) ?? []).join(',') : '';
}

/** Set or clear one type's value in a draft predicate list, keeping canonical order. */
export function withPredicate(text: string, attributeType: string, value: string): string {
  const others = predicatesFromDraft(text).filter((item) => !item.startsWith(attributeType + ':'));
  return draftFromPredicates(value ? [...others, attributeType + ':' + value] : others);
}

const TYPE_LABELS: Record<string, string> = {
  'person-upper-colour': 'Upper clothing colour',
  'person-lower-colour': 'Lower clothing colour',
  'person-carried-bag': 'Carried bag',
  'person-headwear': 'Headwear',
  'vehicle-colour': 'Vehicle colour',
};

/** An operator label for a schema type; an unlabelled type is shown by its token. */
export function attributeTypeLabel(attributeType: string): string {
  return TYPE_LABELS[attributeType] ?? attributeType;
}

/** A schema value as read text. `present` reads as such: a presence attribute has no negative value. */
export function attributeValueLabel(value: string): string {
  return value.replace(/-/g, ' ');
}

export function predicateLabel(raw: string): string {
  const predicate = parsePredicate(raw);
  return predicate ? attributeTypeLabel(predicate.attributeType) + ': ' + attributeValueLabel(predicate.value) : raw;
}

/** The disclosure every attribute surface carries: the server's, else "Development" when development-only. */
export function attributeDisclosure(disclosure: string | null | undefined, developmentOnly: boolean): string | null {
  if (disclosure) return disclosure;
  return developmentOnly ? ATTRIBUTE_DEVELOPMENT_FALLBACK : null;
}

/** A result row's plain-text explanation: each matched value with its abstention-normalised score. */
export function attributeMatchText(matches: ReadonlyArray<{ attributeType: string; value: string; confidence: number }>): string {
  return 'Matched ' + matches
    .map((item) => attributeTypeLabel(item.attributeType).toLowerCase() + ' ' + attributeValueLabel(item.value)
      + ' (score ' + item.confidence.toFixed(2) + ')')
    .join(' · ');
}
