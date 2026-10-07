import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { getCameraScene } from '../../api/scene';
import { useSceneGeometry } from './useSceneGeometry';

vi.mock('../../api/scene', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/scene')>();
  return { ...actual, getCameraScene: vi.fn(), getCameraSceneRevision: vi.fn() };
});

const CAMERA = '11111111-1111-7111-8111-111111111111';

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
});
