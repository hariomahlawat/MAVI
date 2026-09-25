import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { getProcessingStatus, listVideos, queueProcessing, type ProcessingRunStatus, type ProcessingStatus, type VideoAsset } from '../../api/videos';
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
    // §24: compact in the column, the full form on the cell. The year is
    // omitted in the current year, so the assertion does not pin one.
    const recorded = within(rows[0]).getAllByRole('cell')[2];
    expect(recorded.textContent).toMatch(/^14 Sept(?: \d{4})?, 07:30$/);
    expect(recorded.getAttribute('title')).toContain('14 Sept 2026, 07:30:00');
  });

  it('is a Ledger: a Context Bar, one scroll owner and a table that is not stretched', async () => {
    const { container } = renderWithApp(<VideosPage />, { route: '/videos' });
    await screen.findByRole('table');

    expect(container.querySelector('.workspace--ledger')).not.toBeNull();
    expect(container.querySelector('.page--full')).not.toBeNull();
    expect(container.querySelector('.workspace__body--scroll > table.table--ledger')).not.toBeNull();
    // §24: the display timezone is disclosed once, on the surface.
    expect(within(container.querySelector('.context-bar') as HTMLElement).getByText('Asia/Kolkata')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Import video' })).toHaveAttribute('href', '/import');
  });

  it('carries exactly one status badge per row and no identifier in a cell', async () => {
    // Named files, so the assertion is about the cells rather than about a
    // fixture that happens to name its file after its id.
    vi.mocked(listVideos).mockResolvedValue([
      video('018f3f5a-2f70-7a2b-8a12-2d02f4c2144a', { originalFileName: 'gate.mp4' }),
      video('018f3f5a-2f70-7a2b-8a12-2d02f4c2144b', { originalFileName: 'dock.mp4', processingStatus: 'Failed' }),
    ]);
    const { container } = renderWithApp(<VideosPage />, { route: '/videos' });
    const table = await screen.findByRole('table');
    for (const row of within(table).getAllByRole('row').slice(1)) {
      expect(row.querySelectorAll('.badge')).toHaveLength(1);
    }
    expect(container.querySelector('tbody')?.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/);
  });

  it('sorts on File, Camera, Recorded and Duration, and leaves Status to its filter', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideosPage />, { route: '/videos' });

    const files = async () => {
      const table = await screen.findByRole('table');
      return within(table).getAllByRole('row').slice(1)
        .map((row) => within(row).getAllByRole('cell')[0].textContent);
    };

    // The page opens on Recorded descending, exactly as before UI-3.
    expect(await files()).toEqual([processed.originalFileName, 'dock-night.mp4', 'yard.mp4']);
    expect(screen.getByRole('columnheader', { name: /Recorded/ })).toHaveAttribute('aria-sort', 'descending');

    await user.click(screen.getByRole('button', { name: 'Recorded' }));
    expect(screen.getByRole('columnheader', { name: /Recorded/ })).toHaveAttribute('aria-sort', 'ascending');
    expect(await files()).toEqual(['yard.mp4', 'dock-night.mp4', processed.originalFileName]);

    await user.click(screen.getByRole('button', { name: 'File' }));
    expect(await files()).toEqual([processed.originalFileName, 'dock-night.mp4', 'yard.mp4']);

    await user.click(screen.getByRole('button', { name: 'Duration' }));
    expect(screen.getByRole('columnheader', { name: /Duration/ })).toHaveAttribute('aria-sort', 'descending');

    expect(screen.getByRole('button', { name: 'Camera' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Status' })).not.toBeInTheDocument();
  });

  it('sorting is a view preference and writes nothing to the URL', async () => {
    const user = userEvent.setup();
    const { router } = renderWithApp(<VideosPage />, { route: '/videos?status=Failed', dataRouter: true });
    await screen.findByRole('table');

    await user.click(screen.getByRole('button', { name: 'File' }));
    expect(router.state.location.search).toBe('?status=Failed');
  });

  it('breaks recording ties in a fixed order rather than following the response', async () => {
    const tied = [
      video('018f3f5a-2f70-7a2b-8a12-2d02f4c2143a', { originalFileName: 'b.mp4', importedAtUtc: '2026-09-14T03:00:00Z' }),
      video('018f3f5a-2f70-7a2b-8a12-2d02f4c2143b', { originalFileName: 'a.mp4', importedAtUtc: '2026-09-14T04:00:00Z' }),
    ];
    vi.mocked(listVideos).mockResolvedValue(tied);
    const first = renderWithApp(<VideosPage />, { route: '/videos' });
    const order = within(await screen.findByRole('table')).getAllByRole('row').slice(1)
      .map((row) => within(row).getAllByRole('cell')[0].textContent);
    // Same recording start: the later import leads, as it always has.
    expect(order).toEqual(['a.mp4', 'b.mp4']);
    first.unmount();

    vi.mocked(listVideos).mockResolvedValue([...tied].reverse());
    renderWithApp(<VideosPage />, { route: '/videos' });
    const again = within(await screen.findByRole('table')).getAllByRole('row').slice(1)
      .map((row) => within(row).getAllByRole('cell')[0].textContent);
    expect(again).toEqual(order);
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

  it('keeps every committed URL filter exactly as it was', async () => {
    const user = userEvent.setup();
    const { router } = renderWithApp(
      <VideosPage />,
      { route: `/videos?q=dock&cameraId=${camera.id.toLowerCase()}&status=Failed`, dataRouter: true },
    );
    await screen.findByRole('table');

    expect(screen.getByLabelText('Filter by file or camera')).toHaveValue('dock');
    expect(screen.getByLabelText('Camera')).toHaveValue(camera.id.toLowerCase());
    expect(screen.getByLabelText('Status')).toHaveValue('Failed');

    await user.clear(screen.getByLabelText('Filter by file or camera'));
    await waitFor(() => expect(router.state.location.search)
      .toBe(`?cameraId=${camera.id.toLowerCase()}&status=Failed`));
  });

  it('distinguishes a filtered-empty result from an empty inventory', async () => {
    renderWithApp(<VideosPage />, { route: '/videos?q=nothing-matches-this' });
    expect(await screen.findByText('No videos match these filters')).toBeInTheDocument();
    expect(screen.queryByText('No videos imported yet')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
  });

  it('still lists videos whose camera metadata could not be resolved', async () => {
    vi.mocked(listCameras).mockRejectedValue(new Error('down'));
    renderWithApp(<VideosPage />, { route: '/videos' });

    expect(await screen.findByText(/Camera metadata is unavailable/)).toBeInTheDocument();
    expect(within(await screen.findByRole('table')).getAllByRole('row')).toHaveLength(4);
  });

  it('offers the import action when nothing has been imported', async () => {
    vi.mocked(listVideos).mockResolvedValue([]);
    renderWithApp(<VideosPage />, { route: '/videos' });
    expect(await screen.findByText('No videos imported yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Import the first video' })).toHaveAttribute('href', '/import');
  });
});

/** A latest run, as `GET /api/videos/{id}/processing` returns it. */
function run(extra: Partial<ProcessingRunStatus>): ProcessingRunStatus {
  return {
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431', status: 'Failed', pipeline: 'phase1-detection-tracking', pipelineVersion: 'phase1-v1',
    workerId: 'worker-a', queuedAtUtc: '2026-09-14T03:02:00Z', startedAtUtc: '2026-09-14T03:02:02Z', completedAtUtc: '2026-09-14T03:09:02Z',
    progressPercent: 100, attemptCount: 1, failureCode: null, framesProcessed: 0, tracksCreated: 0, analyticsReadiness: 'NotConfigured', phase: 'failed',
    ...extra,
  };
}

/**
 * U1. These go through the page's real lookup — VideosPage → useVideoProcessing
 * → getProcessingStatus — with one answer per video id, so a row can only show
 * a run the page actually asked for. Nothing is handed to a row directly.
 */
describe('VideosPage latest-run lookup (U1)', () => {
  const active = video('018f3f5a-2f70-7a2b-8a12-2d02f4c21424', { originalFileName: 'gate-live.mp4', processingStatus: 'Processing', recordingStartUtc: '2026-09-11T02:00:00Z' });

  function answer(byId: Record<string, ProcessingStatus>) {
    vi.mocked(getProcessingStatus).mockImplementation(async (id) => {
      const status = byId[id];
      if (!status) throw new Error(`the page requested ${id}, which this test never expected it to`);
      return status;
    });
  }

  const requestsFor = (id: string) => vi.mocked(getProcessingStatus).mock.calls.filter(([requested]) => requested === id).length;

  async function statusCell(fileName: string): Promise<HTMLElement> {
    const row = (await screen.findByText(fileName)).closest('tr') as HTMLElement;
    return within(row).getAllByRole('cell')[4];
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(listVideos).mockResolvedValue([fresh, failed, processed, active]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('requests the latest run for Failed and active rows, and never for Processed or NotQueued rows', async () => {
    answer({
      [failed.id]: { videoStatus: 'Failed', latestRun: run({ failureCode: 'worker_watchdog_timeout' }) },
      [active.id]: { videoStatus: 'Processing', latestRun: run({ status: 'Running', phase: 'processing', progressPercent: 40, completedAtUtc: null }) },
    });
    renderWithApp(<VideosPage />, { route: '/videos' });
    await screen.findByRole('table');

    await waitFor(() => expect(getProcessingStatus).toHaveBeenCalledWith(failed.id, expect.anything()));
    await waitFor(() => expect(getProcessingStatus).toHaveBeenCalledWith(active.id, expect.anything()));
    expect(getProcessingStatus).not.toHaveBeenCalledWith(processed.id, expect.anything());
    expect(getProcessingStatus).not.toHaveBeenCalledWith(fresh.id, expect.anything());
  });

  it('names a finalization failure it looked up, keeps its code, and does not keep polling the terminal row', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    answer({
      // Pending readiness on a failed run is what the platform reports for a
      // camera with analytics enabled: it must not become a polling loop.
      [failed.id]: {
        videoStatus: 'Failed',
        latestRun: run({ failureCode: 'vision_finalization_staging_missing', analyticsReadiness: 'Pending' }),
      },
      [active.id]: { videoStatus: 'Processing', latestRun: run({ status: 'Running', phase: 'processing', progressPercent: 40, completedAtUtc: null }) },
    });
    renderWithApp(<VideosPage />, { route: '/videos' });

    const cell = await statusCell('dock-night.mp4');
    expect(await within(cell).findByText('Run: Finalization failed')).toBeInTheDocument();
    expect(within(cell).getByText('vision_finalization_staging_missing').tagName).toBe('CODE');
    expect(cell.querySelectorAll('.badge')).toHaveLength(1);
    expect(within(cell).getByText('Failed')).toHaveAttribute('data-status', 'Failed');
    expect(within(cell).queryByRole('progressbar')).not.toBeInTheDocument();

    // Five poll periods. The active row is the control: it does poll, so the
    // clock really moved the queries; the terminal failed row was asked once.
    await vi.advanceTimersByTimeAsync(10_000);
    expect(requestsFor(active.id)).toBeGreaterThan(1);
    expect(requestsFor(failed.id)).toBe(1);
  });

  it('leaves an ordinary failure it looked up as an ordinary failure', async () => {
    answer({
      [failed.id]: { videoStatus: 'Failed', latestRun: run({ failureCode: 'worker_watchdog_timeout' }) },
      [active.id]: { videoStatus: 'Processing', latestRun: run({ status: 'Running', phase: 'processing', progressPercent: 40, completedAtUtc: null }) },
    });
    renderWithApp(<VideosPage />, { route: '/videos' });

    const cell = await statusCell('dock-night.mp4');
    expect(await within(cell).findByText('worker_watchdog_timeout')).toBeInTheDocument();
    expect(within(cell).queryByText(/Finalization failed/)).not.toBeInTheDocument();
    expect(within(cell).queryByText(/^Run:/)).not.toBeInTheDocument();
    expect(cell.querySelectorAll('.badge')).toHaveLength(1);
    expect(within(cell).queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('names a Finalizing run and draws no inference bar for it', async () => {
    answer({
      [failed.id]: { videoStatus: 'Failed', latestRun: run({ failureCode: 'worker_watchdog_timeout' }) },
      [active.id]: { videoStatus: 'Processing', latestRun: run({ status: 'Running', phase: 'finalizing', progressPercent: 100, completedAtUtc: null }) },
    });
    renderWithApp(<VideosPage />, { route: '/videos' });

    const cell = await statusCell('gate-live.mp4');
    expect(await within(cell).findByText('Run: Finalizing')).toBeInTheDocument();
    expect(within(cell).queryByRole('progressbar')).not.toBeInTheDocument();
    expect(within(cell).queryByText(/Running/)).not.toBeInTheDocument();
    expect(cell.querySelectorAll('.badge')).toHaveLength(1);
    expect(within(cell).getByText('Processing')).toHaveAttribute('data-status', 'Processing');
  });
});
