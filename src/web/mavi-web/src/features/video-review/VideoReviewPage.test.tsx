import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getSystemConfig } from '../../api/system';
import { getTrack, type TrackDetail } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import { renderWithApp } from '../../test/renderWithApp';
import { notConfiguredAnalytics } from '../../test/analyticsFixtures';
import {
  DISAGREEING_REPRESENTATIVE,
  evidenceObservation,
  evidenceSet,
  FULL_EVIDENCE_SET_ROLES,
  trackEvidence,
} from '../../test/trackEvidenceFixtures';
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
const secondTrackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21452';
const secondVideoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21422';

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
    // A historical v2 Track: one Representative, its crop a Thumbnail artifact.
    ...trackEvidence([evidenceObservation('Representative', 0, {
      observationId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21461',
      sourceFrameNumber: 4935,
      videoOffsetMs: 197_420,
      timestampUtc: '2026-09-14T02:30:00Z',
      confidence: 0.96,
      qualityScore: 0.93,
      selectionScore: 0.93,
      boundingBox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
      evidenceArtifactId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21441',
      evidenceContentUrl: '/api/artifacts/018f3f5a-2f70-7a2b-8a12-2d02f4c21441/content',
    })]),
    trajectoryArtifactId: null,
    trajectoryContentUrl: null,
    analytics: notConfiguredAnalytics(),
    ...overrides,
  };
}

function ReviewNavigationHarness() {
  const navigate = useNavigate();
  return (
    <>
      <button
        type="button"
        onClick={() => navigate('/review/video/' + videoId + '?trackId=' + secondTrackId)}
      >
        Next Track
      </button>
      <VideoReviewPage />
    </>
  );
}

function DifferentVideoNavigationHarness() {
  const navigate = useNavigate();
  return (
    <>
      <button
        type="button"
        onClick={() => navigate('/review/video/' + secondVideoId + '?trackId=' + secondTrackId)}
      >
        Different Video
      </button>
      <VideoReviewPage />
    </>
  );
}

describe('VideoReviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(getTrack).mockResolvedValue(detail());
  });

  it('reconstructs a cold review route and seeks one second before Track start', async () => {
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    const video = await screen.findByLabelText(/source video evidence$/);
    Object.defineProperty(video, 'duration', { configurable: true, value: 600 });
    fireEvent.loadedMetadata(video);

    expect((video as HTMLVideoElement).currentTime).toBeCloseTo(196.420, 3);
    (video as HTMLVideoElement).currentTime = 200;
    fireEvent.loadedMetadata(video);
    expect((video as HTMLVideoElement).currentTime).toBe(200);

    expect(video).toHaveAttribute('src', '/api/videos/' + videoId + '/content');
    expect(screen.getByText(/CAM-01.*North Gate/)).toBeInTheDocument();
    expect(screen.getByText(/08:00:00/)).toBeInTheDocument();
  });

  describe('the Evidence Set in the evidence rail', () => {
    function renderReview(track: TrackDetail) {
      vi.mocked(getTrack).mockResolvedValue(track);
      return renderWithApp(<VideoReviewPage />, {
        route: '/review/video/' + videoId + '?trackId=' + trackId,
        routePath: '/review/video/:videoAssetId',
      });
    }

    const fourRole = () => detail(trackEvidence(evidenceSet(FULL_EVIDENCE_SET_ROLES)));

    it('sits in the rail after the primary summary, never under the player', async () => {
      const { container } = renderReview(fourRole());
      const set = await screen.findByRole('region', { name: 'Evidence Set' });

      expect(set.closest('.workspace__review-rail')).not.toBeNull();
      expect(set.closest('.workspace__review-main')).toBeNull();
      expect(container.querySelector('.workspace__player')?.contains(set)).toBe(false);

      // Section 4.5.1: the primary summary still leads the rail.
      const rail = container.querySelector('.workspace__review-rail')!;
      const headings = within(rail as HTMLElement).getAllByRole('heading').map((heading) => heading.textContent);
      expect(headings.indexOf('Track summary')).toBe(0);
      expect(headings.indexOf('Evidence Set')).toBeGreaterThan(headings.indexOf('Track summary'));
      expect(headings.indexOf('Evidence Set')).toBeLessThan(headings.indexOf('Processing provenance'));
    });

    it('replaces the old Representative panel, so the Representative crop has one surface', async () => {
      const { container } = renderReview(fourRole());
      const set = await screen.findByRole('region', { name: 'Evidence Set' });

      expect(screen.queryByRole('heading', { name: 'Representative evidence' })).not.toBeInTheDocument();
      expect(screen.queryByText('Representative evidence unavailable')).not.toBeInTheDocument();
      expect(screen.getAllByRole('region', { name: 'Evidence Set' })).toHaveLength(1);

      // Every image of the Representative crop is inside the one Evidence Set,
      // and the strip carries it once.
      const url = evidenceSet(['Representative'])[0].evidenceContentUrl!;
      const images = [...container.querySelectorAll('img')].filter((img) => img.getAttribute('src') === url);
      expect(images.length).toBeGreaterThan(0);
      expect(images.every((img) => set.contains(img))).toBe(true);
      const strip = within(set).getByRole('list', { name: 'Evidence Set observations' });
      expect(within(strip).getAllByRole('img').filter((img) => img.getAttribute('src') === url)).toHaveLength(1);

      expect(container.querySelectorAll('video')).toHaveLength(1);
    });

    it('keeps the Track identity beside it, following rank 0', async () => {
      renderReview(detail({ ...trackEvidence(evidenceSet(FULL_EVIDENCE_SET_ROLES)), representative: DISAGREEING_REPRESENTATIVE }));
      await screen.findByRole('region', { name: 'Evidence Set' });

      expect(screen.getByText('Source frame').nextElementSibling).toHaveTextContent('300');
      expect(screen.getByText('Video offset').nextElementSibling).toHaveTextContent('00:12.0');
      expect(screen.queryByText('9999')).not.toBeInTheDocument();
    });

    it('reads the legacy shape without an error', async () => {
      renderReview(detail({ representative: null, observations: [] }));

      expect(await screen.findByText('No Evidence Set was persisted for this Track.')).toBeInTheDocument();
      expect(screen.queryByText('Source frame')).not.toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  it('rejects malformed route video and missing Track identity without API calls', async () => {
    const invalidVideo = renderWithApp(<VideoReviewPage />, {
      route: '/review/video/not-a-guid?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    expect(await screen.findByText(/video identifier.*invalid/i)).toBeInTheDocument();
    expect(getTrack).not.toHaveBeenCalled();
    expect(getSystemConfig).not.toHaveBeenCalled();
    invalidVideo.unmount();

    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId,
      routePath: '/review/video/:videoAssetId',
    });

    expect(await screen.findByText(/Exactly one valid Track identifier/i)).toBeInTheDocument();
    expect(getTrack).not.toHaveBeenCalled();
    expect(getSystemConfig).not.toHaveBeenCalled();
  });

  it('canonicalizes uppercase Review identities before querying and cache ownership', async () => {
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId.toUpperCase() + '?trackId=' + trackId.toUpperCase(),
      routePath: '/review/video/:videoAssetId',
    });

    await screen.findByLabelText(/source video evidence$/);
    expect(getTrack).toHaveBeenCalledWith(trackId, expect.any(AbortSignal), undefined);
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
    expect(screen.queryByLabelText(/source video evidence$/)).not.toBeInTheDocument();
  });

  it('reseeks immediately when another Track on the same video is already cached', async () => {
    const user = userEvent.setup();
    const second = detail({
      id: secondTrackId,
      startOffsetMs: 300_000,
    });
    vi.mocked(getTrack).mockImplementation(async (id) => id === secondTrackId ? second : detail());

    const view = renderWithApp(<ReviewNavigationHarness />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    const video = await screen.findByLabelText(/source video evidence$/);
    Object.defineProperty(video, 'duration', { configurable: true, value: 600 });
    Object.defineProperty(video, 'readyState', { configurable: true, value: HTMLMediaElement.HAVE_METADATA });
    (video as HTMLVideoElement).currentTime = 196.420;

    view.queryClient.setQueryData(queryKeys.track(secondTrackId), second);
    await user.click(screen.getByRole('button', { name: 'Next Track' }));

    await waitFor(() => expect((screen.getByLabelText(/source video evidence$/) as HTMLVideoElement).currentTime)
      .toBeCloseTo(299, 3));
  });

  it('recovers configured-zone timestamp presentation after a display-config outage', async () => {
    const user = userEvent.setup();
    vi.mocked(getSystemConfig).mockRejectedValueOnce(new Error('offline'));

    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    expect(await screen.findByRole('button', { name: 'Retry display config' })).toBeInTheDocument();
    expect(screen.getAllByText(/2026-09-14T02:30:00Z UTC/).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Retry display config' }));

    expect(await screen.findByText(/08:00:00/)).toBeInTheDocument();
  });

  it('shows graceful evidence fallbacks when thumbnail or video content fails', async () => {
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    // A failed crop keeps its Observation: role and offset stay, the image is
    // stated unavailable, and the video is unaffected until it fails itself.
    const crop = await screen.findByRole('img', { name: 'Representative · 03:17.4 evidence crop' });
    fireEvent.error(crop);
    expect(screen.getByText('Evidence image unavailable.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Representative · 03:17.4, evidence image unavailable' })).toBeInTheDocument();
    expect(screen.queryByText(/Source video could not be loaded/i)).not.toBeInTheDocument();

    const video = screen.getByLabelText(/source video evidence$/);
    fireEvent.error(video);
    expect(screen.getByText(/Source video could not be loaded/i)).toBeInTheDocument();
  });

  it('reconstructs a replacement route when navigation changes to another video', async () => {
    const user = userEvent.setup();
    const second = detail({
      id: secondTrackId,
      videoAssetId: secondVideoId,
      startOffsetMs: 42_000,
      video: {
        ...detail().video,
        videoContentUrl: '/api/videos/' + secondVideoId + '/content',
      },
    });
    vi.mocked(getTrack).mockImplementation(async (id) => id === secondTrackId ? second : detail());

    renderWithApp(<DifferentVideoNavigationHarness />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });

    expect(await screen.findByLabelText(/source video evidence$/))
      .toHaveAttribute('src', '/api/videos/' + videoId + '/content');

    await user.click(screen.getByRole('button', { name: 'Different Video' }));

    await waitFor(() => expect(screen.getByLabelText(/source video evidence$/))
      .toHaveAttribute('src', '/api/videos/' + secondVideoId + '/content'));
    expect(getTrack).toHaveBeenCalledWith(secondTrackId, expect.any(AbortSignal), undefined);
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

  describe('analytic identity (Slice 4)', () => {
    const revision = '018f3f5a-2f70-7a2b-8a12-2d02f4c21481';

    function review(query: string) {
      return renderWithApp(<VideoReviewPage />, {
        route: '/review/video/' + videoId + '?trackId=' + trackId + query,
        routePath: '/review/video/:videoAssetId',
      });
    }

    // A link that carries no identity is an ordinary direct link, and the server
    // legitimately answers it with the current revision and engine.
    it('reads a link with no identity against the current analytics', async () => {
      review('');
      await screen.findByLabelText(/source video evidence$/);
      expect(getTrack).toHaveBeenCalledWith(trackId, expect.any(AbortSignal), undefined);
    });

    it('reads the Track against the complete identity the link carries', async () => {
      review('&sceneRevisionId=' + revision.toUpperCase() + '&analyticsAlgorithmVersion=scene-analytics-v1');
      await screen.findByLabelText(/source video evidence$/);
      expect(getTrack).toHaveBeenCalledWith(trackId, expect.any(AbortSignal), {
        sceneRevisionId: revision, analyticsAlgorithmVersion: 'scene-analytics-v1',
      });
    });

    // A revision without an engine is a whole request, not half of one: the API
    // reads that revision with the current engine.
    it('accepts a revision with no engine version', async () => {
      review('&sceneRevisionId=' + revision);
      await screen.findByLabelText(/source video evidence$/);
      expect(getTrack).toHaveBeenCalledWith(trackId, expect.any(AbortSignal), {
        sceneRevisionId: revision, analyticsAlgorithmVersion: undefined,
      });
    });

    // A link that claims an identity has said which evidence it refers to. If
    // that claim cannot be read, answering with current analytics would show
    // something the link does not name, and a historical link would stop being
    // reproducible — so the link is refused and nothing is requested.
    it.each([
      ['a malformed revision', '&sceneRevisionId=not-a-guid'],
      ['duplicate revisions', '&sceneRevisionId=' + revision + '&sceneRevisionId=' + revision],
      ['duplicate engine versions', '&sceneRevisionId=' + revision + '&analyticsAlgorithmVersion=scene-analytics-v1&analyticsAlgorithmVersion=scene-analytics-v2'],
      ['a malformed engine version', '&sceneRevisionId=' + revision + '&analyticsAlgorithmVersion=v1'],
      ['an engine version with no revision', '&analyticsAlgorithmVersion=scene-analytics-v1'],
      ['a blank revision', '&sceneRevisionId='],
    ])('refuses a link carrying %s and asks the server for nothing', async (_case, query) => {
      review(query);

      expect(await screen.findByText(/names an invalid analytics identity/)).toBeInTheDocument();
      expect(screen.queryByLabelText(/source video evidence$/)).not.toBeInTheDocument();
      await waitFor(() => expect(getTrack).not.toHaveBeenCalled());
    });
  });

  describe('return navigation', () => {
    it('returns to the exact committed search context carried in the route', async () => {
      const from = 'cameraId=018f3f5a-2f70-7a2b-8a12-2d02f4c21412&objectClass=Person&track=' + trackId;
      renderWithApp(<VideoReviewPage />, {
        route: '/review/video/' + videoId + '?trackId=' + trackId + '&from=' + encodeURIComponent(from),
        routePath: '/review/video/:videoAssetId',
      });
      await screen.findByLabelText(/source video evidence$/);
      expect(screen.getByRole('link', { name: 'Back to search' })).toHaveAttribute('href', '/search?' + from);
    });

    it('falls back to the video scope on a direct link or refresh without a search context', async () => {
      renderWithApp(<VideoReviewPage />, {
        route: '/review/video/' + videoId + '?trackId=' + trackId,
        routePath: '/review/video/:videoAssetId',
      });
      await screen.findByLabelText(/source video evidence$/);
      expect(screen.getByRole('link', { name: 'Back to search' }))
        .toHaveAttribute('href', '/search?videoAssetId=' + videoId + '&track=' + trackId);
    });

    it('rejects a malformed or foreign search context and uses the fallback', async () => {
      const bogus = encodeURIComponent('objectClass=Person&objectClass=Vehicle&evil=1');
      renderWithApp(<VideoReviewPage />, {
        route: '/review/video/' + videoId + '?trackId=' + trackId + '&from=' + bogus,
        routePath: '/review/video/:videoAssetId',
      });
      await screen.findByLabelText(/source video evidence$/);
      expect(screen.getByRole('link', { name: 'Back to search' }))
        .toHaveAttribute('href', '/search?videoAssetId=' + videoId + '&track=' + trackId);
    });
  });
});
