import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation, useNavigate } from 'react-router-dom';
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

function SearchHistoryHarness() {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>Back</button>
      <output aria-label="Current search location">{location.pathname + location.search}</output>
      <VisualSearchPage />
    </>
  );
}

describe('VisualSearchPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(searchTracks).mockResolvedValue({
      items: [track('018f3f5a-2f70-7a2b-8a12-2d02f4c21451')],
      nextCursor: null,
    });
  });

  it('loads the default unfiltered first page', async () => {
    renderWithApp(<VisualSearchPage />, { route: '/search' });

    expect(await screen.findByRole('link', { name: 'Review evidence' })).toBeInTheDocument();
    await waitFor(() => expect(searchTracks).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 24, cursor: undefined }),
      expect.any(AbortSignal),
    ));
  });

  it('keeps draft edits local until Search commits them', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, { route: '/search' });
    await screen.findByRole('link', { name: 'Review evidence' });
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

  it('resets uncommitted draft even when the committed route is already /search', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, { route: '/search' });
    await screen.findByRole('link', { name: 'Review evidence' });

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    await user.type(screen.getByLabelText('Minimum confidence (%)'), '80');
    expect(screen.getByLabelText('Object class')).toHaveValue('Vehicle');
    expect(screen.getByLabelText('Minimum confidence (%)')).toHaveValue('80');

    await user.click(screen.getByRole('button', { name: 'Reset' }));

    expect(screen.getByLabelText('Object class')).toHaveValue('');
    expect(screen.getByLabelText('Minimum confidence (%)')).toHaveValue('');
    expect(searchTracks).toHaveBeenCalledTimes(1);
  });

  it('preserves a bookmarked low confidence exactly when an unrelated filter is submitted', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, {
      route: '/search?minimumConfidence=0.0007',
    });

    await screen.findByRole('link', { name: 'Review evidence' });
    expect(screen.getByLabelText('Minimum confidence (%)')).toHaveValue('0.07');

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
      objectClass: 'Vehicle',
      minimumConfidence: 0.0007,
    }));
  });

  it('preserves committed confidence beyond operator edit precision until the field is edited', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, {
      route: '/search?minimumConfidence=0.00075',
    });

    await screen.findByRole('link', { name: 'Review evidence' });
    expect(screen.getByLabelText('Minimum confidence (%)')).toHaveValue('0.075');

    await user.selectOptions(screen.getByLabelText('Object class'), 'Person');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0].minimumConfidence).toBe(0.00075);
  });

  it('recomputes confidence only after the operator explicitly edits it', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, {
      route: '/search?minimumConfidence=0.00075',
    });

    await screen.findByRole('link', { name: 'Review evidence' });
    const confidence = screen.getByLabelText('Minimum confidence (%)');
    await user.clear(confidence);
    await user.type(confidence, '0.08');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0].minimumConfidence).toBe(0.0008);
  });

  it('preserves committed duration exactly on unrelated submissions until duration is edited', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, {
      route: '/search?minimumDurationMs=1251',
    });

    await screen.findByRole('link', { name: 'Review evidence' });
    expect(screen.getByLabelText('Minimum duration (seconds)')).toHaveValue('1.251');

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0].minimumDurationMs).toBe(1251);
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

  it('converts an edited configured-zone wall time to UTC', async () => {
    renderWithApp(<VisualSearchPage />, { route: '/search' });
    await screen.findByRole('link', { name: 'Review evidence' });

    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-14T08:00:00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
      fromUtc: '2026-09-14T02:30:00.000Z',
    }));
  });

  it('preserves a committed camera scope when camera metadata is unavailable', async () => {
    const user = userEvent.setup();
    vi.mocked(listCameras).mockRejectedValue(new Error('offline'));
    renderWithApp(<VisualSearchPage />, {
      route: '/search?cameraId=' + camera.id,
    });

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(1));
    expect(vi.mocked(searchTracks).mock.calls[0][0]).toEqual(expect.objectContaining({
      cameraId: camera.id,
    }));
    expect(screen.getByRole('option', { name: /Camera ID/ })).toHaveValue(camera.id);

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
      cameraId: camera.id,
      objectClass: 'Vehicle',
    }));
  });

  it('rejects malformed committed URL state without issuing a Track request', async () => {
    renderWithApp(<VisualSearchPage />, {
      route: '/search?objectClass=Person&objectClass=Vehicle',
    });

    expect(await screen.findByText(/must occur exactly once/i)).toBeInTheDocument();
    expect(screen.queryByText(/Searching visual intelligence/i)).not.toBeInTheDocument();
    expect(searchTracks).not.toHaveBeenCalled();
  });

  it('restores committed filters through browser history navigation', async () => {
    const user = userEvent.setup();
    renderWithApp(<SearchHistoryHarness />, { route: '/search?objectClass=Person' });

    await screen.findByRole('link', { name: 'Review evidence' });
    expect(screen.getByLabelText('Object class')).toHaveValue('Person');

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(screen.getByLabelText('Current search location'))
      .toHaveTextContent('/search?objectClass=Vehicle'));

    await user.click(screen.getByRole('button', { name: 'Back' }));

    await waitFor(() => expect(screen.getByLabelText('Object class')).toHaveValue('Person'));
    expect(screen.getByLabelText('Current search location')).toHaveTextContent('/search?objectClass=Person');
  });

  it('hydrates preserved time scope after config recovery without clobbering newer non-time draft edits', async () => {
    const user = userEvent.setup();
    vi.mocked(getSystemConfig).mockRejectedValueOnce(new Error('offline'));

    renderWithApp(<VisualSearchPage />, {
      route: '/search?fromUtc=2026-09-14T02%3A30%3A00Z',
    });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry display config' })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');

    vi.mocked(getSystemConfig).mockResolvedValueOnce({ displayTimeZoneId: 'Asia/Kolkata' });
    await user.click(screen.getByRole('button', { name: 'Retry display config' }));

    await waitFor(() => expect(screen.getByLabelText('From')).toHaveValue('2026-09-14T08:00'));
    expect(screen.getByLabelText('Object class')).toHaveValue('Vehicle');
  });

  it('starts a fresh cursor chain when committed filters change', async () => {
    const user = userEvent.setup();
    vi.mocked(searchTracks)
      .mockResolvedValueOnce({
        items: [track('018f3f5a-2f70-7a2b-8a12-2d02f4c21451')],
        nextCursor: 'first-snapshot-cursor',
      })
      .mockResolvedValueOnce({
        items: [track('018f3f5a-2f70-7a2b-8a12-2d02f4c21452', { objectClass: 'Vehicle' })],
        nextCursor: null,
      });

    renderWithApp(<VisualSearchPage />, { route: '/search' });
    await screen.findByRole('button', { name: 'Load more' });

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
      objectClass: 'Vehicle',
      cursor: undefined,
    }));
  });

  it('refreshes from page one after an expired continuation cursor without mixing snapshots', async () => {
    const user = userEvent.setup();
    const { ApiError } = await import('../../api/client');
    vi.mocked(searchTracks)
      .mockResolvedValueOnce({
        items: [track('018f3f5a-2f70-7a2b-8a12-2d02f4c21451')],
        nextCursor: 'expired-cursor',
      })
      .mockRejectedValueOnce(new ApiError({
        status: 400,
        code: 'track_search_invalid',
        detail: 'Cursor expired.',
      }))
      .mockResolvedValueOnce({
        items: [track('018f3f5a-2f70-7a2b-8a12-2d02f4c21453', { cameraName: 'Fresh Snapshot' })],
        nextCursor: null,
      });

    renderWithApp(<VisualSearchPage />, { route: '/search' });
    await user.click(await screen.findByRole('button', { name: 'Load more' }));

    expect(await screen.findByText(/snapshot can no longer continue/i)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Review evidence' })).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'Refresh results' }));

    expect(await screen.findByText(/Fresh Snapshot/)).toBeInTheDocument();
    expect(vi.mocked(searchTracks).mock.calls[2][0].cursor).toBeUndefined();
  });

  it('keeps inactive cameras available for historical search', async () => {
    vi.mocked(listCameras).mockResolvedValueOnce([{ ...camera, isActive: false }]);

    renderWithApp(<VisualSearchPage />, { route: '/search' });

    await screen.findByRole('link', { name: 'Review evidence' });
    expect(screen.getByRole('option', { name: /CAM-01.*North Gate.*Inactive/ })).toBeInTheDocument();
  });

  it('renders empty and first-page API error states distinctly', async () => {
    vi.mocked(searchTracks).mockResolvedValueOnce({ items: [], nextCursor: null });
    const empty = renderWithApp(<VisualSearchPage />, { route: '/search' });
    expect(await screen.findByText(/No Tracks matched/i)).toBeInTheDocument();
    empty.unmount();

    const { ApiError } = await import('../../api/client');
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(searchTracks).mockRejectedValueOnce(new ApiError({
      status: 400,
      code: 'track_search_invalid',
      detail: 'Invalid search.',
    }));

    renderWithApp(<VisualSearchPage />, { route: '/search' });
    expect(await screen.findByText(/Invalid search.*track_search_invalid/i)).toBeInTheDocument();
    expect(screen.queryByText(/No Tracks matched/i)).not.toBeInTheDocument();
  });

  it('shows and removes URL-provided advanced scopes without hiding their effect', async () => {
    const user = userEvent.setup();
    const videoScope = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';
    const runScope = '018f3f5a-2f70-7a2b-8a12-2d02f4c21431';

    renderWithApp(<VisualSearchPage />, {
      route: '/search?videoAssetId=' + videoScope + '&processingRunId=' + runScope,
    });

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('Active advanced scopes')).toHaveTextContent(videoScope);
    expect(screen.getByLabelText('Active advanced scopes')).toHaveTextContent(runScope);

    await user.click(screen.getByRole('button', { name: 'Remove video scope' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0].videoAssetId).toBeUndefined();
    expect(vi.mocked(searchTracks).mock.calls[1][0].processingRunId).toBe(runScope);
    expect(screen.getByLabelText('Active advanced scopes')).not.toHaveTextContent(videoScope);
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

    expect(await screen.findByText(/East Gate/)).toBeInTheDocument();
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
    await screen.findByRole('link', { name: 'Review evidence' });

    fireEvent.click(screen.getByRole('button', { name: 'Remove time scope' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0].fromUtc).toBeUndefined();
  });
});
