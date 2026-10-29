import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { SIMILARITY_CANDIDATES_LABEL, searchTracks, type TrackSearchItem, type TrackSearchResponse } from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import VisualSearchPage, { APPEARANCE_PENDING_RETRIES } from './VisualSearchPage';

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

const searchDrawn = () => screen.findByLabelText('Object class', undefined, { timeout: 3000 });

function track(n: number, score: number): TrackSearchItem {
  return {
    id: `018f3f5a-2f70-7a2b-8a12-2d02f4c2145${n}`,
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
    videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
    cameraId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
    cameraCode: 'CAM-01',
    cameraName: 'North Gate',
    objectClass: 'Vehicle',
    startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:08Z',
    startOffsetMs: 10_000,
    endOffsetMs: 18_000,
    durationMs: 8_000,
    detectionCount: 32,
    meanConfidence: 0.91,
    maxConfidence: 0.97,
    reviewStatus: 'Unreviewed',
    thumbnailArtifactId: null,
    thumbnailContentUrl: null,
    videoContentUrl: '/api/videos/x/content',
    appearanceScore: score,
  };
}

const ranked: TrackSearchResponse = {
  items: [track(1, 0.31234), track(2, 0.29)],
  nextCursor: null,
  appearance: {
    label: SIMILARITY_CANDIDATES_LABEL,
    identityFingerprint: 'f'.repeat(64),
    modelId: 'siglip2-base-patch16-256',
    modelVersion: '2025-02',
    snapshot: 'tok',
    snapshotUtc: '2026-10-29T08:00:00Z',
  },
};

function pending(retryAfterSeconds = 2) {
  return new ApiError({ status: 503, code: 'appearance_query_pending', detail: 'Preparing the query.', retryAfterSeconds });
}

function Location() {
  const location = useLocation();
  return <output aria-label="Current search location">{location.search}</output>;
}

describe('PoC S4 appearance query on Search', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(listCameras).mockResolvedValue([]);
    vi.mocked(listVideos).mockResolvedValue([]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(searchTracks).mockResolvedValue(ranked);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('commits a description from the rail into the URL and asks for one ranked page', async () => {
    const user = userEvent.setup();
    renderWithApp(<><Location /><VisualSearchPage /></>, { route: '/search' });
    await searchDrawn();

    expect(screen.getByText('e.g. white van, person in red jacket')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Appearance (describe what to look for)'), 'white  van');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(screen.getByLabelText('Current search location')).toHaveTextContent('?appearanceQuery=white+van'));
    await waitFor(() => expect(searchTracks).toHaveBeenLastCalledWith(
      expect.objectContaining({ appearanceQuery: 'white van', limit: 50, cursor: undefined }),
      expect.any(AbortSignal),
    ));
    const chips = screen.getByRole('group', { name: 'Committed filters' });
    expect(within(chips).getByText('Appearance')).toBeInTheDocument();
    expect(chips).toHaveTextContent('white van');
  });

  it('labels the ranked results as similarity candidates and states each score', async () => {
    renderWithApp(<VisualSearchPage />, { route: '/search?appearanceQuery=white+van' });
    await searchDrawn();

    const results = screen.getByRole('region', { name: 'Search results' });
    expect(await within(results).findByText(SIMILARITY_CANDIDATES_LABEL)).toBeInTheDocument();
    expect(results).toHaveTextContent('Ranked by similarity score');
    expect(results).toHaveTextContent('Model siglip2-base-patch16-256 2025-02');
    expect(results).not.toHaveTextContent('Newest first');
    const rows = within(screen.getByRole('list', { name: 'Track results' })).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('0.312 similarity');
    expect(rows[1]).toHaveTextContent('0.290 similarity');
    // The rail field is rehydrated from the committed search.
    expect(screen.getByLabelText('Appearance (describe what to look for)')).toHaveValue('white van');
  });

  it('refuses a description beside plate text with a message on the appearance field', async () => {
    const user = userEvent.setup();
    renderWithApp(<><Location /><VisualSearchPage /></>, { route: '/search' });
    await searchDrawn();
    const calls = vi.mocked(searchTracks).mock.calls.length;

    await user.type(screen.getByLabelText('Plate text'), 'KA01AB1234');
    await user.type(screen.getByLabelText('Appearance (describe what to look for)'), 'white van');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    const field = screen.getByLabelText('Appearance (describe what to look for)');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(await screen.findByText(/Appearance search cannot be combined with plate text or analytics filters/)).toBeInTheDocument();
    expect(screen.getByLabelText('Current search location')).toHaveTextContent(/^$/);
    expect(vi.mocked(searchTracks).mock.calls.length).toBe(calls);
  });

  it('refuses a deep link that combines a description with plate text', async () => {
    renderWithApp(<VisualSearchPage />, { route: '/search?appearanceQuery=van&plateText=KA01' });
    await searchDrawn();
    expect(await screen.findByText(/This search link cannot be used\. Appearance search cannot be combined/)).toBeInTheDocument();
    expect(searchTracks).not.toHaveBeenCalled();
  });

  it('waits out a pending text embedding, saying so, then shows the ranked answer', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(searchTracks)
      .mockRejectedValueOnce(pending(2))
      .mockRejectedValueOnce(pending(2))
      .mockResolvedValueOnce(ranked);
    renderWithApp(<VisualSearchPage />, { route: '/search?appearanceQuery=white+van' });

    expect(await screen.findByText('Preparing appearance query…', undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(searchTracks).toHaveBeenCalledTimes(1);

    // Not before the Retry-After the server named.
    await act(() => vi.advanceTimersByTimeAsync(1_500));
    expect(searchTracks).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(600));
    expect(searchTracks).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Preparing appearance query…')).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(searchTracks).toHaveBeenCalledTimes(3);
    expect(await screen.findByRole('list', { name: 'Track results' })).toHaveTextContent('0.312 similarity');
    expect(screen.queryByText('Preparing appearance query…')).not.toBeInTheDocument();
  });

  it('stops after a bounded number of waits and offers a retry', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(searchTracks).mockRejectedValue(pending(2));
    renderWithApp(<VisualSearchPage />, { route: '/search?appearanceQuery=white+van' });

    await screen.findByText('Preparing appearance query…', undefined, { timeout: 3000 });
    for (let wait = 0; wait < APPEARANCE_PENDING_RETRIES; wait += 1) {
      await act(() => vi.advanceTimersByTimeAsync(2_100));
    }
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The appearance query is still being prepared. Retry in a moment.');
    expect(searchTracks).toHaveBeenCalledTimes(APPEARANCE_PENDING_RETRIES + 1);

    vi.mocked(searchTracks).mockResolvedValue(ranked);
    await act(async () => {
      within(alert.closest('.alert') as HTMLElement).getByRole('button', { name: 'Retry' }).click();
    });
    expect(await screen.findByRole('list', { name: 'Track results' })).toHaveTextContent('0.312 similarity');
  });

  it('says when appearance search is not configured, without a retry that cannot help', async () => {
    vi.mocked(searchTracks).mockRejectedValue(new ApiError({ status: 409, code: 'embeddings_not_configured', detail: 'No embeddings.' }));
    renderWithApp(<VisualSearchPage />, { route: '/search?appearanceQuery=white+van' });

    const alert = await screen.findByRole('alert', undefined, { timeout: 3000 });
    expect(alert).toHaveTextContent('Appearance search is not configured in this installation.');
    expect(within(alert.closest('.alert') as HTMLElement).queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });
});
