type WallParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

const wallPattern = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

function createFormatter(timeZoneId: string): Intl.DateTimeFormat {
  try {
    return new Intl.DateTimeFormat('en-CA-u-ca-gregory-nu-latn', {
      timeZone: timeZoneId,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
  } catch {
    throw new RangeError('Display timezone is invalid.');
  }
}

function parseWall(value: string): WallParts {
  const match = wallPattern.exec(value);
  if (!match) throw new RangeError('Wall time must use YYYY-MM-DDTHH:mm or YYYY-MM-DDTHH:mm:ss.');

  const parts: WallParts = {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
    second: match[6] ? Number(match[6]) : 0,
  };

  if (parts.month < 1 || parts.month > 12 || parts.day < 1 || parts.day > 31
      || parts.hour > 23 || parts.minute > 59 || parts.second > 59) {
    throw new RangeError('Wall time is invalid.');
  }

  const check = new Date(Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second));
  if (check.getUTCFullYear() !== parts.year
      || check.getUTCMonth() !== parts.month - 1
      || check.getUTCDate() !== parts.day
      || check.getUTCHours() !== parts.hour
      || check.getUTCMinutes() !== parts.minute
      || check.getUTCSeconds() !== parts.second) {
    throw new RangeError('Wall time is invalid.');
  }

  return parts;
}

function zonedParts(formatter: Intl.DateTimeFormat, instantMs: number): WallParts {
  const entries = formatter.formatToParts(new Date(instantMs));
  const values = new Map(entries.map((part) => [part.type, part.value]));
  return {
    year: Number(values.get('year')),
    month: Number(values.get('month')),
    day: Number(values.get('day')),
    hour: Number(values.get('hour')),
    minute: Number(values.get('minute')),
    second: Number(values.get('second')),
  };
}

function offsetAt(formatter: Intl.DateTimeFormat, instantMs: number): number {
  const aligned = Math.floor(instantMs / 1000) * 1000;
  const parts = zonedParts(formatter, aligned);
  const localAsUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
  return localAsUtc - aligned;
}

function sameWall(left: WallParts, right: WallParts): boolean {
  return left.year === right.year
    && left.month === right.month
    && left.day === right.day
    && left.hour === right.hour
    && left.minute === right.minute
    && left.second === right.second;
}

export function configuredWallTimeToUtc(localValue: string, displayTimeZoneId: string): string {
  const requested = parseWall(localValue);
  const formatter = createFormatter(displayTimeZoneId);
  const naiveMs = Date.UTC(
    requested.year,
    requested.month - 1,
    requested.day,
    requested.hour,
    requested.minute,
    requested.second,
  );

  const offsets = new Set<number>();
  for (const hours of [-72, -48, -24, -12, 0, 12, 24, 48, 72]) {
    offsets.add(offsetAt(formatter, naiveMs + hours * 60 * 60 * 1000));
  }

  const candidates = new Set<number>();
  for (const offset of offsets) {
    const candidate = naiveMs - offset;
    if (sameWall(zonedParts(formatter, candidate), requested)) candidates.add(candidate);
  }

  if (candidates.size === 0) {
    throw new RangeError('The selected wall time does not exist in the configured timezone.');
  }
  if (candidates.size > 1) {
    throw new RangeError('The selected wall time is ambiguous in the configured timezone.');
  }

  return new Date(Array.from(candidates)[0]).toISOString();
}

export function configuredUtcToWallTime(utcValue: string, displayTimeZoneId: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(utcValue)) {
    throw new RangeError('Absolute timestamp must include an explicit UTC or numeric offset.');
  }
  const instant = new Date(utcValue);
  if (Number.isNaN(instant.getTime())) throw new RangeError('Absolute timestamp is invalid.');

  const parts = zonedParts(createFormatter(displayTimeZoneId), instant.getTime());
  const pad = (value: number) => String(value).padStart(2, '0');
  return String(parts.year)
    + '-' + pad(parts.month)
    + '-' + pad(parts.day)
    + 'T' + pad(parts.hour)
    + ':' + pad(parts.minute)
    + ':' + pad(parts.second);
}
