import type { InfiniteData, UseInfiniteQueryResult, UseQueryResult } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import type { AsyncState } from './asyncState';

/**
 * The one place that understands TanStack Query.
 *
 * Section 14.1 permits the boundary to adapt React Query and requires that
 * presentational components never have to. Keeping the import here is what
 * makes the rest of the boundary source-agnostic: anything that can produce an
 * AsyncState can feed the same components.
 */
export function fromQuery<T, E = unknown>(query: UseQueryResult<T, E>): AsyncState<T> {
  if (query.data !== undefined) {
    /*
     * Data already on screen and a refetch has since failed. Throwing the data
     * away to show an error block would be a regression: the operator loses a
     * real answer because a later poll failed. The surface is told it is
     * degraded and decides how loudly to say so.
     */
    return query.isError ? { kind: 'ready', data: query.data, degraded: { error: query.error } } : { kind: 'ready', data: query.data };
  }
  if (query.isError) return { kind: 'unavailable', error: query.error };
  return { kind: 'loading' };
}

/**
 * A paged result set is one region whose content is the pages that arrived.
 *
 * The first page decides the region's state. A later page failing is a
 * *continuation* failure: the results already on screen are real and stay, and
 * the failure belongs beside the control that asked for more (§17), which the
 * caller renders — it is not reported here, because it is not the region's
 * state. A failed refetch of a set already on screen is degraded, as for any
 * other region.
 */
export function fromInfiniteQuery<TPage, TItem, E = unknown>(
  query: UseInfiniteQueryResult<InfiniteData<TPage, unknown>, E>,
  flatten: (pages: TPage[]) => TItem[],
): AsyncState<TItem[]> {
  const pages = query.data?.pages;
  if (pages !== undefined && pages.length > 0) {
    const items = flatten(pages);
    const refetchFailed = query.isError && !query.isFetchNextPageError;
    return refetchFailed ? { kind: 'ready', data: items, degraded: { error: query.error } } : { kind: 'ready', data: items };
  }
  if (query.isError) return { kind: 'unavailable', error: query.error };
  return { kind: 'loading' };
}

/**
 * The operator sentence for a failure (§14): the API's own detail and code
 * where the failure carries them, otherwise the caller's fallback.
 */
export function describeError(error: unknown, fallback: string): string {
  return error instanceof ApiError ? `${error.detail} (${error.code})` : fallback;
}
