import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  analyticsPollInterval,
  currentUnit,
  getRunAnalytics,
  latestFactBearingUnit,
  requestSceneReanalysis,
  retryRunAnalytics,
  type ProcessingRunAnalytics,
  type SceneAnalysisUnit,
} from './sceneAnalytics';

const runId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21431';
const active = '018f3f5a-2f70-7a2b-8a12-2d02f4c21482';
const older = '018f3f5a-2f70-7a2b-8a12-2d02f4c21481';

function unit(overrides: Partial<SceneAnalysisUnit>): SceneAnalysisUnit {
  return {
    analysisId: '018f3f5a-2f70-7a2b-8a12-2d02f4c214a1', processingRunId: runId, sceneRevisionId: active, sceneRevisionNumber: 2,
    algorithmVersion: 'scene-analytics-v1', status: 'Completed', attemptCount: 1, queuedAtUtc: '2026-09-21T06:00:00Z',
    startedAtUtc: null, completedAtUtc: null, leaseExpiresAtUtc: null, analysedTrackCount: 1, unavailableTrackCount: 0, failureCode: null,
    ...overrides,
  };
}

function analytics(units: SceneAnalysisUnit[], readiness: ProcessingRunAnalytics['readiness'] = 'Ready'): ProcessingRunAnalytics {
  return { processingRunId: runId, readiness, activeSceneRevisionId: active, algorithmVersion: 'scene-analytics-v1', analyses: units };
}

describe('scene analytics client', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn()); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('picks the unit for the active revision and current engine, not the newest row', () => {
    const superseded = unit({ sceneRevisionId: older, sceneRevisionNumber: 1, status: 'Superseded' });
    const olderEngine = unit({ algorithmVersion: 'scene-analytics-v0', status: 'Completed' });
    const current = unit({ status: 'Queued' });

    expect(currentUnit(analytics([superseded, olderEngine, current], 'Pending'))).toBe(current);
    expect(currentUnit({ ...analytics([current]), activeSceneRevisionId: null })).toBeUndefined();
    expect(latestFactBearingUnit(analytics([superseded, current], 'Pending'))).toBe(superseded);
  });

  it('polls only while pending', () => {
    expect(analyticsPollInterval(analytics([], 'Pending'))).toBe(2_000);
    for (const readiness of ['Ready', 'Failed', 'Stale', 'Disabled', 'NotConfigured'] as const) {
      expect(analyticsPollInterval(analytics([], readiness))).toBe(false);
    }
    expect(analyticsPollInterval(undefined)).toBe(false);
  });

  it('addresses the Slice 3 endpoints exactly, inventing no per-run re-analysis', async () => {
    const ok = () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
    vi.mocked(fetch).mockResolvedValueOnce(ok()).mockResolvedValueOnce(ok()).mockResolvedValueOnce(ok());

    await getRunAnalytics(runId);
    expect(fetch).toHaveBeenLastCalledWith(`/api/processing/runs/${runId}/analytics`, expect.anything());

    await retryRunAnalytics(runId);
    expect(fetch).toHaveBeenLastCalledWith(`/api/processing/runs/${runId}/analytics/retry`, expect.objectContaining({ method: 'POST' }));

    await requestSceneReanalysis('018f3f5a-2f70-7a2b-8a12-2d02f4c21412');
    expect(fetch).toHaveBeenLastCalledWith(
      '/api/cameras/018f3f5a-2f70-7a2b-8a12-2d02f4c21412/scene/analyses',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ scope: 'latestRuns' }) }),
    );
  });
});
