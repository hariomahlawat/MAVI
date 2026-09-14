import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { searchTracks, type TrackSearchItem } from '../../api/tracks';
import { renderWithApp } from '../../test/renderWithApp';
import VisualSearchPage from './VisualSearchPage';

vi.mock('../../api/cameras', () => ({
  listCameras: vi.fn(),
}));

vi.mock('../../api/system', () => ({
  getSystemConfig: vi.fn(),
}));

vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return {
    ...actual,
    searchTracks: vi.fn(),
  };
});

const camera = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
  code: 'CAM-01',
  name: 'North Gate',
  description: null,
  locationName: null,
  timeZoneId: 'Asia/Kolkata',
  isActive: true,
  createdAtUtc: '2026-09-14T02:30:00Z',
  updatedAtUtc: '2026-09-14T02:30:00Z',
};

function track(id: string, overrides: Partial<TrackSearchItem> = {}): TrackSearchItem {
  return {
    id,
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
    videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
    cameraId: camera.id,
    cameraCode: camera.code,
    cameraName: camera.name,
    objectClass: 'Person',
    startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:08Z',
    startOffsetMs: 10_000,
    endOffsetMs: 18_000,
    durationMs: 8_000,
    detectionCount: 32,
    meanConfidence: 0.91,
    maxConfidence: 0.97,
    reviewStatus: 'Unreviewed',
    thumbnailArtifactId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21441',
    thumbnailContentUrl: '/api/artifacts/018f3f5a-2f70-7a2b-8a12-2d02f4c21441/content',
    videoContentUrl: '/api/videos/018f3f5a-2f70-7a2b-8a12-2d02f4c21421/content',
    ...overrides,
  };
}

describe('VisualSearchPage', () => {
  beforeEach(() => {
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(searchTracks).mockResolvedValue({
      items: [track('018f3f5a-2f70-7a2b-8a12-2d02f4c21451')],
      nextCursor: null,
    });
  });

  it('loads the default unfiltered first page', async () => {
    renderWithApp(<VisualSearchPage />, { route: '/search' });

    expect(await screen.findByText('North Gate')).toBeInTheDocument();
    await waitFor(() => expect(searchTracks).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 24, cursor: undefined }),
      expect.any(AbortSignal),
    ));
  });

  it('keeps draft edits local until Search commits them', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, { route: '/search' });
    await screen.findByText('North Gate');
    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(1));

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    expect(searchTracks).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
      objectClass: 'Vehicle',
      limit: 24,
    }));
  });

  it('preserves committed UTC time bounds during system-config outage', async () => {
    const user = userEvent.setup();
    vi.mocked(getSystemConfig).mockRejectedValue(new Error('offline'));
    renderWithApp(<VisualSearchPage />, {
      route: '/search?fromUtc=2026-09-14T02%3A30%3A00Z&toUtc=2026-09-14T03%3A30%3A00Z',
    });

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('Active time scope')).toHaveTextContent('2026-09-14T02:30:00.000Z');

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
      objectClass: 'Vehicle',
      fromUtc: '2026-09-14T02:30:00.000Z',
      toUtc: '2026-09-14T03:30:00.000Z',
    }));
  });

  it('passes the opaque continuation cursor only to Load more', async () => {
    const user = userEvent.setup();
    vi.mocked(searchTracks)
      .mockResolvedValueOnce({
        items: [track('018f3f5a-2f70-7a2b-8a12-2d02f4c21451')],
        nextCursor: 'opaque-cursor',
      })
      .mockResolvedValueOnce({
        items: [track('018f3f5a-2f70-7a2b-8a12-2d02f4c21452', { cameraName: 'East Gate' })],
        nextCursor: null,
      });

    renderWithApp(<VisualSearchPage />, { route: '/search' });
    await screen.findByRole('button', { name: 'Load more' });
    await user.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByText('East Gate')).toBeInTheDocument();
    expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
      cursor: 'opaque-cursor',
      limit: 24,
    }));
  });

  it('removes committed time scope only through its explicit control during an outage', async () => {
    vi.mocked(getSystemConfig).mockRejectedValue(new Error('offline'));
    renderWithApp(<VisualSearchPage />, {
      route: '/search?fromUtc=2026-09-14T02%3A30%3A00Z',
    });
    await screen.findByText('North Gate');

    fireEvent.click(screen.getByRole('button', { name: 'Remove time scope' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0].fromUtc).toBeUndefined();
  });
});
