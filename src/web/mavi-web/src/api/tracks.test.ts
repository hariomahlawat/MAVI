import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { searchTracks, serializeTrackSearchFilters, getTrack } from './tracks';

describe('Track API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('serializes supported filters in deterministic order and preserves opaque cursor text', () => {
    const query = serializeTrackSearchFilters({
      minimumConfidence: 0.8,
      cursor: 'opaque+/cursor==',
      objectClass: 'Vehicle',
      cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
      fromUtc: '2026-09-14T02:30:00.000Z',
      minimumDurationMs: 1500,
      limit: 24,
    });

    expect(query).toBe(
      'cameraId=018f3f5a-2f70-7a2b-8a12-2d02f4c21412'
      + '&objectClass=Vehicle'
      + '&fromUtc=2026-09-14T02%3A30%3A00.000Z'
      + '&minimumDurationMs=1500'
      + '&minimumConfidence=0.8'
      + '&cursor=opaque%2B%2Fcursor%3D%3D'
      + '&limit=24',
    );
  });

  it('propagates AbortSignal and preserves stable API errors', async () => {
    const controller = new AbortController();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ status: 400, code: 'track_search_invalid', detail: 'Invalid search.' }),
      { status: 400, headers: { 'content-type': 'application/problem+json' } },
    ));

    await expect(searchTracks({ objectClass: 'Person' }, controller.signal))
      .rejects.toMatchObject({ status: 400, code: 'track_search_invalid' });

    expect(fetch).toHaveBeenCalledWith(
      '/api/tracks?objectClass=Person',
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it('loads Track detail by durable identity', async () => {
    const id = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ id }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ));

    await getTrack(id);

    expect(fetch).toHaveBeenCalledWith('/api/tracks/' + id, {});
  });
});
