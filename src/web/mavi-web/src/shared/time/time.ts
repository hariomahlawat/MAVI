export type InstantInput = string | Date;

// Input validation
function parseInstant(value: InstantInput): Date {
  const instant = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  if (Number.isNaN(instant.getTime())) throw new RangeError('Invalid absolute timestamp.');
  return instant;
}

// Explicit-zone presentation
export function formatInstant(
  utcValue: InstantInput,
  displayTimeZoneId: string,
  options: Intl.DateTimeFormatOptions = {},
): string {
  return new Intl.DateTimeFormat('en-IN', { ...options, timeZone: displayTimeZoneId }).format(parseInstant(utcValue));
}

export function formatDate(utcValue: InstantInput, displayTimeZoneId: string): string {
  return formatInstant(utcValue, displayTimeZoneId, { year: 'numeric', month: '2-digit', day: '2-digit' });
}

export function formatTime(utcValue: InstantInput, displayTimeZoneId: string): string {
  return formatInstant(utcValue, displayTimeZoneId, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}
