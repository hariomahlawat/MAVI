import { describe, expect, it } from 'vitest';
import {
  canonicalSearchKey,
  confidenceFractionToPercentText,
  confidencePercentTextToFraction,
  compareUtcInstants,
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
    const highPrecision = parseCommittedSearch(new URLSearchParams('fromUtc=2026-09-14T08%3A00%3A00.1234000Z'));
    expect(highPrecision.isValid).toBe(true);
    if (highPrecision.isValid) expect(highPrecision.filters.fromUtc).toBe('2026-09-14T08:00:00.1234Z');
    expect(parseCommittedSearch(new URLSearchParams('fromUtc=2026-09-14T08%3A00%3A00.12345678Z')).isValid).toBe(false);
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

  it('round-trips canonical committed state including advanced scopes', () => {
    const source = new URLSearchParams(
      'processingRunId=018F3F5A-2F70-7A2B-8A12-2D02F4C21431'
      + '&videoAssetId=018F3F5A-2F70-7A2B-8A12-2D02F4C21421'
      + '&cameraId=018F3F5A-2F70-7A2B-8A12-2D02F4C21412'
      + '&objectClass=vehicle'
      + '&minimumDurationMs=001250'
      + '&minimumConfidence=0.800'
    );

    const first = parseCommittedSearch(source);
    expect(first.isValid).toBe(true);
    if (!first.isValid) return;

    expect(first.filters).toEqual({
      cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
      videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
      processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
      objectClass: 'Vehicle',
      minimumDurationMs: 1250,
      minimumConfidence: 0.8,
    });

    const second = parseCommittedSearch(new URLSearchParams(first.canonicalQuery));
    expect(second).toEqual(first);
  });

  it('canonicalization removes unknown parameters from the semantic URL', () => {
    const parsed = parseCommittedSearch(new URLSearchParams(
      'utm_source=x&objectClass=Person&debug=true',
    ));
    expect(parsed.isValid).toBe(true);
    if (parsed.isValid) {
      expect(parsed.canonicalQuery).toBe('objectClass=Person');
      expect(parsed.canonicalQuery).not.toContain('utm_');
      expect(parsed.canonicalQuery).not.toContain('debug');
    }
  });

  it('orders UTC instants at backend precision instead of truncating to JavaScript milliseconds', () => {
    expect(compareUtcInstants(
      '2026-09-14T08:00:00.1234566Z',
      '2026-09-14T08:00:00.1234567Z',
    )).toBeLessThan(0);
    expect(compareUtcInstants(
      '2026-09-14T08:00:00.1234000Z',
      '2026-09-14T08:00:00.1234Z',
    )).toBe(0);
  });

  it('formats committed confidence percentages without floating-point artifacts', () => {
    expect(confidenceFractionToPercentText(0.0007)).toBe('0.07');
    expect(confidenceFractionToPercentText(0.00075)).toBe('0.075');
    expect(confidenceFractionToPercentText(0.91)).toBe('91');
    expect(confidenceFractionToPercentText(0)).toBe('0');
    expect(confidenceFractionToPercentText(1)).toBe('100');
    expect(confidenceFractionToPercentText(1e-7)).toBe('0.00001');
  });

  it('converts operator duration and confidence input without silent clamping', () => {
    expect(secondsTextToMilliseconds('1.250')).toBe(1250);
    expect(secondsTextToMilliseconds('1.001')).toBe(1001);
    expect(secondsTextToMilliseconds('0.029')).toBe(29);
    expect(confidencePercentTextToFraction('91.25')).toBe(0.9125);
    expect(confidencePercentTextToFraction('0.07')).toBe(0.0007);
    expect(String(confidencePercentTextToFraction('0.07'))).toBe('0.0007');
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
