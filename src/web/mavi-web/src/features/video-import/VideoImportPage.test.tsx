import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getProcessingStatus, importVideo, queueProcessing } from '../../api/videos';
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
