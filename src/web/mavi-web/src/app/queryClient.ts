import { QueryClient } from '@tanstack/react-query';

export function createMaviQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 5_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export const queryKeys = {
  cameras: ['cameras'] as const,
  camera: (id: string) => ['camera', id] as const,
  videos: ['videos'] as const,
  video: (id: string) => ['video', id] as const,
  videoProcessing: (id: string) => ['video-processing', id] as const,
  systemConfig: ['system-config'] as const,
  platformHealth: ['platform-health'] as const,
};
