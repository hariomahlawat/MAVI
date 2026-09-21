import { apiRequest } from './client';

export const MAXIMUM_VIDEO_FILE_SIZE_BYTES = 3 * 1024 * 1024 * 1024;

export type VideoAsset = {
  id: string;
  cameraId: string;
  originalFileName: string;
  recordingStartUtc: string;
  recordingEndUtc: string;
  recordingTimeZoneId: string;
  recordingUtcOffsetMinutes: number;
  durationMs: number;
  width: number;
  height: number;
  frameRateNumerator: number;
  frameRateDenominator: number;
  codecName: string | null;
  processingStatus: string;
  importedAtUtc: string;
};

/**
 * Analytics readiness of a processing run, derived by the server per request
 * (`SceneAnalyticsContractRules.ReadinessValues`). It is the one readiness
 * vocabulary the product has; the Processing surfaces render it as text.
 */
export const ANALYTICS_READINESS = ['NotConfigured', 'Disabled', 'Pending', 'Ready', 'Failed', 'Stale'] as const;
export type AnalyticsReadiness = (typeof ANALYTICS_READINESS)[number];

export type ProcessingRunStatus = {
  processingRunId: string;
  status: string;
  pipeline: string;
  pipelineVersion: string;
  workerId: string | null;
  queuedAtUtc: string;
  startedAtUtc: string | null;
  completedAtUtc: string | null;
  progressPercent: number;
  attemptCount: number;
  failureCode: string | null;
  framesProcessed: number;
  tracksCreated: number;
  analyticsReadiness: AnalyticsReadiness;
};

export type ProcessingStatus = {
  videoStatus: string;
  latestRun: ProcessingRunStatus | null;
};

export type QueueProcessingResponse = {
  processingRunId: string;
};

export type ImportVideoInput = {
  cameraId: string;
  recordingStartLocal: string;
  file: File;
};

export function getVideo(id: string, signal?: AbortSignal): Promise<VideoAsset> {
  return apiRequest<VideoAsset>(`/api/videos/${encodeURIComponent(id)}`, { signal });
}

export function listVideos(signal?: AbortSignal): Promise<VideoAsset[]> {
  return apiRequest<VideoAsset[]>('/api/videos/', { signal });
}

export function getProcessingStatus(id: string, signal?: AbortSignal): Promise<ProcessingStatus> {
  return apiRequest<ProcessingStatus>(`/api/videos/${encodeURIComponent(id)}/processing`, { signal });
}

export function queueProcessing(id: string, signal?: AbortSignal): Promise<QueueProcessingResponse> {
  return apiRequest<QueueProcessingResponse>(`/api/videos/${encodeURIComponent(id)}/process`, {
    method: 'POST',
    signal,
  });
}

export function importVideo(input: ImportVideoInput, signal?: AbortSignal): Promise<VideoAsset> {
  const form = new FormData();
  form.append('cameraId', input.cameraId);
  form.append('recordingStartLocal', input.recordingStartLocal);
  form.append('file', input.file);

  return apiRequest<VideoAsset>('/api/videos/import', {
    method: 'POST',
    signal,
    body: form,
  });
}

export function isProcessingActive(status: ProcessingStatus | undefined): boolean {
  if (!status) return false;
  return status.videoStatus === 'Queued'
    || status.videoStatus === 'Processing'
    || status.latestRun?.status === 'Queued'
    || status.latestRun?.status === 'Running';
}

/**
 * Whether analytics are still on their way for the latest run. `Pending` is the
 * one readiness that changes on its own — the host will queue and analyse the
 * unit — so it is the one worth polling for; every other readiness changes only
 * when an operator acts or a scene is saved (plan §S "Processing readiness").
 */
export function isAnalyticsPending(status: ProcessingStatus | undefined): boolean {
  return status?.latestRun?.analyticsReadiness === 'Pending';
}

/**
 * Polling continues while the video is being processed and, after that, while
 * analytics for the finished run are still pending — a Processed video whose
 * analytics have not landed is still moving as far as the operator is concerned.
 */
export function processingPollInterval(status: ProcessingStatus | undefined): 2000 | false {
  return isProcessingActive(status) || isAnalyticsPending(status) ? 2_000 : false;
}
