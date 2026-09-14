import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getProcessingStatus, importVideo, queueProcessing } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import VideoImportPage from './VideoImportPage';

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
