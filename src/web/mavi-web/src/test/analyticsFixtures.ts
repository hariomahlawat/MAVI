import type { TrackDetailAnalytics } from '../api/tracks';

/** A detail analytics block for a camera that has never been configured: no facts, no identity. */
export function notConfiguredAnalytics(overrides: Partial<TrackDetailAnalytics> = {}): TrackDetailAnalytics {
  return {
    sceneRevisionId: null,
    sceneRevisionNumber: null,
    algorithmVersion: 'scene-analytics-v1',
    status: 'NotConfigured',
    unavailableReason: null,
    referencePoint: null,
    sampleCount: null,
    gapCount: null,
    gapTotalMs: null,
    zoneSummaries: [],
    zoneVisits: [],
    lineCrossings: [],
    motion: null,
    otherIdentities: [],
    ...overrides,
  };
}
