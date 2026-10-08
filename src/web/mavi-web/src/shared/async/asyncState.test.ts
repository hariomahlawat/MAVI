import type { UseInfiniteQueryResult, UseQueryResult } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { combineStates, type AsyncState } from './asyncState';
import { describeError, fromInfiniteQuery, fromQuery } from './fromQuery';

/**
 * State *selection* (§14.1). The rule every test here protects: a failed
 * request can never be read as an empty one, because the union carries no data
 * on the unavailable variant, and data already on screen survives a later
 * failure as `degraded` rather than being thrown away.
 */

describe('fromQuery', () => {
  const query = (over: Partial<UseQueryResult<string[]>>) => over as UseQueryResult<string[]>;

  it('maps a first load to loading', () => {
    expect(fromQuery(query({ data: undefined, isError: false }))).toEqual({ kind: 'loading' });
  });

  it('maps a failed first load to unavailable, never to empty data', () => {
    const error = new Error('boom');
    const state = fromQuery(query({ data: undefined, isError: true, error }));
    expect(state).toEqual({ kind: 'unavailable', error });
    // There is no `data` to misread: the union does not carry one here.
    expect('data' in state).toBe(false);
  });

  it('maps a successful empty response to ready with an empty payload', () => {
    expect(fromQuery(query({ data: [], isError: false }))).toEqual({ kind: 'ready', data: [] });
  });

  it('keeps the last good data when a refetch fails, and marks it degraded', () => {
    const error = new Error('later');
    expect(fromQuery(query({ data: ['a'], isError: true, error }))).toEqual({ kind: 'ready', data: ['a'], degraded: { error } });
  });

  it('keeps data on screen while a background refetch is in flight: no loading flash', () => {
    // isFetching is deliberately not consulted: a refetch is not a first load.
    expect(fromQuery(query({ data: ['a'], isError: false, isFetching: true }))).toEqual({ kind: 'ready', data: ['a'] });
  });
});

describe('fromInfiniteQuery', () => {
  type Page = { items: string[] };
  const flatten = (pages: Page[]) => pages.flatMap((page) => page.items);
  const query = (over: Record<string, unknown>) => over as unknown as UseInfiniteQueryResult<{ pages: Page[]; pageParams: unknown[] }>;

  it('loads until the first page answers', () => {
    expect(fromInfiniteQuery(query({ data: undefined, isError: false }), flatten)).toEqual({ kind: 'loading' });
  });

  it('is unavailable when the first page fails', () => {
    const error = new Error('first page');
    expect(fromInfiniteQuery(query({ data: undefined, isError: true, error }), flatten)).toEqual({ kind: 'unavailable', error });
  });

  it('keeps the pages that arrived when a later page fails: a continuation failure is not the region state', () => {
    const error = new Error('page 2');
    const state = fromInfiniteQuery(
      query({ data: { pages: [{ items: ['a', 'b'] }] }, isError: true, isFetchNextPageError: true, error }),
      flatten,
    );
    expect(state).toEqual({ kind: 'ready', data: ['a', 'b'] });
  });

  it('marks a failed refresh of a set already on screen degraded', () => {
    const error = new Error('refresh');
    const state = fromInfiniteQuery(
      query({ data: { pages: [{ items: ['a'] }] }, isError: true, isFetchNextPageError: false, error }),
      flatten,
    );
    expect(state).toEqual({ kind: 'ready', data: ['a'], degraded: { error } });
  });

  it('reports a successful empty first page as ready and empty', () => {
    expect(fromInfiniteQuery(query({ data: { pages: [{ items: [] }] }, isError: false }), flatten)).toEqual({ kind: 'ready', data: [] });
  });
});

describe('combineStates: one region on two requests', () => {
  const loading: AsyncState<number> = { kind: 'loading' };
  const ready = (n: number): AsyncState<number> => ({ kind: 'ready', data: n });
  const failed = (message: string): AsyncState<number> => ({ kind: 'unavailable', error: new Error(message) });

  it('loads until both answer', () => {
    expect(combineStates(ready(1), loading)).toEqual({ kind: 'loading' });
  });

  it('is unavailable when either failed, reporting one cause, even while the other still loads', () => {
    const state = combineStates(loading, failed('scene'));
    expect(state.kind).toBe('unavailable');
    expect(state.kind === 'unavailable' && (state.error as Error).message).toBe('scene');
    const first = combineStates(failed('camera'), failed('scene'));
    expect(first.kind === 'unavailable' && (first.error as Error).message).toBe('camera');
  });

  it('carries both payloads when both answered, degraded if either refresh failed', () => {
    expect(combineStates(ready(1), ready(2))).toEqual({ kind: 'ready', data: [1, 2] });
    const error = new Error('later');
    expect(combineStates(ready(1), { kind: 'ready', data: 2, degraded: { error } })).toEqual({ kind: 'ready', data: [1, 2], degraded: { error } });
  });
});

describe('describeError', () => {
  it('names what failed, then adds the API detail with its code last', () => {
    expect(describeError(new ApiError({ status: 503, code: 'store_down', detail: 'Store unavailable.' }), 'Videos could not be loaded.'))
      .toBe('Videos could not be loaded. Store unavailable. (store_down)');
    expect(describeError(new Error('network'), 'Videos could not be loaded.')).toBe('Videos could not be loaded.');
  });
});
