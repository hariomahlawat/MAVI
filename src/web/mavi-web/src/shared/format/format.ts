import { formatDateTime } from '../time/time';

export function formatConfidence(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return (value * 100).toFixed(1) + '%';
}

/** mm:ss or h:mm:ss for a media offset, with tenths when under a minute. */
export function formatOffset(offsetMs: number): string {
  if (!Number.isFinite(offsetMs) || offsetMs < 0) return '—';
  const totalSeconds = offsetMs / 1000;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  if (hours > 0) return `${hours}:${pad(minutes)}:${pad(seconds)}`;
  return `${pad(minutes)}:${pad(seconds)}`;
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
 * the zone is not yet known. The browser zone is never used as an authority.
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

export function frameRateText(numerator: number, denominator: number): string {
  if (!denominator) return '—';
  const fps = numerator / denominator;
  return (Number.isInteger(fps) ? String(fps) : fps.toFixed(2)) + ' fps';
}
