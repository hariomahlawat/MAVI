import { describe, expect, it } from 'vitest';
import { serializeTrackSearchFilters } from '../../api/tracks';
import { emptyDraft } from './SearchFilterRail';
import { normalisePlateText } from './plateText';
import { canonicalSearchKey, parseCommittedSearch, removeCriteria } from './searchState';
import { commitDraft } from './searchValidation';

describe('Stage-4 operator plate search grammar', () => {
  it('normalises only the frozen separators and ASCII case, with NFKC', () => {
    expect(normalisePlateText('ka 01-ab/1234')).toBe('KA01AB1234');
    expect(normalisePlateText('ka\t01\nAB:12·34')).toBe('KA01AB1234');
    expect(normalisePlateText('ｋａ０１ａｂ１２３４')).toBe('KA01AB1234');
    expect(normalisePlateText('O01')).toBe('O01');
    expect(normalisePlateText('001')).toBe('001');
    expect(normalisePlateText('ＫΑ01')).toBeNull(); // Greek alpha is not an ASCII A.
    expect(normalisePlateText('O1')).toBeNull();
    expect(normalisePlateText('A'.repeat(16))).toBeNull();
    expect(normalisePlateText('--.·')).toBeNull();
  });

  it('round-trips one canonical URL for implicit Vehicle and default contains', () => {
    const parsed = parseCommittedSearch(new URLSearchParams('plateText=ka-01-ab-1234&plateMatch=contains'));
    expect(parsed).toEqual({
      isValid: true,
      filters: { objectClass: 'Vehicle', plateText: 'KA01AB1234' },
      canonicalQuery: 'objectClass=Vehicle&plateText=KA01AB1234',
    });
    if (parsed.isValid) {
      expect(parseCommittedSearch(new URLSearchParams(parsed.canonicalQuery))).toEqual(parsed);
      expect(canonicalSearchKey(parsed.filters)).toBe(parsed.canonicalQuery);
      expect(serializeTrackSearchFilters(parsed.filters)).toBe(parsed.canonicalQuery);
    }
  });

  it('preserves prefix/exact, rejects invalid pairing, and removes dependent match', () => {
    const prefix = parseCommittedSearch(new URLSearchParams('plateText=ka01&plateMatch=prefix'));
    const exact = parseCommittedSearch(new URLSearchParams('plateText=ka01&plateMatch=exact'));
    expect(prefix.isValid && prefix.filters.plateMatch).toBe('prefix');
    expect(exact.isValid && exact.filters.plateMatch).toBe('exact');
    expect(parseCommittedSearch(new URLSearchParams('plateMatch=prefix')).isValid).toBe(false);
    expect(parseCommittedSearch(new URLSearchParams('plateText=KA01&plateMatch=fuzzy')).isValid).toBe(false);
    expect(parseCommittedSearch(new URLSearchParams('objectClass=Person&plateText=KA01')).isValid).toBe(false);
    expect(parseCommittedSearch(new URLSearchParams('plateText=KA01&plateText=KA02')).isValid).toBe(false);
    if (exact.isValid) expect(removeCriteria(exact.filters, ['plateText'])).toEqual({ objectClass: 'Vehicle' });
  });

  it('refuses a Person-class plate draft on the class field and commits a vehicle draft', () => {
    const base = {
      committed: {},
      timeDirty: { from: false, to: false },
      numericDirty: { duration: false, confidence: false, dwell: false, stationary: false },
      displayTimeZoneId: 'Asia/Kolkata',
    };
    const bad = commitDraft({ ...base, draft: { ...emptyDraft, objectClass: 'Person', plateText: 'ka-01' } });
    expect(bad).toEqual({ ok: false, errors: { objectClass: 'Plate text requires the Vehicle class.' } });
    const good = commitDraft({ ...base, draft: { ...emptyDraft, plateText: 'ka-01', plateMatch: 'exact' } });
    expect(good).toEqual({ ok: true, filters: { objectClass: 'Vehicle', plateText: 'KA01', plateMatch: 'exact' } });
    const invalid = commitDraft({ ...base, draft: { ...emptyDraft, plateText: 'O1' } });
    expect(invalid).toEqual({ ok: false, errors: { plateText: 'Enter 3 to 15 letters or digits' } });
  });
});
