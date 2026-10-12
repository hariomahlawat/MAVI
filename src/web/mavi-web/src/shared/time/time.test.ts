import { describe, expect, it } from 'vitest';
import { dateTimeFormat, formatTime } from './time';

describe('formatters are made once (§38 no jank; X3)', () => {
  it('returns the same formatter for the same locale and options, and another for others', () => {
    const a = dateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', year: 'numeric' });
    expect(dateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', year: 'numeric' })).toBe(a);
    expect(dateTimeFormat('en-IN', { timeZone: 'UTC', year: 'numeric' })).not.toBe(a);
  });

  it('still refuses a zone it cannot use, every time, keeping nothing', () => {
    expect(() => dateTimeFormat('en-IN', { timeZone: 'Not/AZone' })).toThrow(RangeError);
    expect(() => dateTimeFormat('en-IN', { timeZone: 'Not/AZone' })).toThrow(RangeError);
  });

  it('formats as a new formatter would', () => {
    expect(formatTime('2026-09-14T02:30:00Z', 'Asia/Kolkata')).toBe(new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Kolkata' }).format(new Date('2026-09-14T02:30:00Z')));
  });
});

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
