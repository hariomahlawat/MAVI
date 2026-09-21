import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { searchTracks, serializeTrackSearchFilters, getTrack } from './tracks';

describe('Track API client', () => {
  it('serializes the analytic keys after the ordinary filters and before the cursor', () => {
    const query = serializeTrackSearchFilters({
      cursor: 'c',
      loitering: true,
      zoneId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21461',
      zoneRelation: 'entered',
      minDwellMs: 1500,
      cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
      motionDirection: 'NW',
      crossingDirection: 'bToA',
      lineId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21471',
      sceneRevisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21481',
      analyticsAlgorithmVersion: 'scene-analytics-v1',
      minStationaryMs: 0,
    });

    expect(query).toBe(
      'cameraId=018f3f5a-2f70-7a2b-8a12-2d02f4c21412'
      + '&sceneRevisionId=018f3f5a-2f70-7a2b-8a12-2d02f4c21481'
      + '&analyticsAlgorithmVersion=scene-analytics-v1'
      + '&zoneId=018f3f5a-2f70-7a2b-8a12-2d02f4c21461'
      + '&zoneRelation=entered'
      + '&minDwellMs=1500'
      + '&lineId=018f3f5a-2f70-7a2b-8a12-2d02f4c21471'
      + '&crossingDirection=bToA'
      + '&motionDirection=NW'
      + '&minStationaryMs=0'
      + '&loitering=true'
      + '&cursor=c',
    );
  });

  it('asks for a Track detail against an explicit analytic identity only when given one', async () => {
    const respond = () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
    vi.mocked(fetch).mockResolvedValueOnce(respond()).mockResolvedValueOnce(respond());

    await getTrack('018f3f5a-2f70-7a2b-8a12-2d02f4c21451');
    expect(fetch).toHaveBeenLastCalledWith('/api/tracks/018f3f5a-2f70-7a2b-8a12-2d02f4c21451', expect.anything());

    await getTrack('018f3f5a-2f70-7a2b-8a12-2d02f4c21451', undefined, {
      sceneRevisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21481',
      analyticsAlgorithmVersion: 'scene-analytics-v1',
    });
    expect(fetch).toHaveBeenLastCalledWith(
      '/api/tracks/018f3f5a-2f70-7a2b-8a12-2d02f4c21451?sceneRevisionId=018f3f5a-2f70-7a2b-8a12-2d02f4c21481&analyticsAlgorithmVersion=scene-analytics-v1',
      expect.anything(),
    );
  });

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

  it('serializes an empty search without a query string and omits undefined values', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ items: [], nextCursor: null }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ));

    expect(serializeTrackSearchFilters({
      cameraId: undefined,
      objectClass: undefined,
    })).toBe('');

    await searchTracks({});
    expect(fetch).toHaveBeenCalledWith('/api/tracks', expect.objectContaining({ signal: undefined }));
  });

  it('serializes every supported Track filter using the backend contract names', () => {
    const query = serializeTrackSearchFilters({
      cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
      videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
      processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
      objectClass: 'Person',
      fromUtc: '2026-09-14T02:30:00.000Z',
      toUtc: '2026-09-14T03:30:00.000Z',
      minimumDurationMs: 1250,
      minimumConfidence: 0.9125,
      cursor: 'cursor-token',
      limit: 24,
    });

    expect(Object.fromEntries(new URLSearchParams(query))).toEqual({
      cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
      videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
      processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
      objectClass: 'Person',
      fromUtc: '2026-09-14T02:30:00.000Z',
      toUtc: '2026-09-14T03:30:00.000Z',
      minimumDurationMs: '1250',
      minimumConfidence: '0.9125',
      cursor: 'cursor-token',
      limit: '24',
    });
    expect(serializeTrackSearchFilters({ objectClass: 'Vehicle' })).toBe('objectClass=Vehicle');
  });

  it('never serializes confidence in exponent notation unsupported by the backend', () => {
    expect(serializeTrackSearchFilters({ minimumConfidence: 1e-7 }))
      .toBe('minimumConfidence=0.0000001');
    expect(serializeTrackSearchFilters({ minimumConfidence: 1.25e-7 }))
      .toBe('minimumConfidence=0.000000125');
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

  it('preserves track_not_found from Track detail', async () => {
    const id = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ status: 404, code: 'track_not_found', detail: 'Track was not found.' }),
      { status: 404, headers: { 'content-type': 'application/problem+json' } },
    ));

    await expect(getTrack(id)).rejects.toMatchObject({
      status: 404,
      code: 'track_not_found',
      detail: 'Track was not found.',
    });
  });

  it('loads Track detail by durable identity', async () => {
    const id = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ id }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ));

    await getTrack(id);

    expect(fetch).toHaveBeenCalledWith('/api/tracks/' + id, expect.objectContaining({ signal: undefined }));
  });
});
