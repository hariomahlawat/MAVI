import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getProcessingStatus, importVideo, queueProcessing } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { renderWithApp } from '../../test/renderWithApp';
import VideoImportPage, { runImportWorkflow } from './VideoImportPage';

vi.mock('../../api/cameras', () => ({
  listCameras: vi.fn(),
}));

vi.mock('../../api/videos', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/videos')>();
  return {
    ...original,
    importVideo: vi.fn(),
    queueProcessing: vi.fn(),
    getProcessingStatus: vi.fn(),
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

const video = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
  cameraId: camera.id,
  originalFileName: 'source.mp4',
  recordingStartUtc: '2026-09-14T03:00:00Z',
  recordingEndUtc: '2026-09-14T03:01:00Z',
  recordingTimeZoneId: 'Asia/Kolkata',
  recordingUtcOffsetMinutes: 330,
  durationMs: 60_000,
  width: 1920,
  height: 1080,
  frameRateNumerator: 25,
  frameRateDenominator: 1,
  codecName: 'h264',
  processingStatus: 'NotQueued',
  importedAtUtc: '2026-09-14T03:02:00Z',
};

describe('VideoImportPage', () => {
  beforeEach(() => {
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(importVideo).mockResolvedValue(video);
    vi.mocked(queueProcessing).mockResolvedValue({ processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431' });
    vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'NotQueued', latestRun: null });
  });

  it('is a Record: a Context Bar, a contained form and a facts rail', async () => {
    const { container } = renderWithApp(<VideoImportPage />);
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });

    expect(container.querySelector('.workspace--record')).not.toBeNull();
    expect(container.querySelector('.workspace__record-facts')).not.toBeNull();
    // §4.2: a Record is centred, never full width.
    expect(container.querySelector('.page--full')).toBeNull();
    // The facts rail carries the constraints that used to be loose prose.
    const facts = container.querySelector('.workspace__record-facts') as HTMLElement;
    expect(facts).toHaveTextContent('MP4 container only');
    expect(facts).toHaveTextContent('3.0 GiB');
    expect(facts).toHaveTextContent('Processing is queued automatically.');
  });

  it('opens clean and reports a draft only once a value actually differs', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideoImportPage />);
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });

    // §21 puts dirty state in the Context Bar. An untouched form has none.
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument();

    // Reverting to the starting value clears it: dirty is a comparison, not a
    // flag that latches on the first keystroke.
    await user.selectOptions(screen.getByLabelText('Camera'), '');
    await waitFor(() => expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument());
  });

  it('treats the recording time and the file as draft state too', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideoImportPage />);
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });

    const wallTime = screen.getByLabelText('Recording local date/time');
    await user.type(wallTime, '2026-09-14T08:30');
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument();
    await user.clear(wallTime);
    await waitFor(() => expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument());

    const chooser = screen.getByLabelText('MP4 file');
    await user.upload(chooser, new File(['video'], 'source.mp4', { type: 'video/mp4' }));
    expect(await screen.findByText('Unsaved changes')).toBeInTheDocument();
    // The supported clearing path for a file input: a change with no files.
    fireEvent.change(chooser, { target: { files: [] } });
    await waitFor(() => expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument());
  });

  it('does not become dirty merely by refusing an untouched submission', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideoImportPage />);
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });

    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    expect(await screen.findByText('Enter the recording date and time.')).toBeInTheDocument();
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
  });

  it('shows no draft state while the form is not even available', async () => {
    vi.mocked(listCameras).mockResolvedValue([{ ...camera, isActive: false }]);
    renderWithApp(<VideoImportPage />);

    expect(await screen.findByText('No active camera to import against')).toBeInTheDocument();
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
  });

  it('keeps the authoritative camera timezone beside the wall-time field', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideoImportPage />);
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });

    const wallTime = screen.getByLabelText('Recording local date/time');
    // Before a camera is chosen the field still says whose zone will apply.
    expect(document.getElementById(wallTime.getAttribute('aria-describedby') ?? ''))
      .toHaveTextContent(/never the browser/i);

    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    const help = document.getElementById(wallTime.getAttribute('aria-describedby') ?? '');
    expect(help).toHaveTextContent('Asia/Kolkata');
    expect(help).toHaveTextContent('CAM-01');
    expect(help).toHaveTextContent(/browser's timezone is not used/i);
  });

  it('validates each field inline rather than as one page-level alert', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideoImportPage />);
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });

    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    for (const [label, message] of [
      ['Camera', 'Select the camera this recording came from.'],
      ['Recording local date/time', 'Enter the recording date and time.'],
      ['MP4 file', 'An MP4 file is required.'],
    ] as const) {
      const control = screen.getByLabelText(label);
      expect(control).toHaveAttribute('aria-invalid', 'true');
      expect(control.getAttribute('aria-describedby')).toContain(screen.getByText(message).id);
    }
    expect(importVideo).not.toHaveBeenCalled();

    // Correcting a field clears its own message and leaves the others.
    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    expect(screen.queryByText('Select the camera this recording came from.')).not.toBeInTheDocument();
    expect(screen.getByText('An MP4 file is required.')).toBeInTheDocument();
  });

  it('brings the first refused field into view and focuses it, in reading order (§12)', async () => {
    const user = userEvent.setup();
    const scrolled: Element[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) { scrolled.push(this); };
    try {
      renderWithApp(<VideoImportPage />);
      await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
      await user.click(screen.getByRole('button', { name: 'Import and process' }));
      await waitFor(() => expect(screen.getByLabelText('Camera')).toHaveFocus());
      expect(scrolled).toEqual([screen.getByLabelText('Camera')]);

      // Camera chosen: the next refusal goes to the next refused field.
      await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
      await user.click(screen.getByRole('button', { name: 'Import and process' }));
      await waitFor(() => expect(screen.getByLabelText('Recording local date/time')).toHaveFocus());
      expect(scrolled.at(-1)).toBe(screen.getByLabelText('Recording local date/time'));
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it('takes a refused file field to the real file control, visibly (§12, §27 FileInput)', async () => {
    const user = userEvent.setup();
    const scrolled: Element[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) { scrolled.push(this); };
    try {
      renderWithApp(<VideoImportPage />);
      await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
      await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
      await user.type(screen.getByLabelText('Recording local date/time'), '2026-09-14T08:30');
      await user.click(screen.getByRole('button', { name: 'Import and process' }));

      // The file field is the first refused one: focus lands on the native
      // input itself, the control Enter and Space operate, not on a proxy.
      const chooser = screen.getByLabelText('MP4 file');
      await waitFor(() => expect(chooser).toHaveFocus());
      expect(chooser).toHaveAttribute('type', 'file');
      expect(chooser).toHaveAttribute('accept', '.mp4,video/mp4');
      expect(scrolled.at(-1)).toBe(chooser);
      // The frame it lies over is the one that draws the ring and the error.
      const frame = chooser.closest('.file-input') as HTMLElement;
      expect(frame).toHaveAttribute('data-invalid', 'true');
      expect(frame.matches(':focus-within')).toBe(true);
      expect(frame).toHaveTextContent('No file selected');

      // Choosing a file names it on screen and clears the refusal.
      await user.upload(chooser, new File(['video'], 'north-gate-0800.mp4', { type: 'video/mp4' }));
      expect(frame).toHaveTextContent('north-gate-0800.mp4');
      expect(screen.queryByText('An MP4 file is required.')).not.toBeInTheDocument();
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it('blocks the import when there is no active camera, and offers the way out', async () => {
    vi.mocked(listCameras).mockResolvedValue([{ ...camera, isActive: false }]);
    renderWithApp(<VideoImportPage />);

    expect(await screen.findByText('No active camera to import against')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Cameras' })).toHaveAttribute('href', '/cameras');
    // A dead form with an unusable select is exactly what this replaces.
    expect(screen.queryByLabelText('Camera')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Import and process' })).not.toBeInTheDocument();
  });

  it('keeps an unavailable camera inventory distinct from having no active camera', async () => {
    vi.mocked(listCameras).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Camera store unavailable.' }));
    renderWithApp(<VideoImportPage />);

    expect(await screen.findByText(/Camera inventory is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText('No active camera to import against')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('filters inactive cameras and rejects non-MP4 files before upload', async () => {
    const user = userEvent.setup();
    vi.mocked(listCameras).mockResolvedValueOnce([
      camera,
      { ...camera, id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21499', code: 'CAM-OFF', name: 'Inactive', isActive: false },
    ]);
    renderWithApp(<VideoImportPage />);

    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
    expect(screen.queryByRole('option', { name: /CAM-OFF/ })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    await user.type(screen.getByLabelText('Recording local date/time'), '2026-09-14T08:30');
    const nonMp4 = new File(['text'], 'source.txt', { type: 'text/plain' });
    fireEvent.change(screen.getByLabelText('MP4 file'), { target: { files: [nonMp4] } });
    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    expect(await screen.findByText('Select an MP4 file.')).toBeInTheDocument();
    expect(importVideo).not.toHaveBeenCalled();
  });

  it('preserves imported identity when queueing fails and never re-uploads', async () => {
    const user = userEvent.setup();
    vi.mocked(queueProcessing).mockRejectedValueOnce(new ApiError({
      status: 500,
      code: 'processing_queue_failed',
      detail: 'Queue temporarily unavailable.',
    }));
    renderWithApp(<VideoImportPage />);

    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    await user.type(screen.getByLabelText('Recording local date/time'), '2026-09-14T08:30');
    await user.upload(screen.getByLabelText('MP4 file'), new File(['video'], 'source.mp4', { type: 'video/mp4' }));
    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    await waitFor(() => expect(importVideo).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(queueProcessing).toHaveBeenCalledTimes(1));
    expect(importVideo).toHaveBeenCalledTimes(1);
  });

  it('treats processing_already_active as authoritative active work', async () => {
    const user = userEvent.setup();
    vi.mocked(queueProcessing).mockRejectedValueOnce(new ApiError({
      status: 409,
      code: 'processing_already_active',
      detail: 'Processing is already active.',
    }));
    renderWithApp(<VideoImportPage />);

    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    await user.type(screen.getByLabelText('Recording local date/time'), '2026-09-14T08:30');
    await user.upload(screen.getByLabelText('MP4 file'), new File(['video'], 'source.mp4', { type: 'video/mp4' }));
    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    await waitFor(() => expect(queueProcessing).toHaveBeenCalledWith(video.id));
    expect(importVideo).toHaveBeenCalledTimes(1);
  });

  it('fails closed when duplicate reconciliation has no valid video identity', async () => {
    const user = userEvent.setup();
    vi.mocked(importVideo).mockRejectedValueOnce(new ApiError({
      status: 409,
      code: 'video_duplicate',
      detail: 'Video has already been imported.',
    }));
    renderWithApp(<VideoImportPage />);

    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    await user.type(screen.getByLabelText('Recording local date/time'), '2026-09-14T08:30');
    await user.upload(screen.getByLabelText('MP4 file'), new File(['same'], 'source.mp4', { type: 'video/mp4' }));
    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    expect(await screen.findByText(/Video has already been imported.*video_duplicate/)).toBeInTheDocument();
    expect(getProcessingStatus).not.toHaveBeenCalled();
    expect(queueProcessing).not.toHaveBeenCalled();
  });

  it('preserves camera-local datetime and queues the imported video once', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideoImportPage />);

    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    await user.type(screen.getByLabelText('Recording local date/time'), '2026-09-14T08:30');
    const file = new File(['video'], 'source.mp4', { type: 'video/mp4' });
    await user.upload(screen.getByLabelText('MP4 file'), file);
    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    await waitFor(() => expect(importVideo).toHaveBeenCalledWith({
      cameraId: camera.id,
      recordingStartLocal: '2026-09-14T08:30',
      file,
    }));
    await waitFor(() => expect(queueProcessing).toHaveBeenCalledTimes(1));
    expect(queueProcessing).toHaveBeenCalledWith(video.id);
  });

  it('preserves the reconciled video ID when duplicate status lookup fails', async () => {
    vi.mocked(importVideo).mockRejectedValueOnce(new ApiError({
      status: 409,
      code: 'video_duplicate',
      detail: 'Video has already been imported.',
      videoAssetId: video.id,
    }));
    vi.mocked(getProcessingStatus).mockRejectedValueOnce(new ApiError({
      status: 503,
      code: 'processing_status_unavailable',
      detail: 'Processing status is temporarily unavailable.',
    }));

    const outcome = await runImportWorkflow({
      cameraId: camera.id,
      recordingStartLocal: '2026-09-14T08:30',
      file: new File(['same'], 'source.mp4', { type: 'video/mp4' }),
    });

    expect(outcome.videoAssetId).toBe(video.id);
    expect(outcome.recovered).toBe(true);
    expect(outcome.workflowWarning).toMatch(/Existing import recovered.*processing status.*temporarily unavailable/i);
    expect(importVideo).toHaveBeenCalledTimes(1);
    expect(getProcessingStatus).toHaveBeenCalledWith(video.id);
    expect(queueProcessing).not.toHaveBeenCalled();
  });

  it('recovers a committed import whose 201 response was lost without queueing duplicate active work', async () => {
    const user = userEvent.setup();
    vi.mocked(importVideo).mockRejectedValue(new ApiError({
      status: 409,
      code: 'video_duplicate',
      detail: 'Video has already been imported.',
      videoAssetId: video.id,
    }));
    vi.mocked(getProcessingStatus).mockResolvedValue({
      videoStatus: 'Processing',
      latestRun: {
        processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
        status: 'Running',
        pipeline: 'phase1-detection-tracking',
        pipelineVersion: 'phase1-v1',
        workerId: 'worker-a',
        queuedAtUtc: '2026-09-14T03:02:00Z',
        startedAtUtc: '2026-09-14T03:02:02Z',
        completedAtUtc: null,
        progressPercent: 20,
        attemptCount: 1,
        failureCode: null,
        framesProcessed: 0,
        tracksCreated: 0,
        analyticsReadiness: 'NotConfigured',
        phase: 'processing',
      },
    });

    renderWithApp(<VideoImportPage />);
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    await user.type(screen.getByLabelText('Recording local date/time'), '2026-09-14T08:30');
    await user.upload(screen.getByLabelText('MP4 file'), new File(['same'], 'source.mp4', { type: 'video/mp4' }));
    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    await waitFor(() => expect(getProcessingStatus).toHaveBeenCalledWith(video.id));
    expect(queueProcessing).not.toHaveBeenCalled();
  });
});

describe('VideoImportPage — M3 Record conformance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(importVideo).mockResolvedValue(video);
    vi.mocked(queueProcessing).mockResolvedValue({ processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431' });
    vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'NotQueued', latestRun: null });
  });

  /** Camera, wall time and an MP4 in the form, as an operator enters them. */
  async function fill(user: ReturnType<typeof userEvent.setup>) {
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    await user.type(screen.getByLabelText('Recording local date/time'), '2026-09-14T08:30');
    await user.upload(screen.getByLabelText('MP4 file'), new File(['video'], 'source.mp4', { type: 'video/mp4' }));
  }

  it('states the no-active-camera block as the primary region itself, not a card inside the form panel (§11)', async () => {
    vi.mocked(listCameras).mockResolvedValue([{ ...camera, isActive: false }]);
    const { container } = renderWithApp(<VideoImportPage />);
    const block = (await screen.findByText('No active camera to import against')).closest('.empty--hatched') as HTMLElement;
    expect(block).not.toBeNull();
    // No panel round it, and no "New import" panel with nothing to hold.
    expect(block.closest('.panel')).toBeNull();
    expect(within(container).queryByRole('heading', { name: 'New import' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Cameras' })).toHaveAttribute('href', '/cameras');
  });

  it('keeps an unavailable or loading inventory inside the form panel it replaces (§37.1, panel)', async () => {
    vi.mocked(listCameras).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Camera store unavailable.' }));
    renderWithApp(<VideoImportPage />);
    const alert = (await screen.findByText(/Camera inventory is unavailable/)).closest('.alert') as HTMLElement;
    expect(alert.closest('.panel')).toHaveTextContent('New import');
  });

  it('says a selected camera a refresh no longer lists is gone, keeps the draft, and imports nothing until another is chosen (§21)', async () => {
    const user = userEvent.setup();
    const other = { ...camera, id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21499', code: 'CAM-02', name: 'South Dock' };
    vi.mocked(listCameras).mockResolvedValue([camera, other]);
    const { queryClient } = renderWithApp(<VideoImportPage />);
    await fill(user);

    // A background refresh: CAM-01 has been deactivated meanwhile.
    vi.mocked(listCameras).mockResolvedValue([{ ...camera, isActive: false }, other]);
    await queryClient.refetchQueries({ queryKey: queryKeys.cameras });
    expect(await screen.findByText('The selected camera is no longer active. Select another.')).toBeInTheDocument();
    expect(screen.getByLabelText('Camera')).toHaveAttribute('aria-invalid', 'true');
    // The rest of the draft is intact, and still a draft.
    expect(screen.getByLabelText('Recording local date/time')).toHaveValue('2026-09-14T08:30');
    expect(screen.getByText('source.mp4')).toBeInTheDocument();
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Import and process' }));
    expect(importVideo).not.toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText('Camera'), other.id);
    expect(screen.queryByText(/no longer active/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Import and process' }));
    await waitFor(() => expect(importVideo).toHaveBeenCalledWith(expect.objectContaining({ cameraId: other.id })));
  });

  it('keeps a withdrawn camera refused when a later refresh fails over the newer inventory (degraded, Codex P2)', async () => {
    const user = userEvent.setup();
    const other = { ...camera, id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21499', code: 'CAM-02', name: 'South Dock' };
    vi.mocked(listCameras).mockResolvedValue([camera, other]);
    const { queryClient } = renderWithApp(<VideoImportPage />);
    await fill(user);

    // A refresh withdraws CAM-01; the next one fails, keeping that newer list.
    vi.mocked(listCameras).mockResolvedValue([{ ...camera, isActive: false }, other]);
    await queryClient.refetchQueries({ queryKey: queryKeys.cameras });
    await screen.findByText('The selected camera is no longer active. Select another.');
    vi.mocked(listCameras).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Camera store unavailable.' }));
    await queryClient.refetchQueries({ queryKey: queryKeys.cameras }).catch(() => undefined);
    expect(await screen.findByText('Showing the last known camera inventory; refreshing failed.', {}, { timeout: 4000 })).toBeInTheDocument();

    // Still withdrawn, still refused.
    expect(screen.getByText('The selected camera is no longer active. Select another.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Import and process' }));
    expect(importVideo).not.toHaveBeenCalled();
  });

  it('keeps the no-active-camera block at depth one when a refresh fails over it (degraded, §11)', async () => {
    vi.mocked(listCameras).mockResolvedValue([{ ...camera, isActive: false }]);
    const { queryClient } = renderWithApp(<VideoImportPage />);
    await screen.findByText('No active camera to import against');
    vi.mocked(listCameras).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Camera store unavailable.' }));
    await queryClient.refetchQueries({ queryKey: queryKeys.cameras }).catch(() => undefined);
    expect(await screen.findByText('Showing the last known camera inventory; refreshing failed.', {}, { timeout: 4000 })).toBeInTheDocument();
    const block = screen.getByText('No active camera to import against').closest('.empty--hatched') as HTMLElement;
    expect(block.closest('.panel')).toBeNull();
  });

  it('states each fact once: the timezone beside its field, the file limits in the rail (§24, §30)', async () => {
    const user = userEvent.setup();
    renderWithApp(<VideoImportPage />);
    await screen.findByRole('option', { name: 'CAM-01 — North Gate' });
    await user.selectOptions(screen.getByLabelText('Camera'), camera.id);
    // The operative zone is the wall-time field's help, and only there.
    expect(screen.getAllByText('Asia/Kolkata')).toHaveLength(1);
    expect(screen.queryByText('Recording timezone')).not.toBeInTheDocument();
    // The limits are the rail's, stated once.
    const rail = screen.getByRole('heading', { name: 'Before you import' }).closest('section') as HTMLElement;
    expect(within(rail).getByText('Maximum size').nextElementSibling).toHaveTextContent('3.0 GiB');
    expect(screen.getAllByText(/3\.0 GiB/)).toHaveLength(1);
    expect(screen.queryByText(/Backend media validation/)).not.toBeInTheDocument();
  });

  it('names what failed for a refusal it has no words of its own for, once, and keeps the draft', async () => {
    const user = userEvent.setup();
    vi.mocked(importVideo).mockRejectedValue(new ApiError({ status: 503, code: 'media_store_unavailable', detail: 'The media store did not respond.' }));
    renderWithApp(<VideoImportPage />);
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    const alert = await screen.findByText('The video could not be imported. The media store did not respond. (media_store_unavailable)');
    expect(screen.getAllByText(/media store did not respond/)).toEqual([alert]);
    expect(screen.getByLabelText('Camera')).toHaveValue(camera.id);
    expect(screen.getByLabelText('Recording local date/time')).toHaveValue('2026-09-14T08:30');
    expect(screen.getByText('source.mp4')).toBeInTheDocument();
  });

  it('starts one import however often submit is pressed while it is pending', async () => {
    const user = userEvent.setup();
    let resolve: (value: typeof video) => void = () => {};
    vi.mocked(importVideo).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    renderWithApp(<VideoImportPage />);
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Import and process' }));

    const pending = screen.getByRole('button', { name: 'Importing and queueing…' });
    expect(pending).toBeDisabled();
    // Enter in a field submits the form too; the pending import refuses it.
    await user.type(screen.getByLabelText('Recording local date/time'), '{Enter}');
    expect(importVideo).toHaveBeenCalledTimes(1);
    resolve(video);
    await waitFor(() => expect(queueProcessing).toHaveBeenCalledTimes(1));
  });
});
