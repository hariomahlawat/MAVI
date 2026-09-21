import { apiJson, apiRequest } from './client';
import type { AnalyticsReadiness } from './videos';

/**
 * The Slice 3 analytics lifecycle endpoints (`Mavi.Contracts/Api/Analytics`),
 * mirrored by hand as the rest of this client mirrors its server contracts.
 * Slice 4 consumes them from the Processing surfaces and invents no new
 * per-run re-analysis endpoint: a failed unit is retried, a stale run is
 * repaired through the camera-level re-analysis that already exists.
 */

export type SceneAnalysisStatus = 'Queued' | 'Running' | 'Completed' | 'Failed' | 'Superseded';

/** One analysis unit. The claim token and its hash are never here; the lease expiry is, on purpose. */
export type SceneAnalysisUnit = {
  analysisId: string;
  processingRunId: string;
  sceneRevisionId: string;
  sceneRevisionNumber: number;
  algorithmVersion: string;
  status: SceneAnalysisStatus;
  attemptCount: number;
  queuedAtUtc: string;
  startedAtUtc: string | null;
  completedAtUtc: string | null;
  leaseExpiresAtUtc: string | null;
  analysedTrackCount: number;
  unavailableTrackCount: number;
  failureCode: string | null;
};

/** GET /api/processing/runs/{id}/analytics */
export type ProcessingRunAnalytics = {
  processingRunId: string;
  readiness: AnalyticsReadiness;
  activeSceneRevisionId: string | null;
  algorithmVersion: string;
  analyses: SceneAnalysisUnit[];
};

export type SceneReanalysisScope = 'latestRuns' | 'allRuns';

/** POST /api/cameras/{id}/scene/analyses — idempotent per identity; the breakdown is the point. */
export type SceneReanalysisAccepted = {
  cameraId: string;
  sceneRevisionId: string;
  algorithmVersion: string;
  scope: SceneReanalysisScope;
  created: number;
  alreadyQueued: number;
  alreadyRunning: number;
  alreadyReady: number;
  failedRequiresRetry: number;
  alreadySuperseded: number;
  runsInScope: number;
};

export function getRunAnalytics(processingRunId: string, signal?: AbortSignal): Promise<ProcessingRunAnalytics> {
  return apiRequest<ProcessingRunAnalytics>(
    `/api/processing/runs/${encodeURIComponent(processingRunId)}/analytics`,
    { signal },
  );
}

export function retryRunAnalytics(processingRunId: string, signal?: AbortSignal): Promise<SceneAnalysisUnit> {
  return apiRequest<SceneAnalysisUnit>(
    `/api/processing/runs/${encodeURIComponent(processingRunId)}/analytics/retry`,
    { method: 'POST', signal },
  );
}

export function requestSceneReanalysis(
  cameraId: string,
  scope: SceneReanalysisScope = 'latestRuns',
  signal?: AbortSignal,
): Promise<SceneReanalysisAccepted> {
  return apiJson<SceneReanalysisAccepted>(
    `/api/cameras/${encodeURIComponent(cameraId)}/scene/analyses`,
    'POST',
    { scope },
    signal,
  );
}

/**
 * The unit that answers for the run's current identity: the camera's active
 * revision and the engine version the server reports. Readiness is derived from
 * it, so this is the unit whose attempt count, failure code and counts the
 * operator is owed.
 */
export function currentUnit(analytics: ProcessingRunAnalytics): SceneAnalysisUnit | undefined {
  if (!analytics.activeSceneRevisionId) return undefined;
  const active = analytics.activeSceneRevisionId.toLowerCase();
  return analytics.analyses.find((unit) =>
    unit.sceneRevisionId.toLowerCase() === active && unit.algorithmVersion === analytics.algorithmVersion);
}

/** The most recent unit that carries facts, whatever identity produced them. */
export function latestFactBearingUnit(analytics: ProcessingRunAnalytics): SceneAnalysisUnit | undefined {
  return [...analytics.analyses]
    .reverse()
    .find((unit) => unit.status === 'Completed' || unit.status === 'Superseded');
}

/** Polling for the run analytics follows the same rule as processing: only Pending moves on its own. */
export function analyticsPollInterval(analytics: ProcessingRunAnalytics | undefined): 2000 | false {
  return analytics?.readiness === 'Pending' ? 2_000 : false;
}
