import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getSystemConfig } from '../../api/system';
import { getTrack, type TrackDetail } from '../../api/tracks';
import { renderWithApp } from '../../test/renderWithApp';
import VideoReviewPage from './VideoReviewPage';

vi.mock('../../api/system', () => ({
  getSystemConfig: vi.fn(),
}));

vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return {
    ...actual,
    getTrack: vi.fn(),
  };
});

const videoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';
const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21451';

function detail(overrides: Partial<TrackDetail> = {}): TrackDetail {
  return {
    id: trackId,
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
    videoAssetId: videoId,
    camera: {
      id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412',
      code: 'CAM-01',
      name: 'North Gate',
    },
    objectClass: 'Person',
    localTrackNumber: 7,
    startOffsetMs: 197_420,
    endOffsetMs: 205_000,
    startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:08Z',
    durationMs: 7_580,
    detectionCount: 42,
    meanConfidence: 0.91,
    maxConfidence: 0.98,
    reviewStatus: 'Unreviewed',
    processing: {
      pipelineVersion: 'phase1',
      detectorName: 'RTMDet',
      detectorVersion: '1',
      trackerName: 'ByteTrack',
      trackerVersion: '1',
      completedAtUtc: '2026-09-14T02:40:00Z',
    },
    video: {
      recordingStartUtc: '2026-09-14T02:26:42Z',
      recordingEndUtc: '2026-09-14T02:36:42Z',
      durationMs: 600_000,
      width: 1920,
      height: 1080,
      frameRateNumerator: 25,
      frameRateDenominator: 1,
      videoContentUrl: '/api/videos/' + videoId + '/content',
    },
    representative: {
      observationId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21461',
      sourceFrameNumber: 4935,
      videoOffsetMs: 197_420,
      timestampUtc: '2026-09-14T02:30:00Z',
      confidence: 0.96,
      qualityScore: 0.93,
      boundingBox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
      thumbnailArtifactId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21441',
      thumbnailContentUrl: '/api/artifacts/018f3f5a-2f70-7a2b-8a12-2d02f4c21441/content',
    },
    trajectoryArtifactId: null,
    trajectoryContentUrl: null,
    ...overrides,
  };
}

describe('VideoReviewPage', () => {
  beforeEach(() => {
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(getTrack).mockResolvedValue(detail());
  });

  it('reconstructs a cold review route and seeks one second before Track start', async () => {
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    const video = await screen.findByLabelText('Source video evidence');
    Object.defineProperty(video, 'duration', { configurable: true, value: 600 });
    fireEvent.loadedMetadata(video);

    expect((video as HTMLVideoElement).currentTime).toBeCloseTo(196.420, 3);
    expect(video).toHaveAttribute('src', '/api/videos/' + videoId + '/content');
    expect(screen.getByText('North Gate')).toBeInTheDocument();
    expect(screen.getByText(/08:00:00/)).toBeInTheDocument();
  });

  it('rejects duplicated trackId query parameters without issuing a Track request', async () => {
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId + '&trackId=018f3f5a-2f70-7a2b-8a12-2d02f4c21452',
      routePath: '/review/video/:videoAssetId',
    });

    expect(await screen.findByText(/Exactly one valid Track identifier/i)).toBeInTheDocument();
    expect(getTrack).not.toHaveBeenCalled();
  });

  it('fails closed when route video and Track video identities differ', async () => {
    vi.mocked(getTrack).mockResolvedValueOnce(detail({
      videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21422',
    }));

    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    expect(await screen.findByText(/does not belong to the video/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Source video evidence')).not.toBeInTheDocument();
  });

  it('surfaces Track not found without retrying the stable 404', async () => {
    const { ApiError } = await import('../../api/client');
    vi.mocked(getTrack).mockRejectedValueOnce(new ApiError({
      status: 404,
      code: 'track_not_found',
      detail: 'Track was not found.',
    }));

    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    expect(await screen.findByText('Track was not found.')).toBeInTheDocument();
    await waitFor(() => expect(getTrack).toHaveBeenCalledTimes(1));
  });
});
