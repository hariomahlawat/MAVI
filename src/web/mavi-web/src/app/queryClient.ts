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
  trackSearch: (fingerprint: string) => ['tracks', 'search', fingerprint] as const,
  /**
   * A Track's detail is one cache entry per analytic identity it was read
   * against: a historical revision's facts and the current ones are different
   * answers to different questions and must never overwrite each other.
   */
  track: (id: string, analyticsIdentity = '') => ['track', id, analyticsIdentity] as const,
  cameraScene: (cameraId: string) => ['camera-scene', cameraId] as const,
  cameraSceneRevision: (cameraId: string, revisionNumber: number) =>
    ['camera-scene-revision', cameraId, revisionNumber] as const,
  trajectory: (artifactId: string) => ['trajectory', artifactId] as const,
  runAttestation: (processingRunId: string) => ['processing-run', processingRunId, 'attestation'] as const,
  runAnalytics: (processingRunId: string) => ['processing-run', processingRunId, 'analytics'] as const,
  /**
   * One cache entry per camera and per exact question. The analytics answer is
   * pinned to the scene revision and visibility sequence the server resolved it
   * against, so two windows, two bucket sizes or two grids are different answers
   * and must never overwrite each other.
   */
  cameraAnalyticsAggregates: (cameraId: string, query: string) =>
    ['camera-analytics', cameraId, 'aggregates', query] as const,
  cameraAnalyticsHeatmap: (cameraId: string, query: string) =>
    ['camera-analytics', cameraId, 'heatmap', query] as const,
  systemConfig: ['system-config'] as const,
  platformHealth: ['platform-health'] as const,
};
