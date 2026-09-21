import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getCamera } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { ApiError } from '../../api/client';
import { getProcessingStatus, getVideo, queueProcessing } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import ProcessingPage from './ProcessingPage';

vi.mock('../../api/cameras', () => ({ getCamera: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/videos', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/videos')>();
  return {
    ...original,
    getVideo: vi.fn(),
    getProcessingStatus: vi.fn(),
    queueProcessing: vi.fn(),
  };
});

const videoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';
const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';

describe('ProcessingPage', () => {
  beforeEach(() => {
    vi.mocked(getVideo).mockResolvedValue({
      id: videoId,
      cameraId,
      originalFileName: 'source.mp4',
      recordingStartUtc: '2026-09-09T02:30:00Z',
      recordingEndUtc: '2026-09-09T02:31:00Z',
      recordingTimeZoneId: 'UTC',
      recordingUtcOffsetMinutes: 0,
      durationMs: 60_000,
      width: 1920,
      height: 1080,
      frameRateNumerator: 25,
      frameRateDenominator: 1,
      codecName: 'h264',
      processingStatus: 'Processing',
      importedAtUtc: '2026-09-09T02:32:00Z',
    });
    vi.mocked(getCamera).mockResolvedValue({
      id: cameraId,
      code: 'CAM-COLD',
      name: 'Cold Cache Camera',
      description: null,
      locationName: null,
      timeZoneId: 'UTC',
      isActive: true,
      createdAtUtc: '2026-09-09T02:00:00Z',
      updatedAtUtc: '2026-09-09T02:00:00Z',
    });
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(getProcessingStatus).mockResolvedValue({
      videoStatus: 'Processing',
      latestRun: {
        processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
        status: 'Running',
        pipeline: 'phase1-detection-tracking',
        pipelineVersion: 'phase1-v1',
        workerId: 'worker-a',
        queuedAtUtc: '2026-09-09T02:30:00Z',
        startedAtUtc: '2026-09-09T02:30:02Z',
        completedAtUtc: null,
        progressPercent: 42.5,
        attemptCount: 1,
        failureCode: null,
        framesProcessed: 0,
        tracksCreated: 0,
      },
    });
    vi.mocked(queueProcessing).mockResolvedValue({ processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21432' });
  });

  const render = (id = videoId) => renderWithApp(<ProcessingPage />, {
    route: `/processing/${id}`,
    routePath: '/processing/:videoAssetId',
  });

  it('is a Record: a Context Bar that names the run, a primary column and a facts rail', async () => {
    const { container } = render();
    await screen.findByText('CAM-COLD · Cold Cache Camera');

    expect(container.querySelector('.workspace--record')).not.toBeNull();
    expect(container.querySelector('.workspace__record-facts')).not.toBeNull();
    // §4.2: a Record stays centred.
    expect(container.querySelector('.page--full')).toBeNull();

    // The breadcrumb is the way back to the queue, so the separate
    // "All processing" action is gone rather than duplicated beside it.
    const bar = container.querySelector('.context-bar') as HTMLElement;
    expect(within(bar).getByRole('link', { name: 'Processing' })).toHaveAttribute('href', '/processing');
    expect(bar).toHaveTextContent('source.mp4');
    expect(screen.queryByRole('link', { name: 'All processing' })).not.toBeInTheDocument();
  });

  it('keeps identifiers behind the diagnostics disclosure and out of ordinary content', async () => {
    const { container } = render();
    await screen.findByText('CAM-COLD · Cold Cache Camera');

    const diagnostics = screen.getByText('Diagnostics').closest('details') as HTMLElement;
    expect(within(diagnostics).getByText(videoId)).toBeInTheDocument();
    expect(within(diagnostics).getByText('worker-a')).toBeInTheDocument();

    // Nothing outside the disclosure shows a raw identifier.
    diagnostics.remove();
    expect(container.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-/);
  });

  it('states the display timezone once, on the surface, not as a diagnostic row', async () => {
    const { container } = render();
    await screen.findByText('CAM-COLD · Cold Cache Camera');

    const bar = container.querySelector('.context-bar') as HTMLElement;
    expect(within(bar).getByText('Asia/Kolkata')).toBeInTheDocument();
    expect(screen.queryByText('Display timezone')).not.toBeInTheDocument();
  });

  it('adds no Scene Analytics readiness, which belongs to a later slice', async () => {
    const { container } = render();
    await screen.findByText('CAM-COLD · Cold Cache Camera');
    expect(container.textContent).not.toMatch(/analytics|readiness|scene analysis/i);
  });

  it('does not repeat the run state as a second badge when it agrees with the video', async () => {
    const { container } = render();
    await screen.findByText('CAM-COLD · Cold Cache Camera');
    // Video Processing, run Running: the same answer in two vocabularies. The
    // Context Bar states it; the panel does not restate it.
    expect(container.querySelectorAll('.badge')).toHaveLength(1);

    // A run that genuinely disagrees is named.
    vi.mocked(getProcessingStatus).mockResolvedValue({
      videoStatus: 'Failed',
      latestRun: {
        processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
        status: 'Running',
        pipeline: 'phase1-detection-tracking',
        pipelineVersion: 'phase1-v1',
        workerId: 'worker-a',
        queuedAtUtc: '2026-09-09T02:30:00Z',
        startedAtUtc: '2026-09-09T02:30:02Z',
        completedAtUtc: null,
        progressPercent: 4,
        attemptCount: 3,
        failureCode: null,
        framesProcessed: 0,
        tracksCreated: 0,
      },
    });
    const divergent = render();
    await screen.findAllByText('CAM-COLD · Cold Cache Camera');
    await waitFor(() => expect(divergent.container.querySelectorAll('.badge')).toHaveLength(2));
  });

  it('refuses an invalid route and a missing video without losing the surface', async () => {
    const invalid = render('not-a-guid');
    expect(await screen.findByText(/identifier in this route is invalid/)).toBeInTheDocument();
    expect(invalid.container.querySelector('.context-bar')).not.toBeNull();
    invalid.unmount();

    vi.mocked(getVideo).mockRejectedValue(new ApiError({ status: 404, code: 'video_not_found', detail: 'No such video.' }));
    render();
    expect(await screen.findByText('Video was not found.')).toBeInTheDocument();
  });

  it('reports an unavailable status as unavailable rather than as no run', async () => {
    vi.mocked(getProcessingStatus).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Status store unavailable.' }));
    render();

    // The query retries once before failing terminally, so allow for it
    // rather than reading the retry window as the answer.
    expect(await screen.findByText('Processing status is unavailable.', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText('Not queued')).not.toBeInTheDocument();
  });

  it('leaves no notices band behind for a reconciled already-active queue attempt', async () => {
    const user = userEvent.setup();
    vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'NotQueued', latestRun: null });
    vi.mocked(queueProcessing).mockRejectedValue(new ApiError({
      status: 409,
      code: 'processing_already_active',
      detail: 'Processing is already active.',
    }));
    const { container } = render();

    await user.click(await screen.findByRole('button', { name: 'Queue processing' }));
    await waitFor(() => expect(queueProcessing).toHaveBeenCalledWith(videoId));

    // The conflict is reconciled by refetching authoritative state, not shown…
    await waitFor(() => expect(getProcessingStatus).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/already active/i)).not.toBeInTheDocument();
    // …so the region that would have carried it must not be opened at all.
    expect(container.querySelector('.workspace__notices')).toBeNull();
  });

  it('offers retry on a failed run and queues a new one', async () => {
    const user = userEvent.setup();
    vi.mocked(getProcessingStatus).mockResolvedValue({
      videoStatus: 'Failed',
      latestRun: {
        processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
        status: 'Failed',
        pipeline: 'phase1-detection-tracking',
        pipelineVersion: 'phase1-v1',
        workerId: 'worker-a',
        queuedAtUtc: '2026-09-09T02:30:00Z',
        startedAtUtc: '2026-09-09T02:30:02Z',
        completedAtUtc: '2026-09-09T02:35:02Z',
        progressPercent: 12,
        attemptCount: 2,
        failureCode: 'worker_watchdog_timeout',
        framesProcessed: 0,
        tracksCreated: 0,
      },
    });
    render();

    expect(await screen.findByText('worker_watchdog_timeout')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry processing' }));
    await waitFor(() => expect(queueProcessing).toHaveBeenCalledWith(videoId));
  });

  it('reconstructs camera context on a cold deep link and formats timestamps in configured deployment timezone', async () => {
    renderWithApp(<ProcessingPage />, {
      route: `/processing/${videoId}`,
      routePath: '/processing/:videoAssetId',
    });

    expect(await screen.findByText('CAM-COLD · Cold Cache Camera')).toBeInTheDocument();
    await waitFor(() => expect(getCamera).toHaveBeenCalledWith(cameraId, expect.any(AbortSignal)));
    expect(screen.getByText('Asia/Kolkata')).toBeInTheDocument();
    expect(screen.getAllByText(/08:00:0[02]/).length).toBeGreaterThan(0);
  });

  it('shows frame and Track counts only once a run has completed, never as live progress', async () => {
    vi.mocked(getProcessingStatus).mockResolvedValue({
      videoStatus: 'Processing',
      latestRun: {
        processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
        status: 'Running',
        pipeline: 'phase1-detection-tracking',
        pipelineVersion: 'phase1-v1',
        workerId: 'worker-a',
        queuedAtUtc: '2026-09-09T02:30:00Z',
        startedAtUtc: '2026-09-09T02:30:02Z',
        completedAtUtc: null,
        progressPercent: 42.5,
        attemptCount: 1,
        failureCode: null,
        framesProcessed: 6_000,
        tracksCreated: 3,
      },
    });
    const running = renderWithApp(<ProcessingPage />, {
      route: `/processing/${videoId}`,
      routePath: '/processing/:videoAssetId',
    });
    await screen.findByText('Progress');
    expect(screen.queryByText('6,000')).not.toBeInTheDocument();
    expect(screen.getByText('Frames processed').parentElement).toHaveTextContent(/final count after completion/i);
    running.unmount();

    vi.mocked(getProcessingStatus).mockResolvedValue({
      videoStatus: 'Processed',
      latestRun: {
        processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
        status: 'Completed',
        pipeline: 'phase1-detection-tracking',
        pipelineVersion: 'phase1-v1',
        workerId: 'worker-a',
        queuedAtUtc: '2026-09-09T02:30:00Z',
        startedAtUtc: '2026-09-09T02:30:02Z',
        completedAtUtc: '2026-09-09T02:40:02Z',
        progressPercent: 100,
        attemptCount: 1,
        failureCode: null,
        framesProcessed: 15_000,
        tracksCreated: 42,
      },
    });
    renderWithApp(<ProcessingPage />, {
      route: `/processing/${videoId}`,
      routePath: '/processing/:videoAssetId',
    });
    expect(await screen.findByText('15,000')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });
});
