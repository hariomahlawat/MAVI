import { describe, expect, it } from 'vitest';
import { configuredUtcToWallTime, configuredWallTimeToUtc } from './wallTime';

describe('configured IANA wall-time conversion', () => {
  it('converts Asia/Kolkata wall time without workstation-zone arithmetic', () => {
    expect(configuredWallTimeToUtc('2026-09-14T08:00:00', 'Asia/Kolkata'))
      .toBe('2026-09-14T02:30:00.000Z');
    expect(configuredUtcToWallTime('2026-09-14T02:30:00Z', 'Asia/Kolkata'))
      .toBe('2026-09-14T08:00:00');
  });

  it('converts a normal daylight-saving date deterministically', () => {
    expect(configuredWallTimeToUtc('2026-09-14T08:00:00', 'America/New_York'))
      .toBe('2026-09-14T12:00:00.000Z');
  });

  it('rejects nonexistent spring-forward wall time', () => {
    expect(() => configuredWallTimeToUtc('2026-03-08T02:30:00', 'America/New_York'))
      .toThrow(/does not exist/i);
  });

  it('rejects ambiguous fall-back wall time', () => {
    expect(() => configuredWallTimeToUtc('2026-11-01T01:30:00', 'America/New_York'))
      .toThrow(/ambiguous/i);
  });

  it('rejects invalid zone and invalid calendar wall value', () => {
    expect(() => configuredWallTimeToUtc('2026-09-14T08:00:00', 'Not/AZone')).toThrow(/timezone/i);
    expect(() => configuredWallTimeToUtc('2026-02-31T08:00:00', 'UTC')).toThrow(/invalid/i);
  });
});
