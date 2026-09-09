import { describe, expect, it } from 'vitest';
import { formatTime } from './time';

describe('explicit timezone formatting', () => {
  it('formats a UTC instant in the configured Kolkata timezone', () => {
    expect(formatTime('2026-09-09T02:30:00Z', 'Asia/Kolkata')).toBe('08:00');
  });

  it('is generic across IANA timezones', () => {
    expect(formatTime('2026-09-09T02:30:00Z', 'America/New_York')).toBe('22:30');
  });

  it('rejects invalid timestamps predictably', () => {
    expect(() => formatTime('not-an-instant', 'UTC')).toThrow(RangeError);
  });
});
