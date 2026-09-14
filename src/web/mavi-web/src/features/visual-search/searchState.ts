import { isGuid } from '../../api/client';
import type { TrackObjectClass, TrackSearchFilters } from '../../api/tracks';

export type CommittedTrackSearch = Omit<TrackSearchFilters, 'cursor' | 'limit'>;

export type SearchParseResult =
  | { isValid: true; filters: CommittedTrackSearch; canonicalQuery: string }
  | { isValid: false; filters: CommittedTrackSearch; canonicalQuery: string; error: string };

const supportedKeys = [
  'cameraId',
  'videoAssetId',
  'processingRunId',
  'objectClass',
  'fromUtc',
  'toUtc',
  'minimumDurationMs',
  'minimumConfidence',
] as const;

type SupportedKey = typeof supportedKeys[number];

function singleValue(params: URLSearchParams, key: SupportedKey): { valid: true; value?: string } | { valid: false } {
  const values = params.getAll(key);
  if (values.length === 0) return { valid: true };
  if (values.length !== 1 || values[0].trim() === '') return { valid: false };
  return { valid: true, value: values[0] };
}

function canonicalGuid(raw: string | undefined): string | undefined {
  if (raw === undefined) return undefined;
  return isGuid(raw) ? raw.toLowerCase() : undefined;
}

function canonicalObjectClass(raw: string | undefined): TrackObjectClass | undefined {
  if (raw === undefined) return undefined;
  const normalized = raw.toLowerCase();
  if (normalized === 'person') return 'Person';
  if (normalized === 'vehicle') return 'Vehicle';
  return undefined;
}

const utcPattern = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,7}))?(?:Z|\+00:00)$/;

function canonicalUtc(raw: string | undefined): string | undefined {
  if (raw === undefined) return undefined;
  const match = utcPattern.exec(raw);
  if (!match) return undefined;

  const wholeSecondMs = Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6]),
  );
  const value = new Date(wholeSecondMs);
  if (Number.isNaN(value.getTime())
      || value.getUTCFullYear() !== Number(match[1])
      || value.getUTCMonth() !== Number(match[2]) - 1
      || value.getUTCDate() !== Number(match[3])
      || value.getUTCHours() !== Number(match[4])
      || value.getUTCMinutes() !== Number(match[5])
      || value.getUTCSeconds() !== Number(match[6])) {
    return undefined;
  }

  const significantFraction = (match[7] ?? '').replace(/0+$/, '');
  const fraction = significantFraction.length === 0
    ? '000'
    : significantFraction.length < 3
      ? significantFraction.padEnd(3, '0')
      : significantFraction;
  return match[1] + '-' + match[2] + '-' + match[3]
    + 'T' + match[4] + ':' + match[5] + ':' + match[6]
    + '.' + fraction
    + 'Z';
}

function compareCanonicalUtc(left: string, right: string): number {
  const leftMatch = utcPattern.exec(left);
  const rightMatch = utcPattern.exec(right);
  if (!leftMatch || !rightMatch) throw new RangeError('UTC comparison requires canonical instants.');

  const leftSeconds = Date.UTC(
    Number(leftMatch[1]), Number(leftMatch[2]) - 1, Number(leftMatch[3]),
    Number(leftMatch[4]), Number(leftMatch[5]), Number(leftMatch[6]),
  );
  const rightSeconds = Date.UTC(
    Number(rightMatch[1]), Number(rightMatch[2]) - 1, Number(rightMatch[3]),
    Number(rightMatch[4]), Number(rightMatch[5]), Number(rightMatch[6]),
  );
  if (leftSeconds !== rightSeconds) return leftSeconds < rightSeconds ? -1 : 1;

  const leftFraction = Number((leftMatch[7] ?? '').padEnd(7, '0'));
  const rightFraction = Number((rightMatch[7] ?? '').padEnd(7, '0'));
  return leftFraction === rightFraction ? 0 : leftFraction < rightFraction ? -1 : 1;
}

export function compareUtcInstants(left: string, right: string): number {
  const canonicalLeft = canonicalUtc(left);
  const canonicalRight = canonicalUtc(right);
  if (!canonicalLeft || !canonicalRight) {
    throw new RangeError('UTC comparison requires valid explicit UTC instants.');
  }
  return compareCanonicalUtc(canonicalLeft, canonicalRight);
}

function canonicalDuration(raw: string | undefined): number | undefined {
  if (raw === undefined) return undefined;
  if (!/^\d+$/.test(raw)) return undefined;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}

function canonicalConfidence(raw: string | undefined): number | undefined {
  if (raw === undefined) return undefined;
  if (!/^(?:0(?:\.\d+)?|1(?:\.0+)?)$/.test(raw)) return undefined;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 && value <= 1 ? value : undefined;
}

export function canonicalSearchParams(filters: CommittedTrackSearch): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.cameraId) params.set('cameraId', filters.cameraId.toLowerCase());
  if (filters.videoAssetId) params.set('videoAssetId', filters.videoAssetId.toLowerCase());
  if (filters.processingRunId) params.set('processingRunId', filters.processingRunId.toLowerCase());
  if (filters.objectClass) params.set('objectClass', filters.objectClass);
  if (filters.fromUtc) params.set('fromUtc', canonicalUtc(filters.fromUtc) ?? filters.fromUtc);
  if (filters.toUtc) params.set('toUtc', canonicalUtc(filters.toUtc) ?? filters.toUtc);
  if (filters.minimumDurationMs !== undefined) params.set('minimumDurationMs', String(filters.minimumDurationMs));
  if (filters.minimumConfidence !== undefined) params.set('minimumConfidence', String(filters.minimumConfidence));
  return params;
}

export function canonicalSearchKey(filters: CommittedTrackSearch): string {
  return canonicalSearchParams(filters).toString();
}

export function parseCommittedSearch(params: URLSearchParams): SearchParseResult {
  const raw: Partial<Record<SupportedKey, string>> = {};
  for (const key of supportedKeys) {
    const result = singleValue(params, key);
    if (!result.valid) {
      return {
        isValid: false,
        filters: {},
        canonicalQuery: '',
        error: "Search parameter '" + key + "' must occur exactly once.",
      };
    }
    if (result.value !== undefined) raw[key] = result.value;
  }

  const filters: CommittedTrackSearch = {};

  for (const key of ['cameraId', 'videoAssetId', 'processingRunId'] as const) {
    if (raw[key] === undefined) continue;
    const value = canonicalGuid(raw[key]);
    if (!value) {
      return {
        isValid: false,
        filters: {},
        canonicalQuery: '',
        error: "Search parameter '" + key + "' is not a valid identifier.",
      };
    }
    filters[key] = value;
  }

  if (raw.objectClass !== undefined) {
    const value = canonicalObjectClass(raw.objectClass);
    if (!value) return { isValid: false, filters: {}, canonicalQuery: '', error: 'Object class must be Person or Vehicle.' };
    filters.objectClass = value;
  }

  if (raw.fromUtc !== undefined) {
    const value = canonicalUtc(raw.fromUtc);
    if (!value) return { isValid: false, filters: {}, canonicalQuery: '', error: 'From time must be an explicit UTC instant.' };
    filters.fromUtc = value;
  }

  if (raw.toUtc !== undefined) {
    const value = canonicalUtc(raw.toUtc);
    if (!value) return { isValid: false, filters: {}, canonicalQuery: '', error: 'To time must be an explicit UTC instant.' };
    filters.toUtc = value;
  }

  if (filters.fromUtc && filters.toUtc && compareUtcInstants(filters.fromUtc, filters.toUtc) >= 0) {
    return {
      isValid: false,
      filters,
      canonicalQuery: canonicalSearchKey(filters),
      error: 'From time must be earlier than To time.',
    };
  }

  if (raw.minimumDurationMs !== undefined) {
    const value = canonicalDuration(raw.minimumDurationMs);
    if (value === undefined) {
      return {
        isValid: false,
        filters: {},
        canonicalQuery: '',
        error: 'Minimum duration must be a non-negative integer number of milliseconds.',
      };
    }
    filters.minimumDurationMs = value;
  }

  if (raw.minimumConfidence !== undefined) {
    const value = canonicalConfidence(raw.minimumConfidence);
    if (value === undefined) {
      return {
        isValid: false,
        filters: {},
        canonicalQuery: '',
        error: 'Minimum confidence must be between 0 and 1.',
      };
    }
    filters.minimumConfidence = value;
  }

  return {
    isValid: true,
    filters,
    canonicalQuery: canonicalSearchKey(filters),
  };
}

function scalePlainUnsignedDecimalText(value: string, power: number): string {
  const [integerPart, fractionalPart = ''] = value.split('.');
  const digits = integerPart + fractionalPart;
  const decimalPosition = integerPart.length + power;

  let scaled: string;
  if (decimalPosition <= 0) {
    scaled = '0.' + '0'.repeat(-decimalPosition) + digits;
  } else if (decimalPosition >= digits.length) {
    scaled = digits + '0'.repeat(decimalPosition - digits.length);
  } else {
    scaled = digits.slice(0, decimalPosition) + '.' + digits.slice(decimalPosition);
  }

  const [scaledInteger, scaledFraction = ''] = scaled.split('.');
  const normalizedInteger = scaledInteger.replace(/^0+(?=\d)/, '') || '0';
  const normalizedFraction = scaledFraction.replace(/0+$/, '');
  return normalizedInteger + (normalizedFraction ? '.' + normalizedFraction : '');
}

export function secondsTextToMilliseconds(value: string): number | undefined {
  const trimmed = value.trim();
  if (trimmed === '') return undefined;
  if (!/^\d+(?:\.\d{1,3})?$/.test(trimmed)) {
    throw new RangeError('Minimum duration must use at most three decimal places.');
  }

  const millisecondsText = scalePlainUnsignedDecimalText(trimmed, 3);
  if (millisecondsText.includes('.')) {
    throw new RangeError('Minimum duration must resolve to whole milliseconds.');
  }

  const milliseconds = Number(millisecondsText);
  if (!Number.isSafeInteger(milliseconds) || milliseconds < 0) {
    throw new RangeError('Minimum duration is outside the supported range.');
  }
  return milliseconds;
}

export function confidencePercentTextToFraction(value: string): number | undefined {
  const trimmed = value.trim();
  if (trimmed === '') return undefined;
  if (!/^\d+(?:\.\d{1,2})?$/.test(trimmed)) {
    throw new RangeError('Minimum confidence must use at most two decimal places.');
  }

  const percent = Number(trimmed);
  if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
    throw new RangeError('Minimum confidence must be between 0 and 100 percent.');
  }

  return Number(scalePlainUnsignedDecimalText(trimmed, -2));
}

export function millisecondsToSecondsText(value: number | undefined): string {
  if (value === undefined) return '';
  return String(value / 1000);
}

function decimalScaleByPowerOfTen(value: number, power: number): string {
  if (!Number.isFinite(value)) throw new RangeError('Numeric filter must be finite.');

  const raw = String(value).toLowerCase();
  const [mantissa, exponentText] = raw.split('e');
  const exponent = exponentText === undefined ? 0 : Number(exponentText);
  const [integerPart, fractionalPart = ''] = mantissa.split('.');
  const sign = integerPart.startsWith('-') ? '-' : '';
  const unsignedInteger = sign ? integerPart.slice(1) : integerPart;
  const digits = unsignedInteger + fractionalPart;
  const decimalPosition = unsignedInteger.length + exponent + power;

  let scaled: string;
  if (decimalPosition <= 0) {
    scaled = '0.' + '0'.repeat(-decimalPosition) + digits;
  } else if (decimalPosition >= digits.length) {
    scaled = digits + '0'.repeat(decimalPosition - digits.length);
  } else {
    scaled = digits.slice(0, decimalPosition) + '.' + digits.slice(decimalPosition);
  }

  const [scaledInteger, scaledFraction = ''] = scaled.split('.');
  const normalizedInteger = scaledInteger.replace(/^0+(?=\d)/, '') || '0';
  const normalizedFraction = scaledFraction.replace(/0+$/, '');
  return sign + normalizedInteger + (normalizedFraction ? '.' + normalizedFraction : '');
}

export function confidenceFractionToPercentText(value: number | undefined): string {
  if (value === undefined) return '';
  return decimalScaleByPowerOfTen(value, 2);
}
