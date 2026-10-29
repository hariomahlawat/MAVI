import { describe, expect, it } from 'vitest';
import { emptyDraft, type SearchDraft } from './SearchFilterRail';
import { commitDraft } from './searchValidation';
import type { CommittedTrackSearch } from './searchState';

const clean = { from: false, to: false };
const numeric = { duration: false, confidence: false, dwell: false, stationary: false };

function commit(draft: Partial<SearchDraft>, committed: CommittedTrackSearch = {}) {
  return commitDraft({
    draft: { ...emptyDraft, ...draft },
    committed,
    timeDirty: clean,
    numericDirty: numeric,
    displayTimeZoneId: 'Asia/Kolkata',
  });
}

describe('PoC S4 appearance query: committing the draft', () => {
  it('commits a description, normalised', () => {
    expect(commit({ appearanceQuery: '  white   van ' })).toEqual({ ok: true, filters: { appearanceQuery: 'white van' } });
  });

  it('refuses a description beside plate text, on the appearance field', () => {
    const result = commit({ appearanceQuery: 'white van', plateText: 'KA01AB1234' });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.appearanceQuery).toMatch(/cannot be combined with plate text, attribute or analytics filters/);
      expect(result.errors.plateText).toBeUndefined();
    }
  });

  it('refuses a description beside an analytics filter, including a link-only one', () => {
    const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';
    expect(commit({ appearanceQuery: 'van', cameraId, loitering: 'true' }).ok).toBe(false);
    const linkOnly = commit(
      { appearanceQuery: 'van', cameraId },
      { cameraId, sceneRevisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21499' },
    );
    expect(linkOnly.ok).toBe(false);
  });

  it('refuses a description over 200 characters', () => {
    const result = commit({ appearanceQuery: 'a'.repeat(201) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.appearanceQuery).toBe('Enter 1 to 200 characters.');
  });

  it('keeps a held snapshot for the same search and drops it for a new one', () => {
    const committed = { appearanceQuery: 'white van', appearanceSnapshot: 'tok' };
    expect(commit({ appearanceQuery: 'white van' }, committed)).toEqual({ ok: true, filters: committed });
    expect(commit({ appearanceQuery: 'red van' }, committed)).toEqual({ ok: true, filters: { appearanceQuery: 'red van' } });
    expect(commit({ appearanceQuery: 'white van', objectClass: 'Vehicle' }, committed))
      .toEqual({ ok: true, filters: { appearanceQuery: 'white van', objectClass: 'Vehicle' } });
    expect(commit({}, committed)).toEqual({ ok: true, filters: {} });
  });
});
