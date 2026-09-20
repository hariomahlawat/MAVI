import { describe, expect, it } from 'vitest';
import { formatDuration } from './duration';
import { compactTimestamp, formatConfidence, formatCount, formatOffset } from './format';

/** Section 24: the presentation rules, including the honest-absence cases. */

describe('formatConfidence', () => {
  it('uses an integer percent in a list and one decimal in an inspector', () => {
    // A decimal in a dense column is false precision.
    expect(formatConfidence(0.8426, 'list')).toBe('84%');
    expect(formatConfidence(0.8426, 'inspector')).toBe('84.3%');
  });

  it('handles the boundaries', () => {
    expect(formatConfidence(0, 'list')).toBe('0%');
    expect(formatConfidence(1, 'list')).toBe('100%');
    expect(formatConfidence(1, 'inspector')).toBe('100.0%');
  });

  it('shows an em dash rather than inventing a number', () => {
    expect(formatConfidence(Number.NaN)).toBe('—');
    expect(formatConfidence(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('formatOffset', () => {
  it('is mm:ss in a list and mm:ss.t in a player', () => {
    expect(formatOffset(65_400)).toBe('01:05');
    expect(formatOffset(65_400, 'tenths')).toBe('01:05.4');
  });

  it('grows an hours field only when there are hours', () => {
    expect(formatOffset(3_725_000)).toBe('1:02:05');
    expect(formatOffset(3_725_900, 'tenths')).toBe('1:02:05.9');
  });

  it('handles zero and refuses negatives', () => {
    expect(formatOffset(0)).toBe('00:00');
    expect(formatOffset(0, 'tenths')).toBe('00:00.0');
    expect(formatOffset(-1)).toBe('—');
    expect(formatOffset(Number.NaN)).toBe('—');
  });
});

describe('formatDuration', () => {
  it('zero-pads below the leading unit so a column stays aligned', () => {
    expect(formatDuration(3_725_000)).toBe('1h 02m 05s');
    expect(formatDuration(65_000)).toBe('1m 05s');
    expect(formatDuration(5_000)).toBe('5s');
  });

  it('handles zero and refuses negatives', () => {
    expect(formatDuration(0)).toBe('0s');
    expect(formatDuration(-1)).toBe('—');
    expect(formatDuration(Number.NaN)).toBe('—');
  });
});

describe('formatCount', () => {
  it('separates thousands', () => {
    expect(formatCount(1234)).toBe('1,234');
    expect(formatCount(0)).toBe('0');
  });

  it('shows an em dash for a non-finite count', () => {
    expect(formatCount(Number.NaN)).toBe('—');
  });
});

describe('compactTimestamp', () => {
  const zone = 'Asia/Kolkata';

  it('omits the year when it is the current year', () => {
    const text = compactTimestamp('2026-03-04T08:30:00Z', zone, new Date('2026-09-20T00:00:00Z'));
    expect(text).not.toMatch(/2026/);
    expect(text).toMatch(/Mar/);
  });

  it('keeps the year when it is not the current year', () => {
    const text = compactTimestamp('2025-03-04T08:30:00Z', zone, new Date('2026-09-20T00:00:00Z'));
    expect(text).toMatch(/2025/);
  });

  it('never silently uses the browser zone', () => {
    // Per ADR-004 an unknown display zone is disclosed, not guessed.
    expect(compactTimestamp('2026-03-04T08:30:00Z', undefined)).toBe('2026-03-04T08:30:00Z UTC');
  });

  it('shows an em dash for an absent value', () => {
    expect(compactTimestamp(null, zone)).toBe('—');
    expect(compactTimestamp(undefined, zone)).toBe('—');
  });
});
