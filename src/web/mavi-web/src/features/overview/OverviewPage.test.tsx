import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { searchTracks, type TrackSearchItem } from '../../api/tracks';
import { getProcessingStatus, listVideos, type AnalyticsReadiness, type ProcessingStatus, type VideoAsset } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import OverviewPage from './OverviewPage';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn(), getProcessingStatus: vi.fn() };
});
vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, searchTracks: vi.fn() };
});

const camera = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21412', code: 'CAM-01', name: 'North Gate', description: null, locationName: null,
  timeZoneId: 'Asia/Kolkata', isActive: true, createdAtUtc: '2026-09-14T02:30:00Z', updatedAtUtc: '2026-09-14T02:30:00Z',
};

function video(id: string, processingStatus: string, importedAtUtc = '2026-09-14T03:00:00Z'): VideoAsset {
  return {
    id, cameraId: camera.id, originalFileName: `${id}.mp4`, recordingStartUtc: '2026-09-14T02:00:00Z', recordingEndUtc: '2026-09-14T02:10:00Z',
    recordingTimeZoneId: 'Asia/Kolkata', recordingUtcOffsetMinutes: 330, durationMs: 600_000, width: 1920, height: 1080,
    frameRateNumerator: 25, frameRateDenominator: 1, codecName: 'h264', processingStatus, importedAtUtc,
  };
}

/** A video's processing status as `GET /api/videos/{id}/processing` answers it. */
function statusOf(videoStatus: string, runStatus: string | null, extra: { readiness?: AnalyticsReadiness; failureCode?: string } = {}): ProcessingStatus {
  return {
    videoStatus,
    latestRun: runStatus === null ? null : {
      processingRunId: 'run', status: runStatus, pipeline: 'p', pipelineVersion: '1', workerId: null, queuedAtUtc: '2026-09-14T03:00:00Z',
      startedAtUtc: null, completedAtUtc: null, progressPercent: 100, attemptCount: 1, failureCode: extra.failureCode ?? null,
      framesProcessed: 0, tracksCreated: 0, analyticsReadiness: extra.readiness ?? 'Ready',
      phase: runStatus === 'Completed' ? 'completed' : runStatus === 'Failed' ? 'failed' : 'processing',
    },
  };
}
const STATUSES: Record<string, ProcessingStatus> = {
  a: statusOf('Processed', 'Completed'),
  c: statusOf('Failed', 'Failed', { failureCode: 'vision_job_attempts_exhausted' }),
};
// A failed lookup retries once before it answers, and the region waits for its answer.
const attention = () => screen.findByRole('region', { name: 'Needs attention' }, { timeout: 5000 });

const track: TrackSearchItem = {
  id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21451', processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431', videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
  cameraId: camera.id, cameraCode: camera.code, cameraName: camera.name, objectClass: 'Vehicle', startTimestampUtc: '2026-09-14T02:30:00Z',
  endTimestampUtc: '2026-09-14T02:30:08Z', startOffsetMs: 10_000, endOffsetMs: 18_000, durationMs: 8_000, detectionCount: 32,
  meanConfidence: 0.91, maxConfidence: 0.97, reviewStatus: 'Unreviewed', thumbnailArtifactId: null, thumbnailContentUrl: null,
  videoContentUrl: '/api/videos/018f3f5a-2f70-7a2b-8a12-2d02f4c21421/content',
};

describe('OverviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCameras).mockResolvedValue([camera, { ...camera, id: 'x', isActive: false }]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(listVideos).mockResolvedValue([video('a', 'Processed'), video('b', 'Processing'), video('c', 'Failed'), video('d', 'NotQueued'), video('e', 'Queued')]);
    vi.mocked(searchTracks).mockResolvedValue({ items: [track], nextCursor: null });
    vi.mocked(getProcessingStatus).mockImplementation(async (id) => STATUSES[id] ?? statusOf('Processed', 'Completed'));
  });

  it('summarises cameras, media status and the newest Tracks with links into each workflow', async () => {
    renderWithApp(<OverviewPage />, { route: '/' });

    const cameras = await screen.findByRole('link', { name: /Cameras.*2.*1 active/ });
    expect(cameras).toHaveAttribute('href', '/cameras');
    expect(screen.getByRole('link', { name: /Videos.*5.*1 processed/ })).toHaveAttribute('href', '/videos');
    expect(screen.getByRole('link', { name: /Processing.*2.*queued or running/ })).toHaveAttribute('href', '/processing');
    // What needs acting on is the attention region's, stated there once.
    expect(within(document.querySelector('.summary-band') as HTMLElement).queryByRole('link', { name: /Not queued/ })).not.toBeInTheDocument();

    const recent = (await screen.findByText('Vehicle')).closest('a') as HTMLAnchorElement;
    expect(recent).toHaveAttribute('href', `/search?videoAssetId=${track.videoAssetId}&track=${track.id}`);
    expect(recent).toHaveTextContent('CAM-01 · North Gate');
    expect(recent).toHaveTextContent('14 Sept 2026, 08:00:00 · 8s · 91%');
    expect(within(recent).getByText('Unreviewed')).toBeInTheDocument();
    expect(vi.mocked(searchTracks).mock.calls[0][0]).toEqual({ limit: 8 });
  });

  it('says once, with its own Retry, that the display timezone is unavailable (§37.1)', async () => {
    const user = userEvent.setup();
    vi.mocked(getSystemConfig).mockRejectedValue(new Error('offline'));
    renderWithApp(<OverviewPage />, { route: '/' });

    const notice = await screen.findByText(/Display timezone is unavailable/);
    expect(screen.getAllByText(/Display timezone is unavailable/)).toHaveLength(1);
    const retry = within(notice.closest('[role="status"], [role="alert"]') as HTMLElement).getByRole('button', { name: 'Retry display config' });

    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    await user.click(retry);
    await waitFor(() => expect(screen.queryByText(/Display timezone is unavailable/)).not.toBeInTheDocument());
  });

  it('explains an empty deployment instead of showing blank tiles', async () => {
    vi.mocked(listVideos).mockResolvedValue([]);
    vi.mocked(searchTracks).mockResolvedValue({ items: [], nextCursor: null });
    renderWithApp(<OverviewPage />, { route: '/' });
    expect(await screen.findByText('No tracks yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Videos.*0.*0 processed/ })).toBeInTheDocument();
  });

  it('is the Ledger-summary variant: a Context Bar, one scroll owner and uncontained readouts', async () => {
    const { container } = renderWithApp(<OverviewPage />, { route: '/' });
    await screen.findByText('Vehicle');

    expect(container.querySelector('.workspace--ledger-summary')).not.toBeNull();
    expect(container.querySelector('.context-bar')).not.toBeNull();
    expect(container.querySelectorAll('.workspace__body--scroll')).toHaveLength(1);
    // §4.1.1: Overview alone stays centred, so it must not declare full width.
    expect(container.querySelector('.page--full')).toBeNull();
    // §11: the four summary readouts are figures, not cards.
    expect(container.querySelector('.summary-band')).not.toBeNull();
    expect(container.querySelector('.stat')).toBeNull();
    // §24: the display timezone is disclosed once, on the surface.
    expect(within(container.querySelector('.context-bar') as HTMLElement).getByText('Asia/Kolkata')).toBeInTheDocument();
  });

  it('keeps both Context Bar workflow actions', async () => {
    renderWithApp(<OverviewPage />, { route: '/' });
    expect(await screen.findByRole('link', { name: 'Import video' })).toHaveAttribute('href', '/import');
    expect(screen.getByRole('link', { name: 'Search tracks' })).toHaveAttribute('href', '/search');
  });

  it('degrades only the section whose request failed', async () => {
    vi.mocked(listVideos).mockRejectedValue(new Error('down'));
    renderWithApp(<OverviewPage />, { route: '/' });

    // The media figures say they are unavailable rather than reading as zero…
    expect(await screen.findByText(/The video inventory is unavailable; its figures cannot be shown/)).toBeInTheDocument();
    // The media panel draws from the same request; it says it cannot be drawn,
    // as text, and the band's one notice carries the alert and its retry.
    expect(screen.getByText(/its distribution cannot be shown/)).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('link', { name: /Videos.*—.*unavailable/ })).toBeInTheDocument();

    // …while the two sections that answered are untouched.
    expect(screen.getByRole('link', { name: /Cameras.*2.*1 active/ })).toBeInTheDocument();
    expect(screen.getByText('Vehicle')).toBeInTheDocument();
  });

  it('states an unavailable camera inventory as unavailable, with a retry', async () => {
    const user = userEvent.setup();
    vi.mocked(listCameras).mockRejectedValue(new Error('down'));
    renderWithApp(<OverviewPage />, { route: '/' });

    // §14: unavailable is an alert with a retry, not a dash and a word.
    expect(await screen.findByText(/camera inventory is unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Cameras.*—.*unavailable/ })).toBeInTheDocument();
    expect(screen.queryByText('No cameras registered')).not.toBeInTheDocument();

    // The sections that answered are untouched.
    expect(screen.getByRole('link', { name: /Videos.*5.*1 processed/ })).toBeInTheDocument();
    expect(screen.getByText('Vehicle')).toBeInTheDocument();

    vi.mocked(listCameras).mockResolvedValue([camera]);
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByRole('link', { name: /Cameras.*1.*1 active/ })).toBeInTheDocument());
  });

  it('states both inventories in one notice rather than a stack of alerts', async () => {
    vi.mocked(listCameras).mockRejectedValue(new Error('down'));
    vi.mocked(listVideos).mockRejectedValue(new Error('down'));
    renderWithApp(<OverviewPage />, { route: '/' });

    const notice = await screen.findByText(/camera inventory and the video inventory are unavailable/i);
    expect(notice).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    // The one section that answered still answers.
    expect(screen.getByText('Vehicle')).toBeInTheDocument();
  });

  it('keeps an empty camera inventory distinct from an unavailable one', async () => {
    vi.mocked(listCameras).mockResolvedValue([]);
    renderWithApp(<OverviewPage />, { route: '/' });

    await screen.findByText('Vehicle');
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Cameras.*0.*0 active/ })).toBeInTheDocument();
  });

  it('keeps recent Tracks when only the Track search failed', async () => {
    vi.mocked(searchTracks).mockRejectedValue(new Error('down'));
    renderWithApp(<OverviewPage />, { route: '/' });

    expect(await screen.findByText('Recent tracks are unavailable.')).toBeInTheDocument();
    expect(screen.queryByText('No tracks yet')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Videos.*5.*1 processed/ })).toBeInTheDocument();
  });

  describe('the attention region (§4.1.1)', () => {
    it('renders the regions below only once its content is final, so nothing already shown moves (§36.3, §38)', async () => {
      const waiting: Array<(value: ProcessingStatus) => void> = [];
      vi.mocked(getProcessingStatus).mockImplementation((id) => (id === 'c'
        ? new Promise<ProcessingStatus>((resolve) => { waiting.push(resolve); })
        : Promise.resolve(STATUSES[id] ?? statusOf('Processed', 'Completed'))));
      renderWithApp(<OverviewPage />, { route: '/' });
      expect(await screen.findByText('Checking what needs attention…')).toBeInTheDocument();
      expect(document.querySelector('.summary-band')).toBeNull();
      expect(screen.queryByText('Recent tracks')).not.toBeInTheDocument();

      await waitFor(() => expect(waiting.length).toBeGreaterThan(0));
      waiting.forEach((resolve) => resolve(STATUSES.c));
      const region = await attention();
      expect(within(region).getByRole('link', { name: /vision_job_attempts_exhausted/ })).toBeInTheDocument();
      expect(document.querySelector('.summary-band')).not.toBeNull();
      expect(screen.getByText('Recent tracks')).toBeInTheDocument();
    });

    it('never holds the rest of the page on a failed inventory', async () => {
      vi.mocked(listVideos).mockRejectedValue(new Error('down'));
      renderWithApp(<OverviewPage />, { route: '/' });
      expect(await screen.findByText('Vehicle')).toBeInTheDocument();
      expect(document.querySelector('.summary-band')).not.toBeNull();
    });

    it('comes first, and lists a failed run with its code and the waiting media, each linking where it is acted on', async () => {
      const { container } = renderWithApp(<OverviewPage />, { route: '/' });
      const region = await attention();
      // First in the workspace body, before the readouts.
      const body = container.querySelector('.workspace__body--scroll') as HTMLElement;
      expect(body.querySelector('.attention, .attention-line')).toBe(body.querySelector('.attention, .attention-line, .summary-band'));

      const failed = await within(region).findByRole('link', { name: /Failed.*c\.mp4 · CAM-01.*not searchable.*vision_job_attempts_exhausted.*Open run/ });
      expect(failed).toHaveAttribute('href', '/processing/c');
      const waiting = within(region).getByRole('link', { name: /Not queued.*1 video.*Not searchable until processed.*Open videos/ });
      expect(waiting).toHaveAttribute('href', '/videos?status=NotQueued');
      // Failures first; a run still moving is not an item, and no stall is claimed.
      expect(within(region).getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(['/processing/c', '/videos?status=NotQueued']);
      expect(within(region).queryByText(/b\.mp4|e\.mp4|stall/i)).not.toBeInTheDocument();
    });

    it('says in one line that nothing needs attention when every check answered', async () => {
      vi.mocked(listVideos).mockResolvedValue([video('a', 'Processed'), video('b', 'Processed')]);
      const { container } = renderWithApp(<OverviewPage />, { route: '/' });
      expect(await screen.findByText('No items need attention.')).toBeInTheDocument();
      // No frame around nothing (§36.3).
      expect(container.querySelector('.attention')).toBeNull();
    });

    it('lists failed and stale analytics of completed runs, and nothing for the scene choices or analytics on its way', async () => {
      vi.mocked(listVideos).mockResolvedValue(['af', 'st', 'pe', 'nc', 'di'].map((id) => video(id, 'Processed')));
      vi.mocked(getProcessingStatus).mockImplementation(async (id) => statusOf('Processed', 'Completed', {
        readiness: ({ af: 'Failed', st: 'Stale', pe: 'Pending', nc: 'NotConfigured', di: 'Disabled' } as const)[id as 'af'],
      }));
      renderWithApp(<OverviewPage />, { route: '/' });
      const region = await attention();
      const rows = await within(region).findAllByRole('link');
      expect(rows.map((row) => row.textContent)).toEqual([
        expect.stringMatching(/^Analysis failed.*af\.mp4 · CAM-01.*zone and line results are missing/),
        expect.stringMatching(/^Stale.*st\.mp4 · CAM-01.*earlier scene geometry/),
      ]);
      expect(rows.map((row) => row.getAttribute('href'))).toEqual(['/processing/af', '/processing/st']);
    });

    it('bounds a long list with a disclosure, every item reachable', async () => {
      const user = userEvent.setup();
      vi.mocked(listVideos).mockResolvedValue(Array.from({ length: 8 }, (_, i) => video(`f${i}`, 'Failed', `2026-09-1${i}T00:00:00Z`)));
      vi.mocked(getProcessingStatus).mockImplementation(async () => statusOf('Failed', 'Failed', { failureCode: 'vision_job_attempts_exhausted' }));
      renderWithApp(<OverviewPage />, { route: '/' });
      const region = await attention();
      await waitFor(() => expect(within(region).getAllByRole('link')).toHaveLength(5));
      // Newest first.
      expect(within(region).getAllByRole('link')[0]).toHaveAttribute('href', '/processing/f7');
      const more = within(region).getByRole('button', { name: 'Show 3 more' });
      expect(more).toHaveAttribute('aria-expanded', 'false');
      await user.click(more);
      expect(within(region).getAllByRole('link')).toHaveLength(8);
      expect(within(region).getByRole('button', { name: 'Show fewer' })).toHaveAttribute('aria-expanded', 'true');
    });

    it('never declares clear while a check is still answering', async () => {
      vi.mocked(listVideos).mockResolvedValue([video('a', 'Processed')]);
      vi.mocked(getProcessingStatus).mockImplementation(() => new Promise(() => {}));
      renderWithApp(<OverviewPage />, { route: '/' });
      expect(await screen.findByText('Checking what needs attention…')).toBeInTheDocument();
      expect(screen.queryByText('No items need attention.')).not.toBeInTheDocument();
      // The regions below wait for the attention region's final height (§36.3).
      expect(document.querySelector('.summary-band')).toBeNull();
    });

    it('names a check that failed rather than reading it as healthy, and retries it', async () => {
      const user = userEvent.setup();
      vi.mocked(listVideos).mockResolvedValue([video('a', 'Processed')]);
      vi.mocked(getProcessingStatus).mockRejectedValue(new Error('down'));
      renderWithApp(<OverviewPage />, { route: '/' });
      // The shared per-video lookup retries once before it reports a failure.
      expect(await screen.findByText(/analytics of 1 video could not be read, so it is not known whether it needs attention/, undefined, { timeout: 5000 })).toBeInTheDocument();
      expect(screen.getByText('Nothing found in the checks that answered.')).toBeInTheDocument();
      expect(screen.queryByText('No items need attention.')).not.toBeInTheDocument();

      vi.mocked(getProcessingStatus).mockResolvedValue(statusOf('Processed', 'Completed'));
      await user.click(screen.getByRole('button', { name: 'Retry' }));
      expect(await screen.findByText('No items need attention.')).toBeInTheDocument();
    });

    it('says it cannot be evaluated while the video inventory is unavailable, never that nothing needs attention', async () => {
      vi.mocked(listVideos).mockRejectedValue(new Error('down'));
      renderWithApp(<OverviewPage />, { route: '/' });
      expect(await screen.findByText(/cannot be determined while the video inventory is unavailable/)).toBeInTheDocument();
      expect(screen.queryByText('No items need attention.')).not.toBeInTheDocument();
      // One cause, one alert: the band's notice (§14.1).
      expect(screen.getAllByRole('alert')).toHaveLength(1);
    });

    it('states the bounded analytics scope with the clear line', async () => {
      vi.mocked(listVideos).mockResolvedValue(Array.from({ length: 14 }, (_, i) => video(`p${String(i).padStart(2, '0')}`, 'Processed', `2026-09-${String(i + 1).padStart(2, '0')}T00:00:00Z`)));
      renderWithApp(<OverviewPage />, { route: '/' });
      expect(await screen.findByText('No items need attention.')).toBeInTheDocument();
      expect(screen.getByText('Analytics checked for the 12 most recently imported processed videos of 14.')).toBeInTheDocument();
    });

    it('reads only a bounded, stable set of video statuses, through the shared per-video cache', async () => {
      vi.mocked(listVideos).mockResolvedValue([
        ...Array.from({ length: 15 }, (_, i) => video(`p${String(i).padStart(2, '0')}`, 'Processed', `2026-09-${String(i + 1).padStart(2, '0')}T00:00:00Z`)),
        video('q', 'Queued'), video('r', 'Processing'), video('n', 'NotQueued'),
      ]);
      const { queryClient } = renderWithApp(<OverviewPage />, { route: '/' });
      const region = await attention();
      // The one item is the waiting media; every lookup has answered.
      await within(region).findByRole('link', { name: /Not queued.*1 video/ });
      await waitFor(() => expect(within(region).queryByText(/Checking/)).not.toBeInTheDocument());
      expect(within(region).getByText('Analytics checked for the 12 most recently imported processed videos of 15.')).toBeInTheDocument();
      const asked = vi.mocked(getProcessingStatus).mock.calls.map(([id]) => id);
      expect(asked).toHaveLength(12);
      expect(new Set(asked).size).toBe(12);
      expect(asked).not.toEqual(expect.arrayContaining(['q', 'r', 'n', 'p00', 'p01', 'p02']));
      expect(queryClient.getQueryData(['video-processing', 'p14'])).toBeDefined();
    });

    it('keeps the attention rows in the keyboard sequence, in reading order', async () => {
      const user = userEvent.setup();
      renderWithApp(<OverviewPage />, { route: '/' });
      const region = await attention();
      const first = await within(region).findByRole('link', { name: /c\.mp4/ });
      // From the Context Bar's last action, the next stop is the first attention row.
      screen.getByRole('link', { name: 'Search tracks' }).focus();
      await user.tab();
      expect(first).toHaveFocus();
    });

    it('agrees with the readouts: the failure it lists is the one the inventory counts', async () => {
      renderWithApp(<OverviewPage />, { route: '/' });
      const region = await attention();
      await within(region).findByRole('link', { name: /c\.mp4/ });
      expect(within(region).getAllByText('Failed')).toHaveLength(1);
      expect(screen.getByRole('link', { name: /Processing.*2.*queued or running/ })).toBeInTheDocument();
    });

    it('lists a failed video whose detail could not be read, saying only that its detail is missing', async () => {
      vi.mocked(listVideos).mockResolvedValue([video('c', 'Failed')]);
      vi.mocked(getProcessingStatus).mockRejectedValue(new Error('down'));
      renderWithApp(<OverviewPage />, { route: '/' });
      const region = await attention();
      expect(within(region).getByRole('link', { name: /Failed.*c\.mp4/ })).toHaveAttribute('href', '/processing/c');
      expect(await within(region).findByText(/failure detail of 1 video could not be read/, undefined, { timeout: 5000 })).toBeInTheDocument();
      expect(within(region).queryByText(/not known whether/)).not.toBeInTheDocument();
    });
  });
});
