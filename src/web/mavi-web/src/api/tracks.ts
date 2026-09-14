import { apiRequest } from './client';

export type TrackObjectClass = 'Person' | 'Vehicle';

export type TrackSearchFilters = {
  cameraId?: string;
  videoAssetId?: string;
  processingRunId?: string;
  objectClass?: TrackObjectClass;
  fromUtc?: string;
  toUtc?: string;
  minimumDurationMs?: number;
  minimumConfidence?: number;
  cursor?: string;
  limit?: number;
};

export type TrackSearchResponse = {
  items: TrackSearchItem[];
  nextCursor: string | null;
};

export type TrackSearchItem = {
  id: string;
  processingRunId: string;
  videoAssetId: string;
  cameraId: string;
  cameraCode: string;
  cameraName: string;
  objectClass: TrackObjectClass;
  startTimestampUtc: string;
  endTimestampUtc: string;
  startOffsetMs: number;
  endOffsetMs: number;
  durationMs: number;
  detectionCount: number;
  meanConfidence: number;
  maxConfidence: number;
  reviewStatus: string;
  thumbnailArtifactId: string | null;
  thumbnailContentUrl: string | null;
  videoContentUrl: string;
};

export type TrackCamera = {
  id: string;
  code: string;
  name: string;
};

export type TrackProcessing = {
  pipelineVersion: string;
  detectorName: string | null;
  detectorVersion: string | null;
  trackerName: string | null;
  trackerVersion: string | null;
  completedAtUtc: string;
};

export type TrackVideo = {
  recordingStartUtc: string;
  recordingEndUtc: string;
  durationMs: number;
  width: number;
  height: number;
  frameRateNumerator: number;
  frameRateDenominator: number;
  videoContentUrl: string;
};

export type TrackBoundingBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type TrackRepresentative = {
  observationId: string;
  sourceFrameNumber: number;
  videoOffsetMs: number;
  timestampUtc: string;
  confidence: number;
  qualityScore: number;
  boundingBox: TrackBoundingBox;
  thumbnailArtifactId: string | null;
  thumbnailContentUrl: string | null;
};

export type TrackDetail = {
  id: string;
  processingRunId: string;
  videoAssetId: string;
  camera: TrackCamera;
  objectClass: TrackObjectClass;
  localTrackNumber: number;
  startOffsetMs: number;
  endOffsetMs: number;
  startTimestampUtc: string;
  endTimestampUtc: string;
  durationMs: number;
  detectionCount: number;
  meanConfidence: number;
  maxConfidence: number;
  reviewStatus: string;
  processing: TrackProcessing;
  video: TrackVideo;
  representative: TrackRepresentative | null;
  trajectoryArtifactId: string | null;
  trajectoryContentUrl: string | null;
};

export function serializePlainDecimal(value: number): string {
  if (!Number.isFinite(value)) return String(value);

  const raw = String(value).toLowerCase();
  if (!raw.includes('e')) return raw;

  const [mantissa, exponentText] = raw.split('e');
  const exponent = Number(exponentText);
  const sign = mantissa.startsWith('-') ? '-' : '';
  const unsignedMantissa = sign ? mantissa.slice(1) : mantissa;
  const [integerPart, fractionalPart = ''] = unsignedMantissa.split('.');
  const digits = integerPart + fractionalPart;
  const decimalPosition = integerPart.length + exponent;

  let expanded: string;
  if (decimalPosition <= 0) {
    expanded = '0.' + '0'.repeat(-decimalPosition) + digits;
  } else if (decimalPosition >= digits.length) {
    expanded = digits + '0'.repeat(decimalPosition - digits.length);
  } else {
    expanded = digits.slice(0, decimalPosition) + '.' + digits.slice(decimalPosition);
  }

  const [expandedInteger, expandedFraction = ''] = expanded.split('.');
  const normalizedInteger = expandedInteger.replace(/^0+(?=\d)/, '') || '0';
  const normalizedFraction = expandedFraction.replace(/0+$/, '');
  return sign + normalizedInteger + (normalizedFraction ? '.' + normalizedFraction : '');
}

const orderedFilterKeys: ReadonlyArray<keyof TrackSearchFilters> = [
  'cameraId',
  'videoAssetId',
  'processingRunId',
  'objectClass',
  'fromUtc',
  'toUtc',
  'minimumDurationMs',
  'minimumConfidence',
  'cursor',
  'limit',
];

export function serializeTrackSearchFilters(filters: TrackSearchFilters): string {
  const params = new URLSearchParams();
  for (const key of orderedFilterKeys) {
    const value = filters[key];
    if (value === undefined || value === null || value === '') continue;
    params.set(key, key === 'minimumConfidence' ? serializePlainDecimal(value as number) : String(value));
  }
  return params.toString();
}

export function searchTracks(filters: TrackSearchFilters, signal?: AbortSignal): Promise<TrackSearchResponse> {
  const query = serializeTrackSearchFilters(filters);
  const path = '/api/tracks' + (query ? '?' + query : '');
  return apiRequest<TrackSearchResponse>(path, { signal });
}

export function getTrack(trackId: string, signal?: AbortSignal): Promise<TrackDetail> {
  return apiRequest<TrackDetail>('/api/tracks/' + encodeURIComponent(trackId), { signal });
}
