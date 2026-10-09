import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getSystemConfig } from '../../api/system';
import { getTrack, type TrackDetail } from '../../api/tracks';
import { getVideo, type VideoAsset } from '../../api/videos';
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

vi.mock('../../api/videos', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/videos')>();
  return { ...actual, getVideo: vi.fn() };
});

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
    vi.mocked(getVideo).mockResolvedValue({ id: videoId, originalFileName: 'north-gate-0800.mp4' } as VideoAsset);
  });

  it('is crumbed under Search, names its video, and states the Track beside its review status (§5)', async () => {
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });
    await screen.findByLabelText(/source video evidence$/);
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    await waitFor(() => expect(within(crumbs).getByText('north-gate-0800.mp4')).toBeInTheDocument());
    expect(within(crumbs).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['Search', 'north-gate-0800.mp4', 'Review']);
    expect(within(crumbs).getByText('Review')).toHaveAttribute('aria-current', 'page');
    // One way back, not two controls for one destination.
    expect(screen.queryByRole('link', { name: 'Visual Search' })).not.toBeInTheDocument();
    expect(screen.getByText(/· Track \d+$/)).toBeInTheDocument();
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

    it('keeps the record\'s identifiers out of the operational tier, one closed disclosure away (F18)', async () => {
      const subject = detail({ ...trackEvidence(evidenceSet(FULL_EVIDENCE_SET_ROLES)), representative: DISAGREEING_REPRESENTATIVE });
      renderReview(subject);
      const set = await screen.findByRole('region', { name: 'Evidence Set' });
      const rail = set.closest('.workspace__review-rail') as HTMLElement;

      // Rank 0's frame and time are its caption; the compatibility object's are nowhere.
      expect(within(set).getByText('Frame 300')).toBeInTheDocument();
      expect(screen.queryByText('9999')).not.toBeInTheDocument();
      // The Track number and status are the Context Bar's, and not repeated.
      expect(rail).not.toHaveTextContent(/Local track/);
      expect(rail).not.toHaveTextContent(/Review status/);

      // The full identifiers sit only in the closed Record detail disclosure.
      const record = within(rail).getByText('Record detail').closest('details')!;
      expect(record).not.toHaveAttribute('open');
      for (const id of [subject.id, subject.processingRunId]) {
        expect(within(record).getByText(id)).toBeInTheDocument();
        const outside = Array.from(rail.querySelectorAll('*'))
          .filter((element) => !record.contains(element) && element.children.length === 0)
          .map((element) => element.textContent ?? '').join(' ');
        expect(outside).not.toContain(id);
      }
    });

    it('says what each rail panel holds by its title alone (F19)', async () => {
      renderReview(detail({ ...trackEvidence(evidenceSet(FULL_EVIDENCE_SET_ROLES)) }));
      const set = await screen.findByRole('region', { name: 'Evidence Set' });
      const rail = set.closest('.workspace__review-rail') as HTMLElement;
      expect(rail.querySelectorAll('.panel__title p')).toHaveLength(0);
      for (const prose of ['persisted evidence', 'rank order, and the stable Track identity', 'Which pipeline']) {
        expect(rail).not.toHaveTextContent(prose);
      }
    });

    it('reads the legacy shape without an error', async () => {
      renderReview(detail({ representative: null, observations: [] }));

      expect(await screen.findByText('No Evidence Set was persisted for this Track.')).toBeInTheDocument();
      expect(screen.queryByText('Representative quality')).not.toBeInTheDocument();
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
    // §24: no configured zone is claimed while the configuration is unavailable;
    // the times say UTC themselves and the notice says why.
    await screen.findByRole('heading', { name: 'Track summary' });
    const bar = document.querySelector('.context-bar') as HTMLElement;
    expect(within(bar).queryByText(/Times shown in/)).not.toBeInTheDocument();
    expect(screen.queryByText('Asia/Kolkata')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry display config' }));

    expect(await screen.findByText(/08:00:00/)).toBeInTheDocument();
    expect(within(bar).getByText('Asia/Kolkata')).toBeInTheDocument();
  });

  it('states the configured timezone once, in the Context Bar, and in no panel (§24)', async () => {
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });
    const summary = (await screen.findByRole('heading', { name: 'Track summary' })).closest('section') as HTMLElement;
    const bar = document.querySelector('.context-bar') as HTMLElement;
    // Beside the Track identity and its review status.
    await waitFor(() => expect(within(bar).getByText('Asia/Kolkata')).toBeInTheDocument());
    expect(bar).toHaveTextContent(/Track \d+/);
    expect(within(bar).getByText('Times shown in')).toBeInTheDocument();
    // Once on the surface: not as a row in Record detail or any other panel.
    expect(screen.getAllByText('Asia/Kolkata')).toHaveLength(1);
    expect(screen.queryByText('Display timezone')).not.toBeInTheDocument();
    // And the absolute times are read in that zone (02:30:00Z is 08:00:00 IST).
    expect(within(summary).getByText('Track start').nextElementSibling).toHaveTextContent('14 Sept 2026, 08:00:00');
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
    expect(screen.getByRole('img', { name: /^No image: the evidence image could not be loaded/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Representative · 03:17.4, no image' })).toBeInTheDocument();
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

  it('keeps every terminal Review state under Search, with the way back to its Investigation (§5)', async () => {
    const { ApiError } = await import('../../api/client');
    vi.mocked(getTrack).mockRejectedValueOnce(new ApiError({ status: 404, code: 'track_not_found', detail: 'Track was not found.' }));
    const from = 'cameraId=018f3f5a-2f70-7a2b-8a12-2d02f4c21412&objectClass=Person&track=' + trackId;
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId + '&from=' + encodeURIComponent(from),
      routePath: '/review/video/:videoAssetId',
    });
    expect(await screen.findByText('Track was not found.')).toBeInTheDocument();
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByRole('link', { name: 'Search' })).toHaveAttribute('href', '/search?' + from);
    expect(within(crumbs).getByText('Review')).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByText('Evidence Review')).not.toBeInTheDocument();
  });

  it('names the video by its identifier when its name cannot be read, never by a generic word (§14)', async () => {
    vi.mocked(getVideo).mockRejectedValue(new Error('offline'));
    renderWithApp(<VideoReviewPage />, {
      route: '/review/video/' + videoId + '?trackId=' + trackId,
      routePath: '/review/video/:videoAssetId',
    });
    await screen.findByLabelText(/source video evidence$/);
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    await waitFor(() => expect(within(crumbs).getByText(`Video ${videoId.slice(0, 8)}…`)).toBeInTheDocument());
  });

  describe('video identity in every Review state (§5, §14)', () => {
    const fallback = `Video ${videoId.slice(0, 8)}…`;
    const from = 'cameraId=018f3f5a-2f70-7a2b-8a12-2d02f4c21412&objectClass=Person&track=' + trackId;
    const renderInShell = (route: string) => renderWithApp(<VideoReviewPage />, {
      route,
      routePath: '/review/video/:videoAssetId',
      shell: 'review',
    });

    /** `Search › {identity} › Review`, the root returning to `rootTo`, the title the same trail. */
    async function expectVideoIdentity(identity: string, rootTo?: string) {
      const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
      const root = within(crumbs).getByRole('link', { name: 'Search' });
      if (rootTo) expect(root).toHaveAttribute('href', rootTo);
      expect(await within(crumbs).findByText(identity)).toBeInTheDocument();
      expect(within(crumbs).getByText('Review')).toHaveAttribute('aria-current', 'page');
      expect(within(crumbs).getAllByRole('listitem')).toHaveLength(3);
      expect(crumbs.textContent).not.toContain(videoId);
      await waitFor(() => expect(document.title).toBe(`Review — ${identity} — Search — MAVI`));
    }

    it.each([
      ['no single Track', '', /Exactly one valid Track identifier/, '/search'],
      ['an invalid analytics identity', '?trackId=' + trackId + '&sceneRevisionId=not-a-guid&from=' + encodeURIComponent(from), /names an invalid analytics identity/, '/search?' + from],
      ['a missing Track', '?trackId=' + trackId + '&from=' + encodeURIComponent(from), /Track was not found\./, '/search?' + from],
      ['a Track of another video', '?trackId=' + trackId + '&from=' + encodeURIComponent(from), /does not belong to the video/, '/search?' + from],
    ])('names the video the route names when the state is %s', async (name, query, message, rootTo) => {
      vi.mocked(getVideo).mockImplementation(() => new Promise(() => {}));
      const { ApiError } = await import('../../api/client');
      if (name === 'a missing Track') {
        vi.mocked(getTrack).mockRejectedValueOnce(new ApiError({ status: 404, code: 'track_not_found', detail: 'Track was not found.' }));
      }
      if (name === 'a Track of another video') {
        vi.mocked(getTrack).mockResolvedValueOnce(detail({ videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21422' }));
      }
      renderInShell('/review/video/' + videoId + query);

      expect(await screen.findByText(message)).toBeInTheDocument();
      await expectVideoIdentity(fallback, rootTo);
    });

    it('names the video by its file name in a terminal state once it is read', async () => {
      const { ApiError } = await import('../../api/client');
      vi.mocked(getTrack).mockRejectedValueOnce(new ApiError({ status: 404, code: 'track_not_found', detail: 'Track was not found.' }));
      renderInShell('/review/video/' + videoId + '?trackId=' + trackId + '&from=' + encodeURIComponent(from));

      expect(await screen.findByText('Track was not found.')).toBeInTheDocument();
      await expectVideoIdentity('north-gate-0800.mp4', '/search?' + from);
    });

    it('names the video by its identifier while its record loads, not by a bare `Video`', async () => {
      vi.mocked(getVideo).mockImplementation(() => new Promise(() => {}));
      renderInShell('/review/video/' + videoId + '?trackId=' + trackId);

      await screen.findByLabelText(/source video evidence$/);
      await expectVideoIdentity(fallback);
      expect(within(screen.getByRole('navigation', { name: 'Breadcrumb' })).queryByText('Video')).not.toBeInTheDocument();
    });

    it('invents no video for a route whose video identifier is not one', async () => {
      renderInShell('/review/video/not-a-guid?trackId=' + trackId);

      expect(await screen.findByText(/video identifier.*invalid/i)).toBeInTheDocument();
      const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
      expect(within(crumbs).getByRole('link', { name: 'Search' })).toHaveAttribute('href', '/search');
      expect(within(crumbs).getAllByRole('listitem')).toHaveLength(2);
      await waitFor(() => expect(document.title).toBe('Review — Search — MAVI'));
      expect(getVideo).not.toHaveBeenCalled();
    });
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
      // Review belongs to Search (§5): its root crumb is the way back, with
      // the Investigation's URL state intact.
      const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
      expect(within(crumbs).getByRole('link', { name: 'Search' })).toHaveAttribute('href', '/search?' + from);
      expect(screen.queryByRole('link', { name: 'Back to search' })).not.toBeInTheDocument();
    });

    it('falls back to the video scope on a direct link or refresh without a search context', async () => {
      renderWithApp(<VideoReviewPage />, {
        route: '/review/video/' + videoId + '?trackId=' + trackId,
        routePath: '/review/video/:videoAssetId',
      });
      await screen.findByLabelText(/source video evidence$/);
      const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
      expect(within(crumbs).getByRole('link', { name: 'Search' }))
        .toHaveAttribute('href', '/search?videoAssetId=' + videoId + '&track=' + trackId);
    });

    it('rejects a malformed or foreign search context and uses the fallback', async () => {
      const bogus = encodeURIComponent('objectClass=Person&objectClass=Vehicle&evil=1');
      renderWithApp(<VideoReviewPage />, {
        route: '/review/video/' + videoId + '?trackId=' + trackId + '&from=' + bogus,
        routePath: '/review/video/:videoAssetId',
      });
      await screen.findByLabelText(/source video evidence$/);
      const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
      expect(within(crumbs).getByRole('link', { name: 'Search' }))
        .toHaveAttribute('href', '/search?videoAssetId=' + videoId + '&track=' + trackId);
    });
  });
});
