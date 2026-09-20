import { screen, within } from '@testing-library/react';
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
});
