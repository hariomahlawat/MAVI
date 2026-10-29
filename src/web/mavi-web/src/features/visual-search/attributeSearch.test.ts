import { describe, expect, it } from 'vitest';
import { serializeTrackSearchFilters } from '../../api/tracks';
import {
  attributeDisclosure,
  attributeMatchText,
  canonicalPredicates,
  predicateLabel,
  withPredicate,
} from './attributeSearch';
import { canonicalSearchKey, hasAppearanceConflict, parseCommittedSearch } from './searchState';

describe('PoC S5 attribute predicates', () => {
  it('orders predicates canonically, so any order is one search (E6)', () => {
    expect(canonicalPredicates(['person-upper-colour:red', 'person-carried-bag:present']))
      .toEqual(['person-carried-bag:present', 'person-upper-colour:red']);
    const forward = parseCommittedSearch(new URLSearchParams('attribute=person-upper-colour:red&attribute=person-carried-bag:present'));
    const reversed = parseCommittedSearch(new URLSearchParams('attribute=person-carried-bag:present&attribute=person-upper-colour:red'));
    expect(forward.isValid && reversed.isValid).toBe(true);
    expect(forward.canonicalQuery).toBe(reversed.canonicalQuery);
    expect(forward.canonicalQuery).toBe('attribute=person-carried-bag%3Apresent&attribute=person-upper-colour%3Ared');
  });

  it.each([
    'attribute=person-upper-colour',
    'attribute=Person:red',
    'attribute=person-upper-colour:red&attribute=person-upper-colour:blue',
    'attribute=a:b&attribute=c:d&attribute=e:f&attribute=g:h&attribute=i:j',
  ])('refuses %s', (query) => {
    expect(parseCommittedSearch(new URLSearchParams(query)).isValid).toBe(false);
  });

  it('refuses attribute filters beside plate text and conflicts with an appearance query', () => {
    const plate = parseCommittedSearch(new URLSearchParams('plateText=KA01&attribute=vehicle-colour:white'));
    expect(plate.isValid).toBe(false);
    expect(hasAppearanceConflict({ attribute: ['vehicle-colour:white'] })).toBe(true);
  });

  it('sends each predicate as its own repeated key', () => {
    expect(serializeTrackSearchFilters({ attribute: ['person-carried-bag:present', 'person-upper-colour:red'], limit: 50 }))
      .toBe('attribute=person-carried-bag%3Apresent&attribute=person-upper-colour%3Ared&limit=50');
    expect(canonicalSearchKey({ attribute: ['person-upper-colour:red'] })).toBe('attribute=person-upper-colour%3Ared');
  });

  it('edits one type at a time in the draft, keeping canonical order', () => {
    let draft = withPredicate('', 'person-upper-colour', 'red');
    draft = withPredicate(draft, 'person-carried-bag', 'present');
    expect(draft).toBe('person-carried-bag:present,person-upper-colour:red');
    expect(withPredicate(draft, 'person-carried-bag', '')).toBe('person-upper-colour:red');
  });

  it('labels predicates, matches and the disclosure in operator words', () => {
    expect(predicateLabel('person-upper-colour:red')).toBe('Upper clothing colour: red');
    expect(attributeMatchText([{ attributeType: 'vehicle-colour', value: 'white', confidence: 0.734 }]))
      .toBe('Matched vehicle colour white (score 0.73)');
    expect(attributeDisclosure('zero-shot, Development', true)).toBe('zero-shot, Development');
    expect(attributeDisclosure(null, true)).toBe('Development');
    expect(attributeDisclosure(null, false)).toBeNull();
  });
});
