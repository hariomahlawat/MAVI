// S6/X3 (§38, "no expensive list highlight re-render"): selecting a result
// re-renders the results whose selection changed, never the rest. Each result
// row names its object class once per render (objectClassLabel), so counting
// those calls per Track counts that result's renders — the observable the
// memoisation exists for, not the wrapper's type.
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { getTrack, objectClassLabel, searchTracks, type TrackSearchItem } from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import VisualSearchPage from './VisualSearchPage';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, searchTracks: vi.fn(), getTrack: vi.fn(), objectClassLabel: vi.fn(actual.objectClassLabel) };
});
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});

const camera = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412', code: 'CAM-01', name: 'North Gate', description: null, locationName: null,
  timeZoneId: 'Asia/Kolkata', isActive: true, createdAtUtc: '2026-09-14T02:30:00Z', updatedAtUtc: '2026-09-14T02:30:00Z',
};
const track = (n: number): TrackSearchItem => ({
  id: `018f3f5a-2f70-7a2b-8a12-2d02f4c2145${n}`,
  processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431', videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
  cameraId: camera.id, cameraCode: camera.code, cameraName: camera.name, objectClass: 'Person',
  startTimestampUtc: '2026-09-14T02:30:00Z', endTimestampUtc: '2026-09-14T02:30:08Z', startOffsetMs: 10_000, endOffsetMs: 18_000,
  durationMs: 8_000, detectionCount: 32, meanConfidence: 0.91, maxConfidence: 0.97, reviewStatus: 'Unreviewed',
  thumbnailArtifactId: null, thumbnailContentUrl: null, videoContentUrl: '/api/videos/018f3f5a-2f70-7a2b-8a12-2d02f4c21421/content',
});
const items = [track(1), track(2), track(3)];
const rendersOf = (id: string) => vi.mocked(objectClassLabel).mock.calls.filter(([t]) => (t as TrackSearchItem).id === id).length;

describe('result selection (S6/X3, §38)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(listVideos).mockResolvedValue([]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(searchTracks).mockResolvedValue({ items, nextCursor: null });
    // The inspector's own load is not what is measured here.
    vi.mocked(getTrack).mockReturnValue(new Promise(() => {}));
  });

  for (const view of ['list', 'grid'] as const) {
    it(`re-renders only the results whose selection changed, in the ${view} view`, async () => {
      window.localStorage.setItem('mavi.search.view', view);
      const user = userEvent.setup();
      renderWithApp(<VisualSearchPage />, { route: '/search' });
      const selects = await screen.findAllByRole('button', { name: /^Select Person/ });
      expect(selects).toHaveLength(3);
      // Settle whatever the page renders on its own first.
      await waitFor(() => expect(searchTracks).toHaveBeenCalled());
      const before = items.map((t) => rendersOf(t.id));

      await user.click(selects[0]);
      await waitFor(() => expect(rendersOf(items[0].id)).toBeGreaterThan(before[0]));
      // The third result's selection did not change: it is not rendered again.
      expect(rendersOf(items[2].id)).toBe(before[2]);

      await user.click(selects[1]);
      await waitFor(() => expect(rendersOf(items[1].id)).toBeGreaterThan(before[1]));
      expect(rendersOf(items[2].id)).toBe(before[2]);
    });
  }
});
