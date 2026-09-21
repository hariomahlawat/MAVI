import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { searchTracks, type TrackSearchItem } from '../../api/tracks';
import { listVideos, type VideoAsset } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import OverviewPage from './OverviewPage';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});
vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, searchTracks: vi.fn() };
});

const camera = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412', code: 'CAM-01', name: 'North Gate', description: null, locationName: null,
  timeZoneId: 'Asia/Kolkata', isActive: true, createdAtUtc: '2026-09-14T02:30:00Z', updatedAtUtc: '2026-09-14T02:30:00Z',
};

function video(id: string, processingStatus: string): VideoAsset {
  return {
    id, cameraId: camera.id, originalFileName: `${id}.mp4`, recordingStartUtc: '2026-09-14T02:00:00Z', recordingEndUtc: '2026-09-14T02:10:00Z',
    recordingTimeZoneId: 'Asia/Kolkata', recordingUtcOffsetMinutes: 330, durationMs: 600_000, width: 1920, height: 1080,
    frameRateNumerator: 25, frameRateDenominator: 1, codecName: 'h264', processingStatus, importedAtUtc: '2026-09-14T03:00:00Z',
  };
}

const track: TrackSearchItem = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21451', processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431', videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
  cameraId: camera.id, cameraCode: camera.code, cameraName: camera.name, objectClass: 'Vehicle', startTimestampUtc: '2026-09-14T02:30:00Z',
  endTimestampUtc: '2026-09-14T02:30:08Z', startOffsetMs: 10_000, endOffsetMs: 18_000, durationMs: 8_000, detectionCount: 32,
  meanConfidence: 0.91, maxConfidence: 0.97, reviewStatus: 'Unreviewed', thumbnailArtifactId: null, thumbnailContentUrl: null,
  videoContentUrl: '/api/videos/018f3f5a-2f70-7a2b-8a12-2d02f4c21421/content',
};

describe('OverviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera, { ...camera, id: 'x', isActive: false }]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(listVideos).mockResolvedValue([video('a', 'Processed'), video('b', 'Processing'), video('c', 'Failed'), video('d', 'NotQueued'), video('e', 'Queued')]);
    vi.mocked(searchTracks).mockResolvedValue({ items: [track], nextCursor: null });
  });

  it('summarises cameras, media status and the newest Tracks with links into each workflow', async () => {
    renderWithApp(<OverviewPage />, { route: '/' });

    const cameras = await screen.findByRole('link', { name: /Cameras.*2.*1 active/ });
    expect(cameras).toHaveAttribute('href', '/cameras');
    expect(screen.getByRole('link', { name: /Videos.*5.*1 processed/ })).toHaveAttribute('href', '/videos');
    expect(screen.getByRole('link', { name: /Processing.*2.*1 failed/ })).toHaveAttribute('href', '/processing');
    expect(screen.getByRole('link', { name: /Not queued.*1/ })).toHaveAttribute('href', '/videos?status=NotQueued');

    const recent = (await screen.findByText('Vehicle')).closest('a') as HTMLAnchorElement;
    expect(recent).toHaveAttribute('href', `/search?videoAssetId=${track.videoAssetId}&track=${track.id}`);
    expect(recent).toHaveTextContent('CAM-01 · North Gate');
    expect(recent).toHaveTextContent('14 Sept 2026, 08:00:00 · 8s · 91%');
    expect(within(recent).getByText('Unreviewed')).toBeInTheDocument();
    expect(vi.mocked(searchTracks).mock.calls[0][0]).toEqual({ limit: 8 });
  });

  it('explains an empty deployment instead of showing blank tiles', async () => {
    vi.mocked(listVideos).mockResolvedValue([]);
    vi.mocked(searchTracks).mockResolvedValue({ items: [], nextCursor: null });
    renderWithApp(<OverviewPage />, { route: '/' });
    expect(await screen.findByText('No tracks yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Videos.*0.*0 processed/ })).toBeInTheDocument();
  });

  it('is the Ledger-summary variant: a Context Bar, one scroll owner and uncontained readouts', async () => {
    const { container } = renderWithApp(<OverviewPage />, { route: '/' });
    await screen.findByText('Vehicle');

    expect(container.querySelector('.workspace--ledger-summary')).not.toBeNull();
    expect(container.querySelector('.context-bar')).not.toBeNull();
    expect(container.querySelectorAll('.workspace__body--scroll')).toHaveLength(1);
    // §4.1.1: Overview alone stays centred, so it must not declare full width.
    expect(container.querySelector('.page--full')).toBeNull();
    // §11: the four summary readouts are figures, not cards.
    expect(container.querySelector('.summary-band')).not.toBeNull();
    expect(container.querySelector('.stat')).toBeNull();
    // §24: the display timezone is disclosed once, on the surface.
    expect(within(container.querySelector('.context-bar') as HTMLElement).getByText('Asia/Kolkata')).toBeInTheDocument();
  });

  it('keeps both Context Bar workflow actions', async () => {
    renderWithApp(<OverviewPage />, { route: '/' });
    expect(await screen.findByRole('link', { name: 'Import video' })).toHaveAttribute('href', '/import');
    expect(screen.getByRole('link', { name: 'Search tracks' })).toHaveAttribute('href', '/search');
  });

  it('degrades only the section whose request failed', async () => {
    vi.mocked(listVideos).mockRejectedValue(new Error('down'));
    renderWithApp(<OverviewPage />, { route: '/' });

    // The media figures say they are unavailable rather than reading as zero…
    expect(await screen.findByText(/video inventory is unavailable/i)).toBeInTheDocument();
    expect(screen.getByText('Media status unavailable')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Videos.*—.*unavailable/ })).toBeInTheDocument();

    // …while the two sections that answered are untouched.
    expect(screen.getByRole('link', { name: /Cameras.*2.*1 active/ })).toBeInTheDocument();
    expect(screen.getByText('Vehicle')).toBeInTheDocument();
  });

  it('states an unavailable camera inventory as unavailable, with a retry', async () => {
    const user = userEvent.setup();
    vi.mocked(listCameras).mockRejectedValue(new Error('down'));
    renderWithApp(<OverviewPage />, { route: '/' });

    // §14: unavailable is an alert with a retry, not a dash and a word.
    expect(await screen.findByText(/camera inventory is unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Cameras.*—.*unavailable/ })).toBeInTheDocument();
    expect(screen.queryByText('No cameras registered')).not.toBeInTheDocument();

    // The sections that answered are untouched.
    expect(screen.getByRole('link', { name: /Videos.*5.*1 processed/ })).toBeInTheDocument();
    expect(screen.getByText('Vehicle')).toBeInTheDocument();

    vi.mocked(listCameras).mockResolvedValue([camera]);
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByRole('link', { name: /Cameras.*1.*1 active/ })).toBeInTheDocument());
  });

  it('states both inventories in one notice rather than a stack of alerts', async () => {
    vi.mocked(listCameras).mockRejectedValue(new Error('down'));
    vi.mocked(listVideos).mockRejectedValue(new Error('down'));
    renderWithApp(<OverviewPage />, { route: '/' });

    const notice = await screen.findByText(/camera inventory and the video inventory are unavailable/i);
    expect(notice).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    // The one section that answered still answers.
    expect(screen.getByText('Vehicle')).toBeInTheDocument();
  });

  it('keeps an empty camera inventory distinct from an unavailable one', async () => {
    vi.mocked(listCameras).mockResolvedValue([]);
    renderWithApp(<OverviewPage />, { route: '/' });

    await screen.findByText('Vehicle');
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Cameras.*0.*0 active/ })).toBeInTheDocument();
  });

  it('keeps recent Tracks when only the Track search failed', async () => {
    vi.mocked(searchTracks).mockRejectedValue(new Error('down'));
    renderWithApp(<OverviewPage />, { route: '/' });

    expect(await screen.findByText('Recent tracks are unavailable.')).toBeInTheDocument();
    expect(screen.queryByText('No tracks yet')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Videos.*5.*1 processed/ })).toBeInTheDocument();
  });
});
