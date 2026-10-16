// Binds UI spec §26 (amended 2026-10-14): the harness-only passive observability
// hook is dormant without the harness's preinstalled handle, exposes counts only,
// and cannot alter rendering, query configuration or scheduling.
import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { registerHarnessObservability, type QueryActivity } from './harnessObservability';
import source from './harnessObservability.ts?raw';
import { createMaviQueryClient } from './queryClient';

type Handle = { queryActivity?: () => QueryActivity };
const SECRET = 'payload-that-must-never-leave';

afterEach(() => {
  delete (window as unknown as { __vqa?: unknown }).__vqa;
  vi.resetModules();
});

describe('harness observability (§26, amended)', () => {
  it('is dormant without a preinstalled handle: nothing created, registered or subscribed', async () => {
    const win: Record<string, unknown> = {};
    const client = createMaviQueryClient();
    registerHarnessObservability(client, win);
    registerHarnessObservability(client, undefined);
    expect(win).toEqual({});
    expect(client.getQueryCache().hasListeners()).toBe(false);
    expect(client.getMutationCache().hasListeners()).toBe(false);
    // The application's own start-up registers nothing in ordinary use.
    expect('__vqa' in window).toBe(false);
    await import('./AppProviders');
    expect('__vqa' in window).toBe(false);
  });

  it('activates only on a handle installed before the application starts', async () => {
    const handle: Handle = {};
    (window as unknown as { __vqa: Handle }).__vqa = handle;
    await import('./AppProviders');
    expect(Object.keys(handle)).toEqual(['queryActivity']);
    expect(handle.queryActivity!()).toEqual({ fetching: 0, mutating: 0 });
  });

  it('exposes two counts only: no query key, payload or client', async () => {
    const client = createMaviQueryClient();
    client.setQueryData(['secret-key', SECRET], { payload: SECRET });
    const handle: Handle = {};
    registerHarnessObservability(client, { __vqa: handle });
    const activity = handle.queryActivity!();
    expect(Object.keys(activity).sort()).toEqual(['fetching', 'mutating']);
    expect(Object.values(activity).every((v) => Number.isInteger(v))).toBe(true);
    expect(Object.isFrozen(activity)).toBe(true);
    expect(JSON.stringify(activity)).not.toContain(SECRET);
    expect(JSON.stringify(activity)).not.toContain('secret-key');
    expect(handle.queryActivity!.length).toBe(0);
  });

  it('cannot alter query configuration, cache subscription or scheduling', async () => {
    const client = createMaviQueryClient();
    const defaults = structuredClone(client.getDefaultOptions());
    const queryFn = vi.fn(async () => ({ payload: SECRET }));
    await client.fetchQuery({ queryKey: ['thing'], queryFn });
    const before = client.getQueryState(['thing']);
    const handle: Handle = {};
    registerHarnessObservability(client, { __vqa: handle });
    for (let i = 0; i < 50; i += 1) handle.queryActivity!();
    expect(client.getDefaultOptions()).toEqual(defaults);
    expect(client.getQueryCache().hasListeners()).toBe(false);
    expect(client.getMutationCache().hasListeners()).toBe(false);
    expect(queryFn).toHaveBeenCalledTimes(1);
    expect(client.getQueryState(['thing'])).toEqual(before);
  });

  it('reads a query waiting out its retry backoff as fetching, and settles to zero', async () => {
    const client = createMaviQueryClient();
    const handle: Handle = {};
    registerHarnessObservability(client, { __vqa: handle });
    let calls = 0;
    const done = client.fetchQuery({
      queryKey: ['retrying'],
      retry: 1,
      retryDelay: 200,
      queryFn: async () => {
        calls += 1;
        if (calls === 1) throw new Error('first answer fails');
        return 'ok';
      },
    });
    await vi.waitFor(() => expect(client.getQueryState(['retrying'])?.fetchFailureCount).toBe(1));
    expect(calls).toBe(1); // in backoff: nothing in flight
    expect(handle.queryActivity!()).toEqual({ fetching: 1, mutating: 0 });
    await done;
    expect(handle.queryActivity!()).toEqual({ fetching: 0, mutating: 0 });
  });

  it('renders the same with and without the handle', async () => {
    const renders: number[] = [];
    for (const installed of [false, true]) {
      const client = createMaviQueryClient();
      if (installed) {
        const handle: Handle = {};
        registerHarnessObservability(client, { __vqa: handle });
        handle.queryActivity!();
      }
      let count = 0;
      function Probe() {
        count += 1;
        const q = useQuery({ queryKey: ['probe'], queryFn: async () => 'answer' });
        return <p>{q.data ?? 'loading'}</p>;
      }
      const { unmount } = render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>);
      await screen.findByText('answer');
      renders.push(count);
      unmount();
    }
    expect(renders[1]).toBe(renders[0]);
  });

  it('has no write path into the query client', () => {
    const code = source.replace(/\/\*[^]*?\*\/|\/\/.*$/gm, '');
    expect(code.match(/queryClient\.(\w+)/g)?.sort()).toEqual(['queryClient.isFetching', 'queryClient.isMutating']);
    expect(code).not.toMatch(/\b(set\w+|invalidate\w*|refetch\w*|cancel\w*|remove\w*|reset\w*|fetch\w*Query|prefetch\w*|subscribe|getQueryCache|getMutationCache|mount)\s*\(/);
  });
});
