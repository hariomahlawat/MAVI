import type {
  TrackDetailAnalytics,
  TrackDetailLineCrossing,
  TrackDetailZoneSummary,
  TrackDetailZoneVisit,
} from '../api/tracks';
import type { SceneRevision, SceneTripLine, SceneZone } from '../api/scene';

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

/**
 * A complete analysed block, pinned to one immutable revision.
 *
 * Every Slice-5 surface reads its facts from here, so the fixture carries the
 * whole shape rather than the subset any one test needs: a test that overrides
 * one field must not accidentally assert against a different contract from the
 * one the API sends.
 */
export function analysedAnalytics(overrides: Partial<TrackDetailAnalytics> = {}): TrackDetailAnalytics {
  return {
    sceneRevisionId: ANALYSED_REVISION_ID,
    sceneRevisionNumber: 4,
    algorithmVersion: 'scene-analytics-v1',
    status: 'Analysed',
    unavailableReason: null,
    referencePoint: 'bbox-centre',
    sampleCount: 120,
    gapCount: 0,
    gapTotalMs: 0,
    zoneSummaries: [],
    zoneVisits: [],
    lineCrossings: [],
    motion: null,
    otherIdentities: [],
    ...overrides,
  };
}

export const ANALYSED_REVISION_ID = '018f3f5a-2f70-7a2b-8a12-2d02f4c21460';
export const OTHER_REVISION_ID = '018f3f5a-2f70-7a2b-8a12-2d02f4c21461';
export const CAMERA_ID = '11111111-1111-7111-8111-111111111111';

export function zoneVisit(overrides: Partial<TrackDetailZoneVisit> = {}): TrackDetailZoneVisit {
  return {
    zoneId: ZONE_A,
    visitIndex: 0,
    entryOffsetMs: 11_000,
    exitOffsetMs: 14_000,
    entryTimestampUtc: '2026-09-14T02:30:11Z',
    exitTimestampUtc: '2026-09-14T02:30:14Z',
    dwellMs: 3_000,
    beganInside: false,
    endedInside: false,
    closedByGap: false,
    entryHeading: 'E',
    exitHeading: 'W',
    ...overrides,
  };
}

export function zoneSummary(overrides: Partial<TrackDetailZoneSummary> = {}): TrackDetailZoneSummary {
  return {
    zoneId: ZONE_A,
    visitCount: 1,
    totalDwellMs: 3_000,
    firstEntryTimestampUtc: '2026-09-14T02:30:11Z',
    lastExitTimestampUtc: '2026-09-14T02:30:14Z',
    loitering: false,
    loiteringThresholdSeconds: 60,
    loiteringDwellMs: 3_000,
    ...overrides,
  };
}

export function lineCrossing(overrides: Partial<TrackDetailLineCrossing> = {}): TrackDetailLineCrossing {
  return {
    lineId: LINE_A,
    crossingIndex: 0,
    offsetMs: 12_500,
    timestampUtc: '2026-09-14T02:30:12Z',
    direction: 'aToB',
    pointX: 0.4,
    pointY: 0.6,
    ...overrides,
  };
}

export const ZONE_A = '018f3f5a-2f70-7a2b-8a12-2d02f4c21470';
export const ZONE_B = '018f3f5a-2f70-7a2b-8a12-2d02f4c21471';
export const ZONE_C = '018f3f5a-2f70-7a2b-8a12-2d02f4c21472';
export const ZONE_D = '018f3f5a-2f70-7a2b-8a12-2d02f4c21473';
export const LINE_A = '018f3f5a-2f70-7a2b-8a12-2d02f4c21480';

/** A square zone, so a projection assertion has obvious expected numbers. */
export function sceneZone(overrides: Partial<SceneZone> = {}): SceneZone {
  return {
    zoneId: ZONE_A,
    name: 'Forecourt',
    kind: 'General',
    enabled: true,
    vertices: [{ x: 0.2, y: 0.2 }, { x: 0.6, y: 0.2 }, { x: 0.6, y: 0.8 }, { x: 0.2, y: 0.8 }],
    loiteringThresholdSeconds: 60,
    ...overrides,
  };
}

export function sceneTripLine(overrides: Partial<SceneTripLine> = {}): SceneTripLine {
  return {
    lineId: LINE_A,
    name: 'Gate line',
    enabled: true,
    a: { x: 0.1, y: 0.5 },
    b: { x: 0.9, y: 0.5 },
    directed: true,
    aToBLabel: 'Inbound',
    bToALabel: 'Outbound',
    ...overrides,
  };
}

export function sceneRevision(overrides: Partial<SceneRevision> = {}): SceneRevision {
  return {
    revisionId: ANALYSED_REVISION_ID,
    revisionNumber: 4,
    cameraId: CAMERA_ID,
    createdAtUtc: '2026-09-10T08:00:00Z',
    createdBy: 'operator',
    note: null,
    referenceFrameVideoAssetId: null,
    referenceFrameOffsetMs: null,
    zones: [sceneZone()],
    tripLines: [sceneTripLine()],
    analyticsEnabled: true,
    ...overrides,
  };
}
