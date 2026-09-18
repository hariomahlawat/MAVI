import { apiJson, apiRequest } from './client';

export type Camera = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  locationName: string | null;
  timeZoneId: string;
  isActive: boolean;
  createdAtUtc: string;
  updatedAtUtc: string;
};

export type CreateCameraInput = {
  code: string;
  name: string;
  timeZoneId: string;
};

export function listCameras(signal?: AbortSignal): Promise<Camera[]> {
  return apiRequest<Camera[]>('/api/cameras/', { signal });
}

export function getCamera(id: string, signal?: AbortSignal): Promise<Camera> {
  return apiRequest<Camera>(`/api/cameras/${encodeURIComponent(id)}`, { signal });
}

export function createCamera(input: CreateCameraInput, signal?: AbortSignal): Promise<Camera> {
  return apiJson<Camera>('/api/cameras/', 'POST', input, signal);
}
