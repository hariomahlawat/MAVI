import { formatDateTime, formatInstant } from '../time/time';

/**
 * Confidence density (section 24): an integer percent in a list, one decimal in
 * an inspector. A decimal in a dense list is false precision — it implies the
 * model distinguishes 84.2 from 84.3 in a column the operator is scanning, not
 * reading.
 */
export type ConfidenceDensity = 'list' | 'inspector';

export function formatConfidence(value: number, density: ConfidenceDensity = 'inspector'): string {
  if (!Number.isFinite(value)) return '—';
  return (value * 100).toFixed(density === 'list' ? 0 : 1) + '%';
}

/**
 * Media offset (section 24): `mm:ss.t` in a player, where a tenth is the
 * difference between landing on the crossing and landing just after it, and
 * `mm:ss` in a list, where it is noise.
 *
 * The baseline's comment promised tenths and the code never produced them;
 * precision is now an explicit argument rather than a claim in a comment.
 */
export type OffsetPrecision = 'seconds' | 'tenths';

export function formatOffset(offsetMs: number, precision: OffsetPrecision = 'seconds'): string {
  if (!Number.isFinite(offsetMs) || offsetMs < 0) return '—';
  const totalSeconds = offsetMs / 1000;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  const tenth = precision === 'tenths' ? '.' + Math.floor((offsetMs % 1000) / 100) : '';
  if (hours > 0) return `${hours}:${pad(minutes)}:${pad(seconds)}${tenth}`;
  return `${pad(minutes)}:${pad(seconds)}${tenth}`;
}

/** Counts carry thousands separators and tabular figures (section 24). */
export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-IN').format(value);
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  const units = ['B', 'KiB', 'MiB', 'GiB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

/**
 * Timestamp in the configured display zone, falling back to explicit UTC when
 * the zone is not yet known. Per ADR-004 the browser zone is never an authority.
 */
export function displayTimestamp(value: string | null | undefined, displayTimeZoneId?: string): string {
  if (!value) return '—';
  if (!displayTimeZoneId) return value + ' UTC';
  try {
    return formatDateTime(value, displayTimeZoneId);
  } catch {
    return 'Invalid timestamp';
  }
}

/**
 * The compact table form of section 24: never wraps, and drops the year when it
 * is the current one — the year is the least informative part of a timestamp in
 * a column of today's activity, and the width it costs is the most.
 */
export function compactTimestamp(
  value: string | null | undefined,
  displayTimeZoneId?: string,
  now: Date = new Date(),
): string {
  if (!value) return '—';
  if (!displayTimeZoneId) return value + ' UTC';
  try {
    const instant = new Date(value);
    const yearHere = new Intl.DateTimeFormat('en-IN', { timeZone: displayTimeZoneId, year: 'numeric' });
    const sameYear = yearHere.format(instant) === yearHere.format(now);
    return formatInstant(value, displayTimeZoneId, {
      ...(sameYear ? {} : { year: 'numeric' }),
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    });
  } catch {
    return 'Invalid timestamp';
  }
}

export function frameRateText(numerator: number, denominator: number): string {
  if (!denominator) return '—';
  const fps = numerator / denominator;
  return (Number.isInteger(fps) ? String(fps) : fps.toFixed(2)) + ' fps';
}
