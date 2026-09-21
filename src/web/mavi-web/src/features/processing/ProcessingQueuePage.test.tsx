import { screen, waitFor, within } from '@testing-library/react';
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

  it('lists the active, failed and completed runs with their failure code and Track totals', async () => {
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);

    expect(await within(rows[0]).findByText('Processing')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '43');
    expect(await within(rows[1]).findByText('worker_watchdog_timeout')).toBeInTheDocument();
    expect(await within(rows[2]).findByText('42')).toBeInTheDocument();
    expect(within(rows[2]).getByRole('link', { name: 'Results' })).toHaveAttribute('href', `/search?videoAssetId=${done.id}`);
    expect(within(rows[0]).getByRole('link', { name: 'Detail' })).toHaveAttribute('href', `/processing/${running.id}`);
  });

  it('is a Ledger with one scroll owner, no stat cards and no operator sorting', async () => {
    const { container } = renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    await screen.findByRole('table');

    expect(container.querySelector('.workspace--ledger')).not.toBeNull();
    expect(container.querySelector('.page--full')).not.toBeNull();
    expect(container.querySelector('.workspace__body--scroll > table.table--ledger')).not.toBeNull();
    // §30: no stat tiles restating the table below them.
    expect(container.querySelector('.stat')).toBeNull();
    // §32 decision 5: this Ledger's order is the statement; nothing re-orders it.
    expect(screen.queryAllByRole('button', { name: /^(Video|Status|Queued|Attempt|Tracks)$/ })).toHaveLength(0);
    for (const header of screen.getAllByRole('columnheader')) {
      expect(header).not.toHaveAttribute('aria-sort');
    }
  });

  it('states the counts as operational context beside the table', async () => {
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    await screen.findByRole('table');
    const counts = document.querySelector('.queue-counts') as HTMLElement;
    expect(counts).toHaveTextContent('1 active');
    expect(counts).toHaveTextContent('1 failed');
    expect(counts).toHaveTextContent('1 completed');
  });

  it('carries exactly one status badge per row and no identifier in a cell', async () => {
    // Named files, so the assertion is about the cells rather than about a
    // fixture that happens to name its file after its id.
    vi.mocked(listVideos).mockResolvedValue([
      { ...done, originalFileName: 'gate.mp4' },
      { ...failed, originalFileName: 'dock.mp4' },
    ]);
    const { container } = renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    const table = await screen.findByRole('table');
    for (const row of within(table).getAllByRole('row').slice(1)) {
      await waitFor(() => expect(row.querySelectorAll('.badge')).toHaveLength(1));
    }
    expect(container.querySelector('tbody')?.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/);
  });

  it('names the run state only where it disagrees with the video state', async () => {
    // A video the platform still calls Failed while its newest run is already
    // running again: the two genuinely differ, so the run is named — as text,
    // never as a second badge (§16).
    vi.mocked(getProcessingStatus).mockImplementation(async () =>
      ({ videoStatus: 'Failed', latestRun: run('Running', { progressPercent: 10 }) }));
    vi.mocked(listVideos).mockResolvedValue([failed]);
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });

    const row = within(await screen.findByRole('table')).getAllByRole('row')[1];
    expect(await within(row).findByText('Run: Running')).toBeInTheDocument();
    await waitFor(() => expect(row.querySelectorAll('.badge')).toHaveLength(1));
  });

  it('points to the Videos page when nothing has been queued', async () => {
    vi.mocked(listVideos).mockResolvedValue([idle]);
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    expect(await screen.findByText('Nothing has been queued')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Videos' })).toHaveAttribute('href', '/videos');
  });

  it('keeps the latest-run-per-video statement now that the page header is gone', async () => {
    renderWithApp(<ProcessingQueuePage />, { route: '/processing' });
    await screen.findByRole('table');
    // It moved from a page description into the toolbar band, where it
    // qualifies the table and does not scroll away from it.
    const band = document.querySelector('.toolbar-band') as HTMLElement;
    expect(band).toHaveTextContent(/latest run per video/i);
    expect(band).toHaveTextContent(/earlier runs are not listed here/i);
    expect(screen.queryByText(/processing history/i)).not.toBeInTheDocument();
    // The table itself is still named for assistive technology.
    expect(screen.getByRole('table', { name: 'Latest processing run per video' })).toBeInTheDocument();
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
    expect(screen.queryByText('Loading processing state…')).not.toBeInTheDocument();
    // §14: an unavailable inventory is never an empty one, and never a set of
    // zeroes presented as an answer.
    expect(screen.queryByText('Nothing has been queued')).not.toBeInTheDocument();
    expect(document.querySelector('.queue-counts')).toBeNull();
  });
});
