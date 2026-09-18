import { apiRequest } from './client';

export type PlatformHealth = {
  status: string;
  component: string;
  version: string;
};

export function getPlatformHealth(signal?: AbortSignal): Promise<PlatformHealth> {
  return apiRequest<PlatformHealth>('/api/health', { signal });
}
