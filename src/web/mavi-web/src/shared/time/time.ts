export type InstantInput = string | Date;

// Input validation
function parseInstant(value: InstantInput): Date {
  if (typeof value === 'string' && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) {
    throw new RangeError('Absolute timestamp must include an explicit UTC or numeric offset.');
  }
  const instant = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  if (Number.isNaN(instant.getTime())) throw new RangeError('Invalid absolute timestamp.');
  return instant;
}

/**
 * One formatter per locale and options, made once and reused. Building an
 * `Intl.DateTimeFormat` costs far more than using one, and a table formats a
 * timestamp in every cell: choosing the line crossings report built several
 * hundred in one task, which made it a long task (§38 "no jank on
 * interaction"; X3). A formatter that cannot be built (an invalid zone) still
 * throws, and is not kept.
 */
const dateTimeFormats = new Map<string, Intl.DateTimeFormat>();
export function dateTimeFormat(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = locale + JSON.stringify(options);
  let format = dateTimeFormats.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, options);
    dateTimeFormats.set(key, format);
  }
  return format;
}

// Explicit-zone presentation
export function formatInstant(
  utcValue: InstantInput,
  displayTimeZoneId: string,
  options: Intl.DateTimeFormatOptions = {},
): string {
  return dateTimeFormat('en-IN', { ...options, timeZone: displayTimeZoneId }).format(parseInstant(utcValue));
}

export function formatDate(utcValue: InstantInput, displayTimeZoneId: string): string {
  return formatInstant(utcValue, displayTimeZoneId, { year: 'numeric', month: '2-digit', day: '2-digit' });
}

export function formatTime(utcValue: InstantInput, displayTimeZoneId: string): string {
  return formatInstant(utcValue, displayTimeZoneId, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}

export function formatDateTime(utcValue: InstantInput, displayTimeZoneId: string): string {
  return formatInstant(utcValue, displayTimeZoneId, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  });
}
