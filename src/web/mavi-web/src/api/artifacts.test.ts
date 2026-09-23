import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchArtifactBytes } from './artifacts';
import { DEFAULT_API_READ_TIMEOUT_MS } from './client';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('artifact bytes', () => {
  it('times out a trajectory read that never resolves, as other local reads do', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_path: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
    })));

    const read = fetchArtifactBytes('/api/artifacts/a/content');
    const rejected = expect(read).rejects.toMatchObject({ name: 'TimeoutError' });
    await vi.advanceTimersByTimeAsync(DEFAULT_API_READ_TIMEOUT_MS);

    await rejected;
  });

  it('forwards caller cancellation to the read', async () => {
    const controller = new AbortController();
    let received: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn((_path: string, init?: RequestInit) => {
      received = init?.signal ?? undefined;
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
      });
    }));

    const read = fetchArtifactBytes('/api/artifacts/a/content', controller.signal);
    controller.abort(new DOMException('closed review', 'AbortError'));

    await expect(read).rejects.toMatchObject({ name: 'AbortError', message: 'closed review' });
    expect(received?.aborted).toBe(true);
  });

  it('returns the bytes and leaves no timer behind', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3]), { status: 200 })));

    await expect(fetchArtifactBytes('/api/artifacts/a/content')).resolves.toEqual(new Uint8Array([1, 2, 3]));
    expect(vi.getTimerCount()).toBe(0);
  });
});
