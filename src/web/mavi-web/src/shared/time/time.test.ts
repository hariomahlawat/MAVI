import { describe, expect, it } from 'vitest';
import { formatTime } from './time';

describe('explicit timezone formatting', () => {
  it('formats a UTC instant in the configured Kolkata timezone', () => {
    expect(formatTime('2026-09-09T02:30:00Z', 'Asia/Kolkata')).toBe('08:00');
  });

  it('is generic across IANA timezones', () => {
    expect(formatTime('2026-09-09T02:30:00Z', 'America/New_York')).toBe('22:30');
  });

  it.each(['2026-09-09T02:30:00Z', '2026-09-09T02:30:00.000Z', '2026-09-09T02:30:00+00:00', '2026-09-09T08:00:00+05:30'])('accepts an explicit instant %s', value => {
    expect(() => formatTime(value, 'UTC')).not.toThrow();
  });

  it.each(['2026-09-09T02:30:00', '2026-09-09 02:30:00'])('rejects timezone-less timestamp %s', value => {
    expect(() => formatTime(value, 'UTC')).toThrow(RangeError);
  });

  it('rejects invalid timestamps predictably', () => {
    expect(() => formatTime('not-an-instant', 'UTC')).toThrow(RangeError);
  });
});
