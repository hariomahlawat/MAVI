import { apiRequest } from './client';

export type SystemConfig = {
  displayTimeZoneId: string;
};

export function getSystemConfig(signal?: AbortSignal): Promise<SystemConfig> {
  return apiRequest<SystemConfig>('/api/system/config', { signal });
}
