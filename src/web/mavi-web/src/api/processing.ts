import { apiRequest } from './client';

export type ProcessingRunGpuAttestation = {
  name: string;
  index: number;
  vramBytes: number;
  driverVersion: string;
  cudaRuntimeVersion: string;
  uuid: string;
  pciBusId: string;
  computeCapability: string;
};

export type ProcessingRunPlatformAttestation = {
  system: string;
  release: string;
  version: string;
  machine: string;
  processor: string;
  pythonVersion: string;
  pythonImplementation: string;
  pythonBuild: string[];
  pythonCompiler: string;
};

/** GET /api/processing/runs/{id}/attestation — the completed run's provenance. */
export type ProcessingRunAttestation = {
  processingRunId: string;
  videoAssetId: string;
  completedAtUtc: string;
  pipelineVersion: string;
  modelId: string;
  modelVersion: string;
  modelManifestSha256: string;
  checkpointSha256: string;
  resolvedConfigSha256: string;
  pipelineProfileId: string;
  pipelineProfileVersion: string;
  pipelineProfileSha256: string;
  qualificationId: string | null;
  qualificationSha256: string | null;
  verificationStatus: string;
  runtimeProfileId: string;
  runtimeProfileSha256: string;
  runtimeVariant: string;
  platformLockSha256: string | null;
  maviBuild: string;
  maviCommit: string;
  configuredDevicePolicy: string;
  configuredDeviceIndex: number;
  deviceResolutionReason: string | null;
  actualDevice: string;
  platform: ProcessingRunPlatformAttestation;
  gpu: ProcessingRunGpuAttestation | null;
  dependencyVersions: Record<string, string>;
  detectorName: string | null;
  detectorVersion: string | null;
  trackerName: string | null;
  trackerVersion: string | null;
  framesProcessed: number;
  tracksCreated: number;
  processingDurationMs: number;
};

export function getRunAttestation(processingRunId: string, signal?: AbortSignal): Promise<ProcessingRunAttestation> {
  return apiRequest<ProcessingRunAttestation>(
    `/api/processing/runs/${encodeURIComponent(processingRunId)}/attestation`,
    { signal },
  );
}
