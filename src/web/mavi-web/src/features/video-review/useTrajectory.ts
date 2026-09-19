import { useQuery } from '@tanstack/react-query';
import { fetchArtifactBytes } from '../../api/artifacts';
import { ApiError } from '../../api/client';
import { queryKeys } from '../../app/queryClient';
import { parseTrajectory, type TrajectoryPoint } from './trajectory';

/**
 * The Track's trajectory artefact, decoded. Keyed by artefact id, so two
 * Tracks never share a cache entry and a re-processed video never shows a
 * stale path. Disabled when the Track carries no trajectory.
 */
export function useTrajectory(artifactId: string | null, contentUrl: string | null) {
  return useQuery<TrajectoryPoint[]>({
    queryKey: queryKeys.trajectory(artifactId ?? 'none'),
    queryFn: async ({ signal }) => parseTrajectory(await fetchArtifactBytes(contentUrl as string, signal)),
    enabled: Boolean(artifactId && contentUrl),
    staleTime: Infinity,
    retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1,
  });
}
