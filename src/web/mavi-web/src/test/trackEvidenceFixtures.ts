import type { TrackDetail, TrackEvidenceObservation, TrackEvidenceRole, TrackRepresentative } from '../api/tracks';
import { notConfiguredAnalytics } from './analyticsFixtures';

/**
 * Evidence Set fixtures shaped like the S1.3a Track-detail response.
 *
 * The default offsets are deliberately not in rank order (Early diverse is the
 * earliest frame, Late diverse the latest, the Representative in between), so
 * a component that sorted by time instead of rank would be caught.
 */
const DEFAULTS: Record<TrackEvidenceRole, { offsetMs: number; confidence: number; quality: number; box: [number, number, number, number] }> = {
  Representative: { offsetMs: 12_000, confidence: 0.96, quality: 0.9, box: [0.5, 0.5, 0.25, 0.5] },
  NearView: { offsetMs: 14_600, confidence: 0.93, quality: 0.84, box: [0.42, 0.38, 0.3, 0.55] },
  EarlyDiverse: { offsetMs: 10_400, confidence: 0.88, quality: 0.71, box: [0.6, 0.52, 0.18, 0.4] },
  LateDiverse: { offsetMs: 16_800, confidence: 0.9, quality: 0.76, box: [0.3, 0.45, 0.22, 0.48] },
};

const ROLE_DIGIT: Record<TrackEvidenceRole, string> = { Representative: '1', NearView: '2', EarlyDiverse: '3', LateDiverse: '4' };

/** A server-authored crop URL, as the API writes it. Test data only. */
export function cropUrl(artifactId: string): string {
  return `/api/artifacts/${artifactId}/content`;
}

export function evidenceObservation(
  role: TrackEvidenceRole,
  rank: number,
  overrides: Partial<TrackEvidenceObservation> = {},
): TrackEvidenceObservation {
  const d = DEFAULTS[role];
  const artifactId = `018f3f5a-2f70-7a2b-8a12-2d02f4c2148${ROLE_DIGIT[role]}`;
  return {
    observationId: `018f3f5a-2f70-7a2b-8a12-2d02f4c2147${ROLE_DIGIT[role]}`,
    evidenceRole: role,
    evidenceRank: rank,
    sourceFrameNumber: Math.round((d.offsetMs * 25) / 1000),
    videoOffsetMs: d.offsetMs,
    timestampUtc: new Date(Date.UTC(2026, 8, 14, 2, 30, 0) + d.offsetMs - 10_000).toISOString(),
    confidence: d.confidence,
    qualityScore: d.quality,
    selectionScore: d.quality - 0.05,
    boundingBox: { x: d.box[0], y: d.box[1], width: d.box[2], height: d.box[3] },
    evidenceArtifactId: artifactId,
    evidenceContentUrl: cropUrl(artifactId),
    ...overrides,
  };
}

/** A contiguous Evidence Set in canonical order: the roles given, ranked 0..n−1. */
export function evidenceSet(roles: readonly TrackEvidenceRole[]): TrackEvidenceObservation[] {
  return roles.map((role, rank) => evidenceObservation(role, rank));
}

export const FULL_EVIDENCE_SET_ROLES: readonly TrackEvidenceRole[] = ['Representative', 'NearView', 'EarlyDiverse', 'LateDiverse'];

/** The wire's compatibility object, derived from rank 0 exactly as the server derives it. */
export function compatibilityRepresentative(observations: readonly TrackEvidenceObservation[]): TrackRepresentative | null {
  const first = observations[0];
  if (!first) return null;
  return {
    observationId: first.observationId,
    sourceFrameNumber: first.sourceFrameNumber,
    videoOffsetMs: first.videoOffsetMs,
    timestampUtc: first.timestampUtc,
    confidence: first.confidence,
    qualityScore: first.qualityScore,
    boundingBox: first.boundingBox,
    thumbnailArtifactId: first.evidenceArtifactId,
    thumbnailContentUrl: first.evidenceContentUrl,
  };
}

/** Both halves of a Track detail's evidence, coherent as the server sends them. */
export function trackEvidence(observations: TrackEvidenceObservation[]): {
  observations: TrackEvidenceObservation[];
  representative: TrackRepresentative | null;
} {
  return { observations, representative: compatibilityRepresentative(observations) };
}

/**
 * A compatibility Representative that deliberately disagrees with rank 0 in
 * every field the UI could show: another Observation, frame, offset,
 * confidence, quality, box and crop. The UI must render none of it.
 */
export const DISAGREEING_REPRESENTATIVE: TrackRepresentative = {
  observationId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21499',
  sourceFrameNumber: 9999,
  videoOffsetMs: 3_300,
  timestampUtc: '2026-09-14T02:29:53Z',
  confidence: 0.11,
  qualityScore: 0.222,
  boundingBox: { x: 0.01, y: 0.02, width: 0.03, height: 0.04 },
  thumbnailArtifactId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21498',
  thumbnailContentUrl: '/api/artifacts/018f3f5a-2f70-7a2b-8a12-2d02f4c21498/content',
};

/**
 * A Track detail carrying the given Evidence Set, with its compatibility
 * Representative derived from rank 0 unless the caller overrides it.
 */
export function trackDetailWithEvidence(
  observations: TrackEvidenceObservation[],
  overrides: Partial<TrackDetail> = {},
): TrackDetail {
  return {
    id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21451',
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
    videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
    camera: { id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412', code: 'CAM-01', name: 'North Gate' },
    objectClass: 'Person',
    localTrackNumber: 7,
    startOffsetMs: 10_000,
    endOffsetMs: 18_000,
    startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:08Z',
    durationMs: 8_000,
    detectionCount: 42,
    meanConfidence: 0.91,
    maxConfidence: 0.98,
    reviewStatus: 'Unreviewed',
    processing: { pipelineVersion: 'phase1', detectorName: 'RTMDet', detectorVersion: '1', trackerName: 'ByteTrack', trackerVersion: '1', completedAtUtc: '2026-09-14T02:40:00Z' },
    video: { recordingStartUtc: '2026-09-14T02:26:42Z', recordingEndUtc: '2026-09-14T02:36:42Z', durationMs: 600_000, width: 1920, height: 1080, frameRateNumerator: 25, frameRateDenominator: 1, videoContentUrl: '/api/videos/v/content' },
    ...trackEvidence(observations),
    trajectoryArtifactId: null,
    trajectoryContentUrl: null,
    analytics: notConfiguredAnalytics(),
    ...overrides,
  };
}
