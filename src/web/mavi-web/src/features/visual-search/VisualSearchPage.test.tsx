import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { getTrack, searchTracks, type TrackDetail, type TrackSearchItem } from '../../api/tracks';
import { listVideos } from '../../api/videos';
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
    getTrack: vi.fn(),
  };
});

vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return {
    ...actual,
    listVideos: vi.fn(),
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

function detail(item: TrackSearchItem, localTrackNumber: number): TrackDetail {
  return {
    id: item.id,
    processingRunId: item.processingRunId,
    videoAssetId: item.videoAssetId,
    camera: { id: item.cameraId, code: item.cameraCode, name: item.cameraName },
    objectClass: item.objectClass,
    localTrackNumber,
    startOffsetMs: item.startOffsetMs,
    endOffsetMs: item.endOffsetMs,
    startTimestampUtc: item.startTimestampUtc,
    endTimestampUtc: item.endTimestampUtc,
    durationMs: item.durationMs,
    detectionCount: item.detectionCount,
    meanConfidence: item.meanConfidence,
    maxConfidence: item.maxConfidence,
    reviewStatus: item.reviewStatus,
    processing: {
      pipelineVersion: 'phase1',
      detectorName: 'RTMDet',
      detectorVersion: '1',
      trackerName: 'ByteTrack',
      trackerVersion: '1',
      completedAtUtc: '2026-09-14T02:40:00Z',
    },
    video: {
      recordingStartUtc: '2026-09-14T02:26:42Z',
      recordingEndUtc: '2026-09-14T02:36:42Z',
      durationMs: 600_000,
      width: 1920,
      height: 1080,
      frameRateNumerator: 25,
      frameRateDenominator: 1,
      videoContentUrl: item.videoContentUrl,
    },
    representative: null,
    trajectoryArtifactId: null,
    trajectoryContentUrl: null,
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
    // List/Grid is a stored preference, so a test that switches views would
    // otherwise decide the view of every test that runs after it.
    window.localStorage.clear();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(listVideos).mockResolvedValue([]);
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

  it('is an Investigation rather than a page with its own three-column grid', async () => {
    const { container } = renderWithApp(<VisualSearchPage />, { route: '/search' });
    await screen.findByRole('link', { name: 'Review evidence' });

    // §4.4 through the shared archetype: the rail, the results column and the
    // inspector slot are the layout's regions, not this feature's CSS.
    const workspace = container.querySelector('.workspace--investigation');
    expect(workspace).toBeInTheDocument();
    expect(within(workspace as HTMLElement).getByRole('form', { name: 'Search filters' }))
      .toBeInTheDocument();
    expect(container.querySelector('.workspace__results')).toBeInTheDocument();
    // §4 removes the page title block; the surface names itself in the band.
    expect(container.querySelector('.page-header')).not.toBeInTheDocument();
    // The private grid it used to carry is gone, not renamed.
    expect(container.querySelector('.search-workspace')).not.toBeInTheDocument();
  });

  it('puts page-scope conditions above the results rather than inside them', async () => {
    vi.mocked(listCameras).mockRejectedValue(new ApiError({ status: 503, code: 'cameras_unavailable', detail: 'Cameras unavailable.' }));
    const { container } = renderWithApp(<VisualSearchPage />, { route: '/search' });

    const notice = await screen.findByText(/Camera metadata is unavailable/);
    // A surface-wide outage must not scroll away with the rows it is not about.
    expect(notice.closest('.workspace__notices')).not.toBeNull();
    expect(notice.closest('.workspace__results')).toBeNull();
    expect(container.querySelector('.workspace__notices')).toBeInTheDocument();
  });

  it('shows the inspector through the shared shell when a Track is selected', async () => {
    const user = userEvent.setup();
    const { container } = renderWithApp(<VisualSearchPage />, { route: '/search' });
    const rows = within(await screen.findByRole('list', { name: 'Track results' })).getAllByRole('listitem');
    await user.click(within(rows[0]).getByRole('button', { name: /^Select / }));

    const inspector = await screen.findByRole('complementary', { name: 'Track inspector' });
    expect(inspector).toHaveClass('inspector');
    expect(container.querySelector('.workspace--investigation.has-inspector')).toBeInTheDocument();
    // §20: a drawer, not a dialog. Nothing here may claim modality.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(inspector.getAttribute('aria-modal')).toBeNull();
    expect(container.querySelector('[inert]')).toBeNull();
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
    // Without the configured zone the chip states the instant explicitly in
    // UTC rather than guessing at the browser's (ADR-004, §24).
    expect(within(screen.getByRole('group', { name: 'Committed filters' })).getByTitle(/^From:/))
      .toHaveTextContent('2026-09-14T02:30:00.000Z UTC');

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
    vi.mocked(listVideos).mockResolvedValue([]);
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
    // The rail has no control for either scope, so the chip is the only place
    // an operator can see that one is in force — shortened, because the video
    // inventory is empty here and there is no name to resolve it to.
    const chips = () => screen.getByRole('group', { name: 'Committed filters' });
    expect(within(chips()).getByTitle(/^Video:/)).toHaveTextContent(videoScope.slice(0, 8));
    expect(within(chips()).getByTitle(/^Processing run:/)).toHaveTextContent(runScope.slice(0, 8));

    await user.click(screen.getByRole('button', { name: 'Remove video filter' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0].videoAssetId).toBeUndefined();
    expect(vi.mocked(searchTracks).mock.calls[1][0].processingRunId).toBe(runScope);
    expect(within(chips()).queryByTitle(/^Video:/)).not.toBeInTheDocument();
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

    fireEvent.click(screen.getByRole('button', { name: 'Remove from filter' }));

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchTracks).mock.calls[1][0].fromUtc).toBeUndefined();
  });

  describe('field-level validation (§10)', () => {
    it('reports every refused field on the field itself, not once at page level', async () => {
      const user = userEvent.setup();
      renderWithApp(<SearchHistoryHarness />, { route: '/search' });
      await screen.findByRole('link', { name: 'Review evidence' });

      await user.type(screen.getByLabelText('Minimum duration (seconds)'), '1.2345');
      await user.type(screen.getByLabelText('Minimum confidence (%)'), '140');
      await user.click(screen.getByRole('button', { name: 'Search' }));

      // Both, not just the first: an operator who mistyped two fields should
      // not have to discover the second after fixing the first.
      const duration = screen.getByLabelText('Minimum duration (seconds)');
      const confidence = screen.getByLabelText('Minimum confidence (%)');
      expect(duration).toHaveAttribute('aria-invalid', 'true');
      expect(confidence).toHaveAttribute('aria-invalid', 'true');
      expect(document.getElementById(duration.getAttribute('aria-describedby')!.split(' ')[0]))
        .toHaveTextContent(/three decimal places/i);
      expect(document.getElementById(confidence.getAttribute('aria-describedby')!.split(' ')[0]))
        .toHaveTextContent(/between 0 and 100/i);

      // Nothing was committed and nothing was requested.
      expect(searchTracks).toHaveBeenCalledTimes(1);
      expect(screen.getByLabelText('Current search location')).toHaveTextContent('/search');
    });

    it('reports an inverted range on the To field and clears it when corrected', async () => {
      renderWithApp(<VisualSearchPage />, { route: '/search' });
      await screen.findByRole('link', { name: 'Review evidence' });

      fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-14T10:00:00' } });
      fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-09-14T09:00:00' } });
      fireEvent.click(screen.getByRole('button', { name: 'Search' }));

      expect(await screen.findByText(/To time must be later/i)).toBeInTheDocument();
      expect(screen.getByLabelText('To')).toHaveAttribute('aria-invalid', 'true');
      expect(screen.getByLabelText('From')).not.toHaveAttribute('aria-invalid');

      // Touching the field withdraws the claim; it is re-judged on the next ask.
      fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-09-14T11:00:00' } });
      expect(screen.queryByText(/To time must be later/i)).not.toBeInTheDocument();
      expect(screen.getByLabelText('To')).not.toHaveAttribute('aria-invalid');
    });

    it('keeps malformed committed URL state at page level rather than on a field', async () => {
      renderWithApp(<VisualSearchPage />, { route: '/search?objectClass=Person&objectClass=Vehicle' });

      const notice = await screen.findByText(/must occur exactly once/i);
      // §10: the URL is not a field, so its refusal is not a field error.
      expect(notice.closest('.workspace__notices')).not.toBeNull();
      expect(document.querySelector('[aria-invalid="true"]')).toBeNull();
      expect(searchTracks).not.toHaveBeenCalled();
    });
  });

  describe('committed filter chips (§11)', () => {
    it('resolves identifiers to names and falls back to a short identifier', async () => {
      const unknown = '018f3f5a-2f70-7a2b-8a12-2d02f4c21499';
      renderWithApp(<VisualSearchPage />, {
        route: `/search?cameraId=${camera.id}&videoAssetId=${unknown}&objectClass=Person&minimumConfidence=0.075`,
      });

      const chips = await screen.findByRole('group', { name: 'Committed filters' });
      // The chip is drawn before the inventory that names the camera arrives,
      // and states the identifier until it does rather than waiting.
      expect(within(chips).getByTitle(/^Camera:/)).toHaveTextContent(camera.id.slice(0, 8));
      await waitFor(() => expect(within(chips).getByTitle(/^Camera:/))
        .toHaveTextContent('CAM-01 · North Gate'));
      // No video inventory resolves this one, so it shortens rather than vanishing.
      expect(within(chips).getByTitle(/^Video:/)).toHaveTextContent(unknown.slice(0, 8));
      expect(within(chips).getByTitle(/^Class:/)).toHaveTextContent('Person');
      // Stated to the precision it was committed with, not rounded for scanning.
      expect(within(chips).getByTitle(/^Minimum confidence:/)).toHaveTextContent('7.5%');
      // Selection is not a criterion.
      expect(within(chips).queryByTitle(/^Track:/)).not.toBeInTheDocument();
    });

    it('removes one criterion without disturbing a field the operator is editing', async () => {
      const user = userEvent.setup();
      renderWithApp(<SearchHistoryHarness />, {
        route: `/search?cameraId=${camera.id}&objectClass=Person`,
      });
      await screen.findByRole('link', { name: 'Review evidence' });

      // A local edit that has not been committed yet.
      await user.type(screen.getByLabelText('Minimum confidence (%)'), '80');
      expect(screen.getByLabelText('Minimum confidence (%)')).toHaveValue('80');

      await user.click(screen.getByRole('button', { name: 'Remove class filter' }));

      await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
      // The criterion went; the rest of the committed search stayed; the
      // continuation cursor did not travel to the new snapshot.
      expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({
        cameraId: camera.id, cursor: undefined, limit: 24,
      }));
      expect(vi.mocked(searchTracks).mock.calls[1][0].objectClass).toBeUndefined();
      expect(screen.getByLabelText('Current search location'))
        .toHaveTextContent('/search?cameraId=' + camera.id);
      // The untouched Camera field rebased; the edited confidence survived.
      expect(screen.getByLabelText('Camera')).toHaveValue(camera.id);
      expect(screen.getByLabelText('Object class')).toHaveValue('');
      expect(screen.getByLabelText('Minimum confidence (%)')).toHaveValue('80');
    });

    it('drops the selection when a criterion is removed', async () => {
      const user = userEvent.setup();
      const first = track('018f3f5a-2f70-7a2b-8a12-2d02f4c21451');
      vi.mocked(searchTracks).mockResolvedValue({ items: [first], nextCursor: null });
      renderWithApp(<SearchHistoryHarness />, { route: `/search?objectClass=Person&track=${first.id}` });

      await screen.findByRole('complementary', { name: 'Track inspector' });
      await user.click(screen.getByRole('button', { name: 'Remove class filter' }));

      // The Track belonged to a snapshot that no longer exists.
      await waitFor(() => expect(screen.getByLabelText('Current search location'))
        .not.toHaveTextContent('track='));
      expect(screen.queryByRole('complementary', { name: 'Track inspector' })).not.toBeInTheDocument();
    });
  });

  describe('in-place inspector', () => {
    const first = track('018f3f5a-2f70-7a2b-8a12-2d02f4c21451');
    const second = track('018f3f5a-2f70-7a2b-8a12-2d02f4c21452', { objectClass: 'Vehicle', cameraName: 'East Gate' });

    beforeEach(() => {
      vi.mocked(searchTracks).mockResolvedValue({ items: [first, second], nextCursor: null });
      vi.mocked(getTrack).mockImplementation(async (id) => detail(id === first.id ? first : second, id === first.id ? 7 : 8));
    });

    it('returns focus to the result it was opened from when it closes', async () => {
      const user = userEvent.setup();
      renderWithApp(<VisualSearchPage />, { route: '/search' });
      const rows = within(await screen.findByRole('list', { name: 'Track results' })).getAllByRole('listitem');
      const control = within(rows[0]).getByRole('button', { name: /^Select / });

      await user.click(control);
      await screen.findByRole('heading', { name: 'Person · Track 7' });
      await user.click(screen.getByRole('button', { name: 'Close inspector' }));

      // Closing removes the subtree focus was in; without this, focus falls to
      // the document and the next Tab restarts at the top of the page.
      await waitFor(() => expect(control).toHaveFocus());
    });

    it('falls back to the results region when the result it was opened from is gone', async () => {
      const user = userEvent.setup();
      renderWithApp(<VisualSearchPage />, { route: '/search' });
      await screen.findByRole('list', { name: 'Track results' });

      // A deep-linked Track that is not in this snapshot has no control to
      // return to; focus must still land somewhere the operator can work from.
      await user.click(within(within(screen.getByRole('list', { name: 'Track results' }))
        .getAllByRole('listitem')[0]).getByRole('button', { name: /^Select / }));
      await screen.findByRole('heading', { name: 'Person · Track 7' });
      vi.mocked(searchTracks).mockResolvedValue({ items: [], nextCursor: null });
      await user.click(screen.getByRole('button', { name: 'Close inspector' }));

      await waitFor(() => expect(screen.queryByRole('heading', { name: 'Person · Track 7' })).not.toBeInTheDocument());
      expect(document.activeElement).not.toBe(document.body);
    });

    it('drives the Grid from the keyboard exactly as it drives the List', async () => {
      const user = userEvent.setup();
      renderWithApp(<SearchHistoryHarness />, { route: '/search' });
      await screen.findByRole('list', { name: 'Track results' });
      await user.click(screen.getByRole('button', { name: 'Grid view' }));

      // No list any more — and the same shortcuts still work.
      expect(screen.queryByRole('list', { name: 'Track results' })).not.toBeInTheDocument();
      const control = screen.getByRole('button', { name: `Select Person · ${camera.code} · ${camera.name}` });
      await user.click(control);
      expect(await screen.findByRole('heading', { name: 'Person · Track 7' })).toBeInTheDocument();

      await user.keyboard('{j}');
      expect(await screen.findByRole('heading', { name: 'Vehicle · Track 8' })).toBeInTheDocument();
      await user.keyboard('{k}');
      expect(await screen.findByRole('heading', { name: 'Person · Track 7' })).toBeInTheDocument();

      // Enter on the selected result's own control opens the full review —
      // the same rule as the List, decided by the shared contract rather than
      // by a class name belonging to one of the two views.
      control.focus();
      await user.keyboard('{Enter}');
      await waitFor(() => expect(screen.getByLabelText('Current search location'))
        .toHaveTextContent('/review/video/'));
    });

    it('leaves the shortcuts alone while the operator is typing a filter', async () => {
      const user = userEvent.setup();
      renderWithApp(<VisualSearchPage />, { route: '/search' });
      await screen.findByRole('list', { name: 'Track results' });
      await user.click(within(within(screen.getByRole('list', { name: 'Track results' }))
        .getAllByRole('listitem')[0]).getByRole('button', { name: /^Select / }));
      await screen.findByRole('heading', { name: 'Person · Track 7' });

      await user.click(screen.getByLabelText('Minimum confidence (%)'));
      await user.keyboard('jk');

      // The letters went into the field; they did not step the selection.
      expect(screen.getByLabelText('Minimum confidence (%)')).toHaveValue('jk');
      expect(screen.getByRole('heading', { name: 'Person · Track 7' })).toBeInTheDocument();
    });

    it('selects a result into the URL, shows its evidence in place and closes on Escape', async () => {
      const user = userEvent.setup();
      renderWithApp(<SearchHistoryHarness />, { route: '/search' });
      const rows = within(await screen.findByRole('list', { name: 'Track results' })).getAllByRole('listitem');
      expect(rows).toHaveLength(2);

      await user.click(within(rows[0]).getByRole('button', { name: /^Select / }));

      expect(await screen.findByRole('heading', { name: 'Person · Track 7' })).toBeInTheDocument();
      expect(screen.getByLabelText('Current search location')).toHaveTextContent('/search?track=' + first.id);
      expect(rows[0]).toHaveAttribute('aria-current', 'true');
      expect(screen.getByLabelText('Source video evidence')).toHaveAttribute('src', first.videoContentUrl);
      expect(vi.mocked(getTrack).mock.calls[0][0]).toBe(first.id);

      await user.keyboard('{Escape}');
      await waitFor(() => expect(screen.queryByRole('heading', { name: 'Person · Track 7' })).not.toBeInTheDocument());
      expect(screen.getByLabelText('Current search location')).toHaveTextContent('/search');
    });

    it('steps through results with the keyboard and opens the full review on Enter', async () => {
      const user = userEvent.setup();
      renderWithApp(<SearchHistoryHarness />, { route: '/search?track=' + first.id });
      await screen.findByRole('heading', { name: 'Person · Track 7' });

      await user.keyboard('j');
      expect(await screen.findByRole('heading', { name: 'Vehicle · Track 8' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Next result' })).toBeDisabled();

      await user.keyboard('k');
      expect(await screen.findByRole('heading', { name: 'Person · Track 7' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Previous result' })).toBeDisabled();

      await user.keyboard('{Enter}');
      await waitFor(() => expect(screen.getByLabelText('Current search location'))
        .toHaveTextContent('/review/video/' + first.videoAssetId + '?trackId=' + first.id));
    });

    it('drops the selection when a new search snapshot is committed', async () => {
      const user = userEvent.setup();
      renderWithApp(<SearchHistoryHarness />, { route: '/search?track=' + first.id });
      await screen.findByRole('heading', { name: 'Person · Track 7' });

      await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
      await user.click(screen.getByRole('button', { name: 'Search' }));

      await waitFor(() => expect(screen.getByLabelText('Current search location')).toHaveTextContent('/search?objectClass=Vehicle'));
      expect(screen.getByLabelText('Current search location')).not.toHaveTextContent('track=');
      expect(screen.queryByRole('heading', { name: 'Person · Track 7' })).not.toBeInTheDocument();
    });

    it('fetches the next snapshot page when stepping past the last loaded result', async () => {
      const user = userEvent.setup();
      const third = track('018f3f5a-2f70-7a2b-8a12-2d02f4c21453', { cameraName: 'South Gate' });
      vi.mocked(searchTracks)
        .mockResolvedValueOnce({ items: [first, second], nextCursor: 'page-two' })
        .mockResolvedValueOnce({ items: [third], nextCursor: null });
      vi.mocked(getTrack).mockImplementation(async (id) => detail([first, second, third].find((item) => item.id === id) ?? first, 9));

      renderWithApp(<VisualSearchPage />, { route: '/search?track=' + second.id });
      await screen.findByRole('heading', { name: 'Vehicle · Track 9' });

      await user.click(screen.getByRole('button', { name: 'Next result' }));

      await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
      expect(vi.mocked(searchTracks).mock.calls[1][0]).toEqual(expect.objectContaining({ cursor: 'page-two' }));
      expect(await screen.findByText(/3 \/ 3/)).toBeInTheDocument();
    });
  });
});
