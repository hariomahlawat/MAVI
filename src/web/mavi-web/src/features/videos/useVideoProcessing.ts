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
    let pending = 0;
    let failed = 0;
    results.forEach((result, index) => {
      if (result.data) byVideo.set(videoIds[index], result.data);
      if (result.isPending) pending += 1;
      if (result.isError) failed += 1;
    });
    return { byVideo, pending, failed };
  }, [results, videoIds]);
}
