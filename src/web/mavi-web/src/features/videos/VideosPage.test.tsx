import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { getProcessingStatus, listVideos, queueProcessing, type VideoAsset } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import VideosPage from './VideosPage';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn(), queueProcessing: vi.fn(), getProcessingStatus: vi.fn() };
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

function video(id: string, overrides: Partial<VideoAsset> = {}): VideoAsset {
  return {
    id,
    cameraId: camera.id,
    originalFileName: `${id}.mp4`,
    recordingStartUtc: '2026-09-14T02:00:00Z',
    recordingEndUtc: '2026-09-14T02:10:00Z',
    recordingTimeZoneId: 'Asia/Kolkata',
    recordingUtcOffsetMinutes: 330,
    durationMs: 600_000,
    width: 1920,
    height: 1080,
    frameRateNumerator: 25,
    frameRateDenominator: 1,
    codecName: 'h264',
    processingStatus: 'Processed',
    importedAtUtc: '2026-09-14T03:00:00Z',
    ...overrides,
  };
}

const processed = video('018f3f5a-2f70-7a2b-8a12-2d02f4c21421');
const failed = video('018f3f5a-2f70-7a2b-8a12-2d02f4c21422', { originalFileName: 'dock-night.mp4', processingStatus: 'Failed', recordingStartUtc: '2026-09-13T02:00:00Z' });
const fresh = video('018f3f5a-2f70-7a2b-8a12-2d02f4c21423', { originalFileName: 'yard.mp4', processingStatus: 'NotQueued', recordingStartUtc: '2026-09-12T02:00:00Z' });

describe('VideosPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(listVideos).mockResolvedValue([fresh, failed, processed]);
    vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'Processed', latestRun: null });
    vi.mocked(queueProcessing).mockResolvedValue({ processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21432' });
  });

  it('lists videos newest first with status, results link and the right action per state', async () => {
    renderWithApp(<VideosPage />, { route: '/videos' });
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((row) => within(row).getAllByRole('cell')[0].textContent)).toEqual([
      expect.stringContaining(processed.originalFileName),
      expect.stringContaining('dock-night.mp4'),
      expect.stringContaining('yard.mp4'),
    ]);

    expect(within(rows[0]).getByRole('link', { name: 'Results' })).toHaveAttribute('href', `/search?videoAssetId=${processed.id}`);
    expect(within(rows[1]).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(within(rows[2]).getByRole('button', { name: 'Process' })).toBeInTheDocument();
    expect(within(rows[0]).getByText('CAM-01')).toBeInTheDocument();
    expect(within(rows[0]).getByText('14 Sept 2026, 07:30:00')).toBeInTheDocument();
  });

  it('queues processing for a not-queued video and refreshes the inventory', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideosPage />, { route: '/videos' });
    await screen.findByRole('table');

    await user.click(screen.getByRole('button', { name: 'Process' }));

    await waitFor(() => expect(queueProcessing).toHaveBeenCalledWith(fresh.id));
    await waitFor(() => expect(listVideos).toHaveBeenCalledTimes(2));
  });

  it('applies the status filter from the URL and reports the filtered count', async () => {
    renderWithApp(<VideosPage />, { route: '/videos?status=Failed' });
    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(2);
    expect(screen.getByText('1 of 3 videos match the filters')).toBeInTheDocument();
    expect(screen.getByLabelText('Status')).toHaveValue('Failed');
  });

  it('offers the import action when nothing has been imported', async () => {
    vi.mocked(listVideos).mockResolvedValue([]);
    renderWithApp(<VideosPage />, { route: '/videos' });
    expect(await screen.findByText('No videos imported yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Import the first video' })).toHaveAttribute('href', '/import');
  });
});
