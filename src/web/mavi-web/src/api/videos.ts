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
