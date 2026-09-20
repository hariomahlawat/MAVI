import type { UseQueryResult } from '@tanstack/react-query';
import type { AsyncState } from './asyncState';

/**
 * The one place that understands TanStack Query.
 *
 * Section 14.1 permits the boundary to adapt React Query and requires that
 * presentational components never have to. Keeping the import here is what
 * makes the rest of the boundary source-agnostic: anything that can produce an
 * AsyncState can feed the same components.
 */
export function fromQuery<T>(query: UseQueryResult<T>): AsyncState<T> {
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
