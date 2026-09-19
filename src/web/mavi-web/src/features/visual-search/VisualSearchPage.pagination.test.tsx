import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { getTrack, searchTracks, type TrackDetail, type TrackSearchItem } from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import VisualSearchPage from './VisualSearchPage';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, searchTracks: vi.fn(), getTrack: vi.fn() };
});
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});

const camera = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412', code: 'CAM-01', name: 'North Gate', description: null, locationName: null,
  timeZoneId: 'Asia/Kolkata', isActive: true, createdAtUtc: '2026-09-14T02:30:00Z', updatedAtUtc: '2026-09-14T02:30:00Z',
};

function track(id: string, overrides: Partial<TrackSearchItem> = {}): TrackSearchItem {
  return {
    id, processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431', videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
    cameraId: camera.id, cameraCode: camera.code, cameraName: camera.name, objectClass: 'Person',
    startTimestampUtc: '2026-09-14T02:30:00Z', endTimestampUtc: '2026-09-14T02:30:08Z', startOffsetMs: 10_000, endOffsetMs: 18_000,
    durationMs: 8_000, detectionCount: 32, meanConfidence: 0.91, maxConfidence: 0.97, reviewStatus: 'Unreviewed',
    thumbnailArtifactId: null, thumbnailContentUrl: null, videoContentUrl: '/api/videos/018f3f5a-2f70-7a2b-8a12-2d02f4c21421/content',
    ...overrides,
  };
}

function detail(item: TrackSearchItem, localTrackNumber: number): TrackDetail {
  return {
    id: item.id, processingRunId: item.processingRunId, videoAssetId: item.videoAssetId,
    camera: { id: item.cameraId, code: item.cameraCode, name: item.cameraName }, objectClass: item.objectClass, localTrackNumber,
    startOffsetMs: item.startOffsetMs, endOffsetMs: item.endOffsetMs, startTimestampUtc: item.startTimestampUtc, endTimestampUtc: item.endTimestampUtc,
    durationMs: item.durationMs, detectionCount: item.detectionCount, meanConfidence: item.meanConfidence, maxConfidence: item.maxConfidence,
    reviewStatus: item.reviewStatus,
    processing: { pipelineVersion: 'phase1', detectorName: 'RTMDet', detectorVersion: '1', trackerName: 'ByteTrack', trackerVersion: '1', completedAtUtc: '2026-09-14T02:40:00Z' },
    video: { recordingStartUtc: '2026-09-14T02:26:42Z', recordingEndUtc: '2026-09-14T02:36:42Z', durationMs: 600_000, width: 1920, height: 1080, frameRateNumerator: 25, frameRateDenominator: 1, videoContentUrl: item.videoContentUrl },
    representative: null, trajectoryArtifactId: null, trajectoryContentUrl: null,
  };
}

const A = track('018f3f5a-2f70-7a2b-8a12-2d02f4c21451');
const B = track('018f3f5a-2f70-7a2b-8a12-2d02f4c21452', { cameraName: 'East Gate' });
const C = track('018f3f5a-2f70-7a2b-8a12-2d02f4c21453', { cameraName: 'South Gate', objectClass: 'Vehicle' });
const D = track('018f3f5a-2f70-7a2b-8a12-2d02f4c21454', { cameraName: 'West Gate' });
const all = [A, B, C, D];

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="Current search location">{location.pathname + location.search}</output>;
}

function Harness() {
  return (<><LocationProbe /><VisualSearchPage /></>);
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 250));

describe('VisualSearchPage pagination and navigation guards', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(listVideos).mockResolvedValue([]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(getTrack).mockImplementation(async (id) => detail(all.find((item) => item.id === id) ?? A, 7));
  });

  it('stops automatic pagination after a transient continuation failure and offers an explicit retry', async () => {
    vi.mocked(searchTracks)
      .mockResolvedValueOnce({ items: [A, B], nextCursor: 'page-two' })
      .mockRejectedValue(new ApiError({ status: 503, code: 'search_unavailable', detail: 'Search backend unavailable.' }));

    renderWithApp(<Harness />, { route: '/search?track=' + B.id });
    await screen.findByRole('heading', { name: 'Person · Track 7' });

    // Selecting the last loaded row prefetches once (plus the query's single retry) and then stops.
    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(3));
    await settle();
    expect(searchTracks).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('button', { name: 'Retry load more' })).toBeInTheDocument();
    expect(screen.getByText(/next page could not be loaded/i)).toBeInTheDocument();

    // Stepping past the end after a failure must not fire another request either.
    await userEvent.setup().click(screen.getByRole('button', { name: 'Next result' }));
    await settle();
    expect(searchTracks).toHaveBeenCalledTimes(3);
  });

  it('requires an explicit refresh after the snapshot expires instead of retrying automatically', async () => {
    vi.mocked(searchTracks)
      .mockResolvedValueOnce({ items: [A, B], nextCursor: 'expired' })
      .mockRejectedValueOnce(new ApiError({ status: 400, code: 'track_search_invalid', detail: 'Cursor expired.' }))
      .mockResolvedValue({ items: [C], nextCursor: null });

    renderWithApp(<Harness />, { route: '/search?track=' + B.id });
    await screen.findByRole('heading', { name: 'Person · Track 7' });

    await waitFor(() => expect(searchTracks).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/snapshot can no longer continue/i)).toBeInTheDocument();
    await settle();
    expect(searchTracks).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: 'Refresh results' }));
    expect(await screen.findByText(/South Gate/)).toBeInTheDocument();
    expect(vi.mocked(searchTracks).mock.calls[2][0]).toEqual(expect.objectContaining({ cursor: undefined }));
  });

  function deferredSecondPage() {
    let release: (() => void) | undefined;
    vi.mocked(searchTracks).mockImplementation(async (filters) => {
      if (filters.cursor === 'page-two') {
        await new Promise<void>((resolve) => { release = resolve; });
        return { items: [D], nextCursor: null };
      }
      if (filters.objectClass === 'Vehicle') return { items: [C], nextCursor: null };
      return { items: [A, B], nextCursor: 'page-two' };
    });
    return () => release!();
  }

  it('advances onto the next page when it lands after stepping past the last loaded result', async () => {
    const release = deferredSecondPage();
    const user = userEvent.setup();
    renderWithApp(<Harness />, { route: '/search?track=' + B.id });
    await screen.findByRole('heading', { name: 'Person · Track 7' });

    await user.click(screen.getByRole('button', { name: 'Next result' }));
    release();

    await waitFor(() => expect(screen.getByLabelText('Current search location')).toHaveTextContent('track=' + D.id));
    expect((await screen.findAllByText(/West Gate/)).length).toBeGreaterThan(0);
  });

  it('ignores a late next-page response when the committed filters changed meanwhile', async () => {
    const release = deferredSecondPage();
    const user = userEvent.setup();
    renderWithApp(<Harness />, { route: '/search?track=' + B.id });
    await screen.findByRole('heading', { name: 'Person · Track 7' });
    await user.click(screen.getByRole('button', { name: 'Next result' }));

    await user.selectOptions(screen.getByLabelText('Object class'), 'Vehicle');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(screen.getByLabelText('Current search location')).toHaveTextContent('/search?objectClass=Vehicle'));
    release();
    await settle();

    expect(screen.getByLabelText('Current search location')).toHaveTextContent('/search?objectClass=Vehicle');
    expect(screen.getByLabelText('Current search location')).not.toHaveTextContent('track=');
    expect(within(screen.getByRole('list', { name: 'Track results' })).getAllByRole('listitem')).toHaveLength(1);
  });

  it('ignores a late next-page response when the selection changed meanwhile', async () => {
    const release = deferredSecondPage();
    const user = userEvent.setup();
    renderWithApp(<Harness />, { route: '/search?track=' + B.id });
    await screen.findByRole('heading', { name: 'Person · Track 7' });
    await user.click(screen.getByRole('button', { name: 'Next result' }));

    await user.click(screen.getByRole('button', { name: 'Previous result' }));
    await waitFor(() => expect(screen.getByLabelText('Current search location')).toHaveTextContent('track=' + A.id));
    release();
    await settle();

    expect(screen.getByLabelText('Current search location')).toHaveTextContent('track=' + A.id);
  });

  it('ignores a late next-page response when the inspector was closed meanwhile', async () => {
    const release = deferredSecondPage();
    const user = userEvent.setup();
    renderWithApp(<Harness />, { route: '/search?track=' + B.id });
    await screen.findByRole('heading', { name: 'Person · Track 7' });
    await user.click(screen.getByRole('button', { name: 'Next result' }));

    await user.click(screen.getByRole('button', { name: 'Close inspector' }));
    await waitFor(() => expect(screen.getByLabelText('Current search location')).not.toHaveTextContent('track='));
    release();
    await settle();

    expect(screen.getByLabelText('Current search location')).not.toHaveTextContent('track=');
    expect(screen.queryByRole('button', { name: 'Close inspector' })).not.toBeInTheDocument();
  });

  it('ignores a late next-page response after the page unmounted', async () => {
    const release = deferredSecondPage();
    const user = userEvent.setup();
    const view = renderWithApp(<Harness />, { route: '/search?track=' + B.id });
    await screen.findByRole('heading', { name: 'Person · Track 7' });
    await user.click(screen.getByRole('button', { name: 'Next result' }));

    view.unmount();
    release();
    await settle();
    expect(document.body.textContent).toBe('');
  });

  it('carries the committed search context into the full review link and back', async () => {
    vi.mocked(searchTracks).mockResolvedValue({ items: [A, B], nextCursor: null });
    const user = userEvent.setup();
    const route = '/search?cameraId=' + camera.id + '&objectClass=Person&track=' + B.id;

    renderWithApp(<Harness />, { route });
    await screen.findByRole('heading', { name: 'Person · Track 7' });

    const expectedFrom = encodeURIComponent('cameraId=' + camera.id + '&objectClass=Person&track=' + B.id);
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      '/review/video/' + B.videoAssetId + '?trackId=' + B.id + '&from=' + expectedFrom,
    );

    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByLabelText('Current search location'))
      .toHaveTextContent('/review/video/' + B.videoAssetId + '?trackId=' + B.id + '&from=' + expectedFrom));
  });

  it('opens the full review on Enter while the selected row button still has focus', async () => {
    vi.mocked(searchTracks).mockResolvedValue({ items: [A, B], nextCursor: null });
    const user = userEvent.setup();
    renderWithApp(<Harness />, { route: '/search' });
    const list = await screen.findByRole('list', { name: 'Track results' });
    const rows = within(list).getAllByRole('listitem');

    await user.click(within(rows[1]).getByRole('button', { name: /^Select / }));
    await screen.findByRole('heading', { name: 'Person · Track 7' });
    expect(within(rows[1]).getByRole('button', { name: /^Select / })).toHaveFocus();

    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByLabelText('Current search location'))
      .toHaveTextContent('/review/video/' + B.videoAssetId + '?trackId=' + B.id));
  });

  it('leaves Enter alone on other controls such as the Search button', async () => {
    vi.mocked(searchTracks).mockResolvedValue({ items: [A, B], nextCursor: null });
    const user = userEvent.setup();
    renderWithApp(<Harness />, { route: '/search?track=' + B.id });
    await screen.findByRole('heading', { name: 'Person · Track 7' });

    screen.getByRole('button', { name: 'Search' }).focus();
    await user.keyboard('{Enter}');
    await settle();
    // Enter activated the Search button (a new committed search, selection cleared) and did not open the review.
    expect(screen.getByLabelText('Current search location')).toHaveTextContent(/^\/search$/);
  });
});
