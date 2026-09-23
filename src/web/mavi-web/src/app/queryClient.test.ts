import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryObserver } from '@tanstack/react-query';
import { createMaviQueryClient } from './queryClient';

afterEach(() => {
  vi.useRealTimers();
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
});
