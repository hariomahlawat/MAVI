import { useQueries } from '@tanstack/react-query';
import { useMemo } from 'react';
import { ApiError } from '../../api/client';
import { getProcessingStatus, processingPollInterval, type ProcessingStatus } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';

/**
 * Latest run status for a set of videos. Each video is one query so the cache
 * is shared with the per-video Processing page, and only videos whose status
 * is still moving are polled.
 */
export function useVideoProcessing(videoIds: readonly string[]) {
  const results = useQueries({
    queries: videoIds.map((id) => ({
      queryKey: queryKeys.videoProcessing(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => getProcessingStatus(id, signal),
      retry: (count: number, error: unknown) => !(error instanceof ApiError && error.status === 404) && count < 1,
      refetchInterval: (query: { state: { error: unknown; data: ProcessingStatus | undefined } }) =>
        query.state.error ? false : processingPollInterval(query.state.data),
    })),
  });

  return useMemo(() => {
    const byVideo = new Map<string, ProcessingStatus>();
    const errors = new Map<string, unknown>();
    const refetchers = new Map<string, () => void>();
    let pending = 0;
    results.forEach((result, index) => {
      const id = videoIds[index];
      if (result.data) byVideo.set(id, result.data);
      if (result.isPending) pending += 1;
      if (result.isError) errors.set(id, result.error);
      refetchers.set(id, () => { void result.refetch(); });
    });
    return {
      byVideo,
      /** Videos whose latest-run status could not be loaded, by id. */
      errors,
      pending,
      failed: errors.size,
      /** Re-request one video's status after a failure. */
      retry: (id: string) => refetchers.get(id)?.(),
    };
  }, [results, videoIds]);
}
