import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { getCameraScene, getCameraSceneRevision, type CameraScene, type SceneRevision } from '../../api/scene';
import { queryKeys } from '../../app/queryClient';
import { useSceneGeometry } from './useSceneGeometry';

vi.mock('../../api/scene', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/scene')>();
  return { ...actual, getCameraScene: vi.fn(), getCameraSceneRevision: vi.fn() };
});

const CAMERA = '11111111-1111-7111-8111-111111111111';
const ACTIVE_ID = '018f3f5a-2f70-7a2b-8a12-2d02f4c21404';
const HISTORICAL_ID = '018f3f5a-2f70-7a2b-8a12-2d02f4c21403';
const ZONE_ID = '018f3f5a-2f70-7a2b-8a12-2d02f4c214a1';
const LINE_ID = '018f3f5a-2f70-7a2b-8a12-2d02f4c214b1';
const OLD_ZONE_ID = '018f3f5a-2f70-7a2b-8a12-2d02f4c214a0';

/** A real configured revision: identifiers the backend would accept for a query. */
function revision(revisionId: string, revisionNumber: number, zone: { id: string; name: string }, withLine: boolean): SceneRevision {
  return {
    revisionId,
    revisionNumber,
    cameraId: CAMERA,
    createdAtUtc: '2026-09-01T04:00:00Z',
    createdBy: 'operator',
    note: null,
    referenceFrameVideoAssetId: null,
    referenceFrameOffsetMs: null,
    zones: [{ zoneId: zone.id, name: zone.name, kind: 'Restricted', enabled: true, vertices: [{ x: 0.1, y: 0.1 }, { x: 0.4, y: 0.1 }, { x: 0.4, y: 0.4 }], loiteringThresholdSeconds: 120 }],
    tripLines: withLine
      ? [{ lineId: LINE_ID, name: 'Gate A', enabled: true, a: { x: 0.2, y: 0.8 }, b: { x: 0.8, y: 0.2 }, directed: true, aToBLabel: 'Inbound', bToALabel: 'Outbound' }]
      : [],
    analyticsEnabled: true,
  };
}

const ACTIVE = revision(ACTIVE_ID, 4, { id: ZONE_ID, name: 'Loading bay' }, true);
const HISTORICAL = revision(HISTORICAL_ID, 3, { id: OLD_ZONE_ID, name: 'Old forecourt' }, false);
const CONFIGURED: CameraScene = {
  cameraId: CAMERA,
  configured: true,
  activeRevision: ACTIVE,
  history: [HISTORICAL, ACTIVE].map((r) => ({
    revisionId: r.revisionId, revisionNumber: r.revisionNumber, createdAtUtc: r.createdAtUtc, createdBy: r.createdBy,
    note: r.note, analyticsEnabled: r.analyticsEnabled, zoneCount: r.zones.length, tripLineCount: r.tripLines.length,
  })),
};

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

/**
 * §14.1, degraded: the active scene is not immutable, so a scene whose refresh
 * failed is not offered as current geometry — the active revision may have
 * moved on, and its zones and lines could be identifiers the server no longer
 * accepts.
 */
describe('useSceneGeometry', () => {
  it('treats a scene whose refresh failed as unavailable, not as current', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    vi.mocked(getCameraScene).mockResolvedValue({ configured: false, activeRevision: null, history: [] } as never);

    const { result } = renderHook(() => useSceneGeometry(CAMERA, undefined), { wrapper });
    await waitFor(() => expect(result.current.status).toBe('unconfigured'));

    vi.mocked(getCameraScene).mockRejectedValue(new Error('down'));
    await act(async () => {
      await client.refetchQueries();
    });

    await waitFor(() => expect(result.current.status).toBe('unavailable'));
  });

  it('fails closed on configured active geometry once its refresh fails: no stale zone or line is offered as current', async () => {
    const { client, wrapper } = setup();
    vi.mocked(getCameraScene).mockResolvedValue(CONFIGURED);

    const { result } = renderHook(() => useSceneGeometry(CAMERA, undefined, 'current'), { wrapper });

    // 1-2. Current mode is ready, naming the active revision's real zone and line.
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const ready = result.current as Extract<typeof result.current, { status: 'ready' }>;
    expect(ready.names.revisionNumber).toBe(4);
    expect(ready.names.zones.get(ZONE_ID)?.name).toBe('Loading bay');
    expect(ready.names.lines.get(LINE_ID)?.name).toBe('Gate A');
    expect(ready.analyticsEnabled).toBe(true);

    // 3. The active-scene refresh fails; the query still holds the old revision.
    vi.mocked(getCameraScene).mockRejectedValue(new Error('down'));
    await act(async () => {
      await client.refetchQueries({ queryKey: queryKeys.cameraScene(CAMERA) });
    });
    expect(client.getQueryState(queryKeys.cameraScene(CAMERA))?.status).toBe('error');
    expect((client.getQueryData(queryKeys.cameraScene(CAMERA)) as CameraScene).activeRevision?.zones[0].zoneId).toBe(ZONE_ID);

    // 4-6. Current mode is unavailable and exposes no ready geometry, so the rail
    // has no zone or line to offer as a verified current choice.
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(Object.keys(result.current).sort()).toEqual(['retry', 'status']);
    expect('names' in result.current).toBe(false);

    // Its own Retry re-reads the scene; once the read succeeds it is current again.
    vi.mocked(getCameraScene).mockResolvedValue(CONFIGURED);
    await act(async () => {
      (result.current as Extract<typeof result.current, { status: 'unavailable' }>).retry?.();
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));
  });

  it('offers no Retry for a committed revision the scene does not contain: re-reading cannot help', async () => {
    const { wrapper } = setup();
    vi.mocked(getCameraScene).mockResolvedValue(CONFIGURED);
    const { result } = renderHook(
      () => useSceneGeometry(CAMERA, '018f3f5a-2f70-7a2b-8a12-2d02f4c214ee', 'pinned'),
      { wrapper },
    );
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(result.current).toEqual({ status: 'unavailable' });
  });

  it('keeps an exact historical revision ready when its own refresh fails: an immutable revision cannot have moved on', async () => {
    const { client, wrapper } = setup();
    vi.mocked(getCameraScene).mockResolvedValue(CONFIGURED);
    vi.mocked(getCameraSceneRevision).mockResolvedValue(HISTORICAL);

    const { result } = renderHook(() => useSceneGeometry(CAMERA, HISTORICAL_ID, 'pinned'), { wrapper });

    // Scene and history resolve the id to revision 3, which loads exactly.
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(getCameraSceneRevision).toHaveBeenCalledWith(CAMERA, 3, expect.anything());
    const pinned = result.current as Extract<typeof result.current, { status: 'ready' }>;
    expect(pinned.names.revisionNumber).toBe(3);
    expect(pinned.names.zones.get(OLD_ZONE_ID)?.name).toBe('Old forecourt');
    // Never the active revision's geometry.
    expect(pinned.names.zones.has(ZONE_ID)).toBe(false);

    // A later refresh of that exact revision fails, retaining its data.
    vi.mocked(getCameraSceneRevision).mockRejectedValue(new Error('down'));
    await act(async () => {
      await client.refetchQueries({ queryKey: queryKeys.cameraSceneRevision(CAMERA, 3) });
    });
    expect(client.getQueryState(queryKeys.cameraSceneRevision(CAMERA, 3))?.status).toBe('error');

    // Intentionally still ready: degraded means "could not re-read", and the
    // geometry of an immutable revision is the same geometry it was.
    expect(result.current.status).toBe('ready');
    const retained = result.current as Extract<typeof result.current, { status: 'ready' }>;
    expect(retained.names.revisionNumber).toBe(3);
    expect(retained.names.zones.get(OLD_ZONE_ID)?.name).toBe('Old forecourt');
  });
});
