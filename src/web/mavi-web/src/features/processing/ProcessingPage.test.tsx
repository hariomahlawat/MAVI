import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getCamera } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
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
      },
    });
    vi.mocked(queueProcessing).mockResolvedValue({ processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21432' });
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
});
