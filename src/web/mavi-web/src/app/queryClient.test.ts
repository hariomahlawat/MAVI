import { afterEach, describe, expect, it, vi } from 'vitest';
import { MutationObserver, QueryObserver, onlineManager } from '@tanstack/react-query';
import { createMaviQueryClient } from './queryClient';

afterEach(() => {
  vi.useRealTimers();
  onlineManager.setOnline(true);
});

/**
 * A local read that times out (`api/client.ts`) is retried once by the query
 * defaults and then shown as a failure with its own Retry. The single retry is
 * what recovers a read that stalled during an offline cold start; this pins it
 * so a change to the defaults cannot silently remove that recovery or turn one
 * timeout into an unbounded wait.
 */
describe('MAVI query defaults', () => {
  it('retries a timed-out read exactly once, then reports the failure', async () => {
    vi.useFakeTimers();
    const client = createMaviQueryClient();
    const timeout = new DOMException('Local API read did not respond within 10000 ms.', 'TimeoutError');
    const queryFn = vi.fn().mockRejectedValue(timeout);
    const observer = new QueryObserver(client, { queryKey: ['timeout-probe'], queryFn });
    const unsubscribe = observer.subscribe(() => {});

    await vi.advanceTimersByTimeAsync(60_000);

    expect(queryFn).toHaveBeenCalledTimes(2);
    expect(observer.getCurrentResult().status).toBe('error');
    expect(observer.getCurrentResult().error).toBe(timeout);
    unsubscribe();
    client.clear();
  });

  it('never retries a mutation', () => {
    expect(createMaviQueryClient().getDefaultOptions().mutations?.retry).toBe(false);
  });

  it('still reads the local API while the browser reports no network', async () => {
    // Air-gapped: every adapter disabled, navigator.onLine false, API on loopback.
    onlineManager.setOnline(false);
    const client = createMaviQueryClient();
    const queryFn = vi.fn().mockResolvedValue({ ok: true });
    const observer = new QueryObserver(client, { queryKey: ['offline-probe'], queryFn });
    const unsubscribe = observer.subscribe(() => {});

    await vi.waitFor(() => expect(observer.getCurrentResult().status).toBe('success'));
    expect(queryFn).toHaveBeenCalledTimes(1);
    expect(observer.getCurrentResult().fetchStatus).toBe('idle');
    unsubscribe();
    client.clear();
  });

  it('still sends a mutation while the browser reports no network', async () => {
    onlineManager.setOnline(false);
    const client = createMaviQueryClient();
    const mutationFn = vi.fn().mockResolvedValue({ saved: true });

    await expect(new MutationObserver(client, { mutationFn }).mutate(undefined)).resolves.toEqual({ saved: true });
    expect(mutationFn).toHaveBeenCalledTimes(1);
    client.clear();
  });
});
