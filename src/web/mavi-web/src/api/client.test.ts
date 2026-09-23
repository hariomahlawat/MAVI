import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, DEFAULT_API_READ_TIMEOUT_MS, apiRequest } from './client';
import { importVideo } from './videos';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('API client', () => {
  it('parses stable Problem Details extensions from top-level wire properties', async () => {
    const existingId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21411';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      type: 'about:blank',
      status: 409,
      detail: 'Video has already been imported.',
      code: 'video_duplicate',
      videoAssetId: existingId,
    }), {
      status: 409,
      headers: { 'Content-Type': 'application/problem+json' },
    })));

    await expect(apiRequest('/api/test')).rejects.toMatchObject({
      status: 409,
      code: 'video_duplicate',
      detail: 'Video has already been imported.',
      videoAssetId: existingId,
    });
  });

  it('does not require an extensions wrapper and mistrusts malformed duplicate identities', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 409,
      code: 'video_duplicate',
      videoAssetId: 'not-a-guid',
    }), {
      status: 409,
      headers: { 'Content-Type': 'application/problem+json' },
    })));

    try {
      await apiRequest('/api/test');
      throw new Error('Expected API error.');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({ code: 'video_duplicate', videoAssetId: undefined });
    }
  });

  it('falls back safely when an error body is malformed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not-json', {
      status: 500,
      headers: { 'Content-Type': 'text/plain' },
    })));

    await expect(apiRequest('/api/test')).rejects.toMatchObject({
      status: 500,
      code: 'api_error',
      detail: 'The request could not be completed.',
    });
  });

  it('composes caller cancellation into the bounded read signal', async () => {
    const controller = new AbortController();
    let receivedSignal: AbortSignal | undefined;
    const fetchMock = vi.fn((_path: string, init?: RequestInit) => {
      receivedSignal = init?.signal ?? undefined;
      return Promise.reject(new DOMException('caller cancelled', 'AbortError'));
    });
    vi.stubGlobal('fetch', fetchMock);

    const request = apiRequest('/api/test', { signal: controller.signal });
    controller.abort(new DOMException('caller cancelled', 'AbortError'));

    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(receivedSignal).toBeDefined();
    expect(receivedSignal).not.toBe(controller.signal);
    expect(receivedSignal?.aborted).toBe(true);
  });

  it('times out a local read that never resolves', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_path: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
    }));
    vi.stubGlobal('fetch', fetchMock);

    const request = apiRequest('/api/test');
    const rejected = expect(request).rejects.toMatchObject({ name: 'TimeoutError' });
    await vi.advanceTimersByTimeAsync(DEFAULT_API_READ_TIMEOUT_MS);

    await rejected;
  });

  it('does not impose the read timeout on mutating requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await apiRequest('/api/test', { method: 'POST' });

    expect(fetchMock).toHaveBeenCalledWith('/api/test', { method: 'POST' });
  });

  it('lets the browser own the multipart boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21411',
    }), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await importVideo({
      cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
      recordingStartLocal: '2026-09-14T08:30',
      file: new File(['video'], 'source.mp4', { type: 'video/mp4' }),
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers).toBeUndefined();
    const form = init.body as FormData;
    expect(form.get('recordingStartLocal')).toBe('2026-09-14T08:30');
  });
});
