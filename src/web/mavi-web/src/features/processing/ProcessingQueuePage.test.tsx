import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { ApiError } from '../../api/client';
import { getProcessingStatus, listVideos, type ProcessingRunStatus, type VideoAsset } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import ProcessingQueuePage, { bucketFor, orderForQueue } from './ProcessingQueuePage';
import { joinVideoRows } from '../videos/videoRows';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn(), getProcessingStatus: vi.fn() };
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

function run(status: string, extra: Partial<ProcessingRunStatus> = {}): ProcessingRunStatus {
  return {
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431', status, pipeline: 'phase1-detection-tracking', pipelineVersion: 'phase1-v1',
    workerId: 'worker-a', queuedAtUtc: '2026-09-14T03:02:00Z', startedAtUtc: '2026-09-14T03:02:02Z', completedAtUtc: null,
    progressPercent: 0, attemptCount: 1, failureCode: null, framesProcessed: 0, tracksCreated: 0, ...extra,
  };
}

const done = video('018f3f5a-2f70-7a2b-8a12-2d02f4c21421', 'Processed');
const running = video('018f3f5a-2f70-7a2b-8a12-2d02f4c21422', 'Processing');
const failed = video('018f3f5a-2f70-7a2b-8a12-2d02f4c21423', 'Failed');
const idle = video('018f3f5a-2f70-7a2b-8a12-2d02f4c21424', 'NotQueued');

describe('processing queue ordering', () => {
  it('buckets statuses and orders active, failed, completed while dropping unqueued videos', () => {
    expect(bucketFor('Queued')).toBe('active');
    expect(bucketFor('NotQueued')).toBeNull();
    const rows = joinVideoRows([done, idle, failed, running], [camera]);
    expect(orderForQueue(rows).map((row) => row.processingStatus)).toEqual(['Processing', 'Failed', 'Processed']);
  });
});

describe('ProcessingQueuePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(listVideos).mockResolvedValue([done, idle, failed, running]);
    vi.mocked(getProcessingStatus).mockImplementation(async (id) => {
      if (id === running.id) return { videoStatus: 'Processing', latestRun: run('Running', { progressPercent: 42.5, framesProcessed: 6_000 }) };
      if (id === failed.id) return { videoStatus: 'Failed', latestRun: run('Failed', { failureCode: 'worker_watchdog_timeout' }) };
      return { videoStatus: 'Processed', latestRun: run('Completed', { progressPercent: 100, completedAtUtc: '2026-09-14T03:12:02Z', tracksCreated: 42 }) };
    });
  });

  it('counts the queue and lists runs with worker, failure code and Track totals', async () => {
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);

    expect(await within(rows[0]).findByText('Running')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '43');
    expect(await within(rows[1]).findByText('worker_watchdog_timeout')).toBeInTheDocument();
    expect(await within(rows[2]).findByText('42')).toBeInTheDocument();
    expect(within(rows[2]).getByRole('link', { name: 'Results' })).toHaveAttribute('href', `/search?videoAssetId=${done.id}`);
    expect(within(rows[0]).getByRole('link', { name: 'Detail' })).toHaveAttribute('href', `/processing/${running.id}`);

    expect(screen.getByText('Active').parentElement).toHaveTextContent('1');
    expect(screen.getByText('Failed', { selector: '.stat__label' }).parentElement).toHaveTextContent('1');
    expect(screen.getByText('Completed', { selector: '.stat__label' }).parentElement).toHaveTextContent('1');
  });

  it('points to the Videos page when nothing has been queued', async () => {
    vi.mocked(listVideos).mockResolvedValue([idle]);
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    expect(await screen.findByText('Nothing has been queued')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Videos' })).toHaveAttribute('href', '/videos');
  });

  it('describes the table as the latest run per video, not a run history', async () => {
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    await screen.findByRole('table');
    expect(screen.getByText(/latest run per video/i)).toBeInTheDocument();
    expect(screen.queryByText(/processing history/i)).not.toBeInTheDocument();
  });

  it('shows a per-video status failure with a retry instead of loading forever', async () => {
    const user = userEvent.setup();
    vi.mocked(getProcessingStatus).mockImplementation(async (id) => {
      if (id === failed.id) throw new ApiError({ status: 503, code: 'status_unavailable', detail: 'Status store unavailable.' });
      return { videoStatus: 'Processed', latestRun: run('Completed', { progressPercent: 100, tracksCreated: 42 }) };
    });

    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);

    expect(await within(rows[1]).findByText(/run status unavailable/i)).toBeInTheDocument();
    expect(within(rows[1]).queryByText(/Loading run/)).not.toBeInTheDocument();

    vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'Failed', latestRun: run('Failed', { failureCode: 'worker_watchdog_timeout' }) });
    await user.click(within(rows[1]).getByRole('button', { name: /retry/i }));
    expect(await within(rows[1]).findByText('worker_watchdog_timeout')).toBeInTheDocument();
  });

  it('does not claim to be loading or show zero counts when the inventory request failed', async () => {
    vi.mocked(listVideos).mockRejectedValue(new ApiError({ status: 500, code: 'api_error', detail: 'The request could not be completed.' }));
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    expect(await screen.findByText(/could not be completed/)).toBeInTheDocument();
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
  });
});
