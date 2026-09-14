import { describe, expect, it } from 'vitest';
import {
  canonicalSearchKey,
  confidencePercentTextToFraction,
  parseCommittedSearch,
  secondsTextToMilliseconds,
} from './searchState';

const cameraId = '018F3F5A-2F70-7A2B-8A12-2D02F4C21412';

describe('Task-16 committed search state', () => {
  it('parses and canonicalizes URL state independent of parameter order and casing', () => {
    const parsed = parseCommittedSearch(new URLSearchParams(
      'objectClass=person&cameraId=' + cameraId
      + '&fromUtc=2026-09-14T02%3A30%3A00Z&minimumConfidence=0.80',
    ));

    expect(parsed).toEqual({
      isValid: true,
      filters: {
        cameraId: cameraId.toLowerCase(),
        objectClass: 'Person',
        fromUtc: '2026-09-14T02:30:00.000Z',
        minimumConfidence: 0.8,
      },
      canonicalQuery:
        'cameraId=' + cameraId.toLowerCase()
        + '&objectClass=Person'
        + '&fromUtc=2026-09-14T02%3A30%3A00.000Z'
        + '&minimumConfidence=0.8',
    });
  });

  it('rejects duplicate supported parameters rather than choosing one', () => {
    const params = new URLSearchParams();
    params.append('objectClass', 'Person');
    params.append('objectClass', 'Vehicle');

    const parsed = parseCommittedSearch(params);

    expect(parsed.isValid).toBe(false);
    if (!parsed.isValid) expect(parsed.error).toMatch(/exactly once/i);
  });

  it('rejects malformed identities, UTC bounds and inverted intervals', () => {
    expect(parseCommittedSearch(new URLSearchParams('cameraId=bad')).isValid).toBe(false);
    expect(parseCommittedSearch(new URLSearchParams('fromUtc=2026-09-14T08%3A00%3A00')).isValid).toBe(false);
    expect(parseCommittedSearch(new URLSearchParams('fromUtc=2026-02-31T08%3A00%3A00Z')).isValid).toBe(false);
    expect(parseCommittedSearch(new URLSearchParams('fromUtc=2026-09-14T08%3A00%3A00.1234Z')).isValid).toBe(false);
    expect(parseCommittedSearch(new URLSearchParams(
      'fromUtc=2026-09-14T03%3A00%3A00Z&toUtc=2026-09-14T02%3A00%3A00Z',
    )).isValid).toBe(false);
  });

  it('ignores unknown parameters for backend semantics', () => {
    const parsed = parseCommittedSearch(new URLSearchParams('utm_source=x&objectClass=Vehicle'));
    expect(parsed.isValid).toBe(true);
    if (parsed.isValid) {
      expect(parsed.filters).toEqual({ objectClass: 'Vehicle' });
      expect(parsed.canonicalQuery).toBe('objectClass=Vehicle');
    }
  });

  it('converts operator duration and confidence input without silent clamping', () => {
    expect(secondsTextToMilliseconds('1.250')).toBe(1250);
    expect(confidencePercentTextToFraction('91.25')).toBe(0.9125);
    expect(() => secondsTextToMilliseconds('-1')).toThrow();
    expect(() => secondsTextToMilliseconds('1.2345')).toThrow();
    expect(() => confidencePercentTextToFraction('100.1')).toThrow();
  });

  it('produces one canonical cache identity', () => {
    expect(canonicalSearchKey({
      cameraId: cameraId.toLowerCase(),
      objectClass: 'Person',
    })).toBe('cameraId=' + cameraId.toLowerCase() + '&objectClass=Person');
  });
});
