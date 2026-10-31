import { QueryClient } from '@tanstack/react-query';

/**
 * MAVI's API is always on loopback, so whether the browser thinks it has an
 * Internet connection says nothing about whether the API can be reached.
 * TanStack Query's default `networkMode: 'online'` pauses every query and
 * mutation while `navigator.onLine` is false. With the network adapters
 * disabled on an air-gapped machine, that leaves pages on their loading state
 * indefinitely, without a request ever being sent. `'always'` sends the request
 * regardless; a local API that does not answer still fails through the bounded
 * read (`api/client.ts`) and shows its Retry.
 */
const LOCAL_API_NETWORK_MODE = 'always' as const;

export function createMaviQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 5_000,
        refetchOnWindowFocus: false,
        networkMode: LOCAL_API_NETWORK_MODE,
      },
      mutations: {
        retry: false,
        networkMode: LOCAL_API_NETWORK_MODE,
      },
    },
  });
}

export const queryKeys = {
  deployment: ['system', 'deployment'] as const,
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
  /**
   * One entry per explicit similarity request: the operator asked for it, so a
   * second press is a second request (`serial`), never a cached answer.
   */
  similarTracks: (id: string, request: string, serial: number) => ['track-similar', id, request, serial] as const,
  /** PoC S6 (ADR-022): a Track's face state, a transient query image, and the gallery. */
  trackFaces: (id: string) => ['track-faces', id] as const,
  faceQuery: (queryId: string) => ['face-query', queryId] as const,
  faceGallery: ['face-gallery'] as const,
  /**
   * PoC S11-full (ADR-027): a Track's review state and its decision history
   * share the `['track-review', id]` prefix, so one invalidation after a
   * decision refreshes both.
   */
  trackReview: (id: string) => ['track-review', id] as const,
  trackReviewHistory: (id: string) => ['track-review', id, 'history'] as const,
  /** Every case read shares the `['cases']` prefix: any case write invalidates them all. */
  cases: ['cases'] as const,
  caseList: (subject: string) => ['cases', 'list', subject] as const,
  caseDetail: (id: string) => ['cases', 'detail', id] as const,
  /** One entry per exact audit filter (its canonical query string, without the cursor). */
  audit: (filter: string) => ['audit', filter] as const,
  /** PoC S7 (ADR-023): Entity candidates, their per-camera-pair summary, and one Entity. */
  entityCandidates: (filter: object) => ['entity-candidates', filter] as const,
  entityCandidateSummary: ['entity-candidates', 'summary'] as const,
  entity: (id: string) => ['entity', id] as const,
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
  attributeVocabulary: ['visual-attributes', 'vocabulary'] as const,
  platformHealth: ['platform-health'] as const,
};
