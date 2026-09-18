import { describe, expect, it } from 'vitest';
import { calculateReviewSeekSeconds } from './seek';

describe('Task-16 evidence seek', () => {
  it('applies one-second preroll', () => {
    expect(calculateReviewSeekSeconds(197_420, 600)).toBeCloseTo(196.420, 3);
  });

  it('clamps preroll at zero', () => {
    expect(calculateReviewSeekSeconds(500, 600)).toBe(0);
  });

  it('clamps seek below finite media duration', () => {
    expect(calculateReviewSeekSeconds(20_000, 10)).toBeCloseTo(9.999, 3);
  });

  it('fails safe for invalid offsets', () => {
    expect(calculateReviewSeekSeconds(-1, 10)).toBe(0);
    expect(calculateReviewSeekSeconds(Number.NaN, 10)).toBe(0);
  });
});
