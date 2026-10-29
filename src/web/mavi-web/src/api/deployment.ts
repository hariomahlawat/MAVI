import { apiRequest } from './client';

/** The PoC profile (ADR-020); the only profile whose disclosure the shell must show. */
export const POC_PROFILE = 'poc-single-host';

export type DeploymentDevice = {
  requestedPolicy: string;
  resolvedPolicy: string;
  reason: string;
  runtimePackId: string | null;
  runtimeVariant: string | null;
  resolvedAtUtc: string | null;
  /** True when the record comes from the launcher's readiness check rather than a running worker. */
  verifyOnly: boolean;
};

export type DeploymentPack = {
  kind: string;
  role: string;
  capabilityId: string | null;
  packId: string;
  variant: string | null;
  verificationStatus: string;
  note: string | null;
  /** The licence the installer read from the pack's own notice file (PoC S3); absent for packs that record none. */
  licence?: string | null;
};

/** A role runtime's own device record (PoC S3: the plates role), disclosed beside the Vision worker's. */
export type DeploymentRoleDevice = {
  role: string;
  deviceStatus: 'reported' | 'not-reported' | 'unavailable';
  device: DeploymentDevice | null;
};

/** `GET /api/system/deployment` (`mavi-deployment-disclosure-v1`). */
export type DeploymentDisclosure = {
  schemaVersion: string;
  profile: string;
  productionQualified: boolean;
  evidenceClass: string | null;
  statement: string | null;
  metadataStatus: 'verified' | 'unavailable' | 'not-configured';
  applicationRevision: string | null;
  installedAtUtc: string | null;
  deviceStatus: 'reported' | 'not-reported' | 'unavailable';
  device: DeploymentDevice | null;
  packs: DeploymentPack[];
  roleDevices?: DeploymentRoleDevice[] | null;
};

export function getDeploymentDisclosure(signal?: AbortSignal): Promise<DeploymentDisclosure> {
  return apiRequest<DeploymentDisclosure>('/api/system/deployment', { signal });
}
