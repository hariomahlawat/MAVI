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

function canonicalUtc(raw: string | undefined): string | undefined {
  if (raw === undefined) return undefined;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(?:Z|\+00:00)$/.exec(raw);
  if (!match) return undefined;

  const value = new Date(raw);
  if (Number.isNaN(value.getTime())) return undefined;
  if (value.getUTCFullYear() !== Number(match[1])
      || value.getUTCMonth() !== Number(match[2]) - 1
      || value.getUTCDate() !== Number(match[3])
      || value.getUTCHours() !== Number(match[4])
      || value.getUTCMinutes() !== Number(match[5])
      || value.getUTCSeconds() !== Number(match[6])) {
    return undefined;
  }
  return value.toISOString();
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

  if (filters.fromUtc && filters.toUtc && Date.parse(filters.fromUtc) >= Date.parse(filters.toUtc)) {
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

export function secondsTextToMilliseconds(value: string): number | undefined {
  const trimmed = value.trim();
  if (trimmed === '') return undefined;
  if (!/^\d+(?:\.\d{1,3})?$/.test(trimmed)) {
    throw new RangeError('Minimum duration must use at most three decimal places.');
  }
  const seconds = Number(trimmed);
  const milliseconds = seconds * 1000;
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
  return percent / 100;
}

export function millisecondsToSecondsText(value: number | undefined): string {
  if (value === undefined) return '';
  return String(value / 1000);
}

export function confidenceFractionToPercentText(value: number | undefined): string {
  if (value === undefined) return '';
  return String(value * 100);
}
