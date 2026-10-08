import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getCamera } from '../../api/cameras';
import { getSystemConfig } from '../../api/system';
import { ApiError } from '../../api/client';
import { analyticsPollInterval, getRunAnalytics, requestSceneReanalysis, retryRunAnalytics, type ProcessingRunAnalytics, type SceneAnalysisUnit } from '../../api/sceneAnalytics';
import { getProcessingStatus, getVideo, queueProcessing, type AnalyticsReadiness, type ProcessingRunStatus } from '../../api/videos';
import { queryKeys } from '../../app/queryClient';
import { renderWithApp } from '../../test/renderWithApp';
import ProcessingPage from './ProcessingPage';

vi.mock('../../api/cameras', () => ({ getCamera: vi.fn() }));
vi.mock('../../api/sceneAnalytics', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/sceneAnalytics')>();
  return { ...original, getRunAnalytics: vi.fn(), retryRunAnalytics: vi.fn(), requestSceneReanalysis: vi.fn() };
});
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

/** The latest run, differing from an inference-time run only in what a test names. */
function latestRun(extra: Partial<ProcessingRunStatus>): ProcessingRunStatus {
  return {
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
    analyticsReadiness: 'NotConfigured',
    phase: 'processing',
    ...extra,
  };
}

/** The panel the run is stated in, found by its heading. */
async function runPanel(): Promise<HTMLElement> {
  return (await screen.findByRole('heading', { name: 'Processing run' })).closest('.panel') as HTMLElement;
}

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
        analyticsReadiness: 'NotConfigured',
        phase: 'processing',
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

  it('shows no scene analytics while the run is still processing', async () => {
    const { container } = render();
    await screen.findByText('CAM-COLD · Cold Cache Camera');
    expect(container.textContent).not.toMatch(/Scene analytics/);
    expect(getRunAnalytics).not.toHaveBeenCalled();
  });

  it('states timestamps in UTC, with a notice and Retry, when the display timezone fails — never as "—" (§14.1)', async () => {
    const user = userEvent.setup();
    vi.mocked(getSystemConfig).mockRejectedValue(new Error('offline'));
    render();

    const notice = await screen.findByText(/Display timezone is unavailable/);
    const queued = await screen.findByText('Queued');
    await waitFor(() => expect(queued.nextElementSibling).toHaveTextContent('2026-09-09T02:30:00Z UTC'));
    expect(screen.getByText('Recorded').nextElementSibling).toHaveTextContent('UTC');

    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    await user.click(within(notice.closest('[role="status"], [role="alert"]') as HTMLElement).getByRole('button', { name: 'Retry display config' }));

    await waitFor(() => expect(screen.queryByText(/Display timezone is unavailable/)).not.toBeInTheDocument());
    expect(screen.getByText('Queued').nextElementSibling).not.toHaveTextContent('UTC');
    expect(screen.getByText('Queued').nextElementSibling).not.toHaveTextContent('—');
  });

  describe('scene analytics readiness (Slice 4)', () => {
    const runId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21431';
    const activeRevision = '018f3f5a-2f70-7a2b-8a12-2d02f4c21482';

    function completedRun(readiness: AnalyticsReadiness): ProcessingRunStatus {
      return {
        processingRunId: runId, status: 'Completed', pipeline: 'phase1-detection-tracking', pipelineVersion: 'phase1-v1', workerId: 'worker-a',
        queuedAtUtc: '2026-09-09T02:30:00Z', startedAtUtc: '2026-09-09T02:30:02Z', completedAtUtc: '2026-09-09T02:35:02Z', progressPercent: 100,
        attemptCount: 1, failureCode: null, framesProcessed: 1500, tracksCreated: 6, analyticsReadiness: readiness, phase: 'completed',
      };
    }

    function unit(overrides: Partial<SceneAnalysisUnit>): SceneAnalysisUnit {
      return {
        analysisId: '018f3f5a-2f70-7a2b-8a12-2d02f4c214a1', processingRunId: runId, sceneRevisionId: activeRevision, sceneRevisionNumber: 2,
        algorithmVersion: 'scene-analytics-v1', status: 'Completed', attemptCount: 1, queuedAtUtc: '2026-09-09T02:36:00Z', startedAtUtc: '2026-09-09T02:36:01Z',
        completedAtUtc: '2026-09-09T02:36:30Z', leaseExpiresAtUtc: null, analysedTrackCount: 5, unavailableTrackCount: 1, failureCode: null, ...overrides,
      };
    }

    function analytics(readiness: AnalyticsReadiness, units: SceneAnalysisUnit[], active: string | null = activeRevision): ProcessingRunAnalytics {
      return { processingRunId: runId, readiness, activeSceneRevisionId: active, algorithmVersion: 'scene-analytics-v1', analyses: units };
    }

    function arrange(readiness: AnalyticsReadiness, units: SceneAnalysisUnit[], active: string | null = activeRevision) {
      vi.mocked(getVideo).mockResolvedValue({ ...vi.mocked(getVideo).mock.results[0]?.value ?? {}, id: videoId, cameraId, originalFileName: 'source.mp4', recordingStartUtc: '2026-09-09T02:30:00Z', recordingEndUtc: '2026-09-09T02:31:00Z', recordingTimeZoneId: 'UTC', recordingUtcOffsetMinutes: 0, durationMs: 60_000, width: 1920, height: 1080, frameRateNumerator: 25, frameRateDenominator: 1, codecName: 'h264', processingStatus: 'Processed', importedAtUtc: '2026-09-09T02:32:00Z' });
      vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'Processed', latestRun: completedRun(readiness) });
      vi.mocked(getRunAnalytics).mockResolvedValue(analytics(readiness, units, active));
    }

    it('names the revision, engine and Track counts once analysed, still with one badge', async () => {
      arrange('Ready', [unit({})]);
      const { container } = render();

      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(within(panel).getByText('Analysed')).toBeInTheDocument();
      expect(await within(panel).findByText('Revision 2 · scene-analytics-v1')).toBeInTheDocument();
      expect(within(panel).getByText('Tracks analysed').nextElementSibling).toHaveTextContent('5');
      expect(within(panel).getByText('Tracks unavailable').nextElementSibling).toHaveTextContent('1');
      expect(getRunAnalytics).toHaveBeenCalledWith(runId, expect.anything());
      // Readiness is text: the Context Bar's video badge stays the row's only badge.
      expect(container.querySelectorAll('.badge')).toHaveLength(1);
      expect(panel.querySelector('.badge')).toBeNull();
    });

    it('retries a failed unit through the Slice 3 retry endpoint', async () => {
      const user = userEvent.setup();
      arrange('Failed', [unit({ status: 'Failed', attemptCount: 3, failureCode: 'analytics_attempts_exhausted' })]);
      vi.mocked(retryRunAnalytics).mockResolvedValue(unit({ status: 'Queued', attemptCount: 0 }));
      render();

      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(within(panel).getByText('Analysis failed')).toBeInTheDocument();
      expect(await within(panel).findByText('analytics_attempts_exhausted')).toBeInTheDocument();
      // §8.1: the surface's one primary is the Context Bar's `Open results`;
      // the retry beside the failure is secondary.
      expect(within(panel).getByRole('button', { name: 'Retry analytics' })).not.toHaveClass('btn--primary');
      expect(Array.from(document.querySelectorAll('.btn--primary')).map((button) => button.textContent)).toEqual(['Open results']);
      await user.click(within(panel).getByRole('button', { name: 'Retry analytics' }));
      await waitFor(() => expect(retryRunAnalytics).toHaveBeenCalledWith(runId));
      expect(requestSceneReanalysis).not.toHaveBeenCalled();
    });

    it('states an analytics failure once — the readiness and code — and the alert only says what retrying does', async () => {
      arrange('Failed', [unit({ status: 'Failed', attemptCount: 3, failureCode: 'analytics_attempts_exhausted' })]);
      render();

      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(await within(panel).findByText('analytics_attempts_exhausted')).toBeInTheDocument();
      expect(within(panel).getAllByText(/failed/i)).toHaveLength(1);
      expect(within(panel).getByRole('alert')).toHaveTextContent(/^Retrying starts a new attempt cycle/);
    });

    it('says what could not be retried when the analytics retry is refused, then the API detail and code', async () => {
      const user = userEvent.setup();
      arrange('Failed', [unit({ status: 'Failed', attemptCount: 3, failureCode: 'analytics_attempts_exhausted' })]);
      vi.mocked(retryRunAnalytics).mockRejectedValue(new ApiError({ status: 409, code: 'analysis_not_retryable', detail: 'The analysis is not in a retryable state.' }));
      render();

      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      await user.click(await within(panel).findByRole('button', { name: 'Retry analytics' }));
      expect(await within(panel).findByText('Scene analytics could not be retried. The analysis is not in a retryable state. (analysis_not_retryable)')).toBeInTheDocument();
      // Recovery stays where it was: the action is offered again once settled.
      await waitFor(() => expect(within(panel).getByRole('button', { name: 'Retry analytics' })).toBeEnabled());
    });

    it('keeps scene analytics when only the video record fails, withholding just the camera-wide re-analysis', async () => {
      arrange('Stale', [unit({ sceneRevisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21481', sceneRevisionNumber: 1 })]);
      vi.mocked(getVideo).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Video store unavailable.' }));
      render();

      // §37.1: the analytics region's request is the run's, so it still renders.
      const panel = (await screen.findByText('Scene analytics', {}, { timeout: 4000 })).closest('.panel') as HTMLElement;
      expect(within(panel).getByText('Stale')).toBeInTheDocument();
      expect(await screen.findByText('Video metadata is unavailable.', {}, { timeout: 4000 })).toBeInTheDocument();
      // Re-analysis is camera-wide and the camera is the video record's: it waits for that retry.
      expect(within(panel).queryByRole('button', { name: 'Re-analyse camera' })).not.toBeInTheDocument();
      expect(within(panel).queryByText(/every video of/)).not.toBeInTheDocument();
      expect(requestSceneReanalysis).not.toHaveBeenCalled();
    });

    it('explains a stale run and offers the camera-wide re-analysis with its consequence stated', async () => {
      const user = userEvent.setup();
      arrange('Stale', [unit({ sceneRevisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21481', sceneRevisionNumber: 1, status: 'Superseded' })]);
      vi.mocked(requestSceneReanalysis).mockResolvedValue({
        cameraId, sceneRevisionId: activeRevision, algorithmVersion: 'scene-analytics-v1', scope: 'latestRuns',
        created: 1, alreadyQueued: 0, alreadyRunning: 0, alreadyReady: 2, failedRequiresRetry: 0, alreadySuperseded: 0, runsInScope: 3,
      });
      render();

      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(within(panel).getByText('Stale')).toBeInTheDocument();
      expect(await within(panel).findByText('Revision 1 · scene-analytics-v1')).toBeInTheDocument();
      expect(within(panel).getByText(/latest completed run of/)).toHaveTextContent('every video of CAM-COLD · Cold Cache Camera');
      await user.click(within(panel).getByRole('button', { name: 'Re-analyse camera' }));
      await waitFor(() => expect(requestSceneReanalysis).toHaveBeenCalledWith(cameraId, 'latestRuns'));
      expect(await within(panel).findByText(/1 of 3 runs queued/)).toBeInTheDocument();
      expect(retryRunAnalytics).not.toHaveBeenCalled();
    });

    it('keeps disabled and never-configured distinct, each pointing at the Scene Editor', async () => {
      arrange('Disabled', []);
      const first = render();
      const disabled = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(within(disabled).getByText('Disabled by scene')).toBeInTheDocument();
      expect(within(disabled).getByText(/switched off for this camera on purpose/)).toBeInTheDocument();
      expect(within(disabled).getByRole('link', { name: 'Open Scene Editor' })).toHaveAttribute('href', `/cameras/${cameraId}/scene`);
      first.unmount();

      arrange('NotConfigured', [], null);
      render();
      const unconfigured = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(within(unconfigured).getByText('No scene configured')).toBeInTheDocument();
      expect(within(unconfigured).getByText(/no scene configuration yet/)).toBeInTheDocument();
      expect(within(unconfigured).queryByRole('button')).not.toBeInTheDocument();
    });

    it('says a pending run is still on its way and shows the unit progress', async () => {
      arrange('Pending', [unit({ status: 'Running', attemptCount: 2, completedAtUtc: null })]);
      render();

      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(within(panel).getByText('Not analysed yet')).toBeInTheDocument();
      expect(await within(panel).findByText('Running · attempt 2')).toBeInTheDocument();
      expect(within(panel).getByText(/keeps refreshing until it does/)).toBeInTheDocument();
    });

    it('states a failed poll over details already shown, with a retry, and recovers polling when the retry succeeds', async () => {
      const user = userEvent.setup();
      const units = [unit({ status: 'Running', attemptCount: 2, completedAtUtc: null })];
      arrange('Pending', units);
      const { queryClient } = render();
      const analyticsQuery = () => queryClient.getQueryCache().find({ queryKey: queryKeys.runAnalytics(runId) })!;
      const requests = () => vi.mocked(getRunAnalytics).mock.calls.length;

      // 1. Pending analytics load.
      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(await within(panel).findByText('Running · attempt 2')).toBeInTheDocument();
      expect(within(panel).getByText(/keeps refreshing until it does/)).toBeInTheDocument();

      // 2. A later poll fails (after the query's one retry).
      vi.mocked(getRunAnalytics).mockRejectedValue(new ApiError({ status: 503, code: 'upstream_unavailable', detail: 'Down.' }));
      await act(async () => {
        await queryClient.refetchQueries({ queryKey: queryKeys.runAnalytics(runId) });
      });

      // 3-5. Cached details stay, the warning says polling has stopped, Retry is offered.
      const warning = await within(panel).findByText(/could not be refreshed, so this page has stopped checking/, {}, { timeout: 4000 });
      expect(within(panel).getByText('Running · attempt 2')).toBeInTheDocument();
      expect(within(panel).queryByText(/keeps refreshing until it does/)).not.toBeInTheDocument();
      const status = warning.closest('[role="status"]') as HTMLElement;
      const retry = within(status).getByRole('button', { name: 'Retry' });
      // Degraded really means stopped: no automatic request across a full poll interval.
      const whileDegraded = requests();
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 2_500)); });
      expect(requests()).toBe(whileDegraded);

      // 6-7. The operator retries, and it succeeds with Pending analytics.
      vi.mocked(getRunAnalytics).mockResolvedValue(analytics('Pending', units, activeRevision));
      await user.click(retry);

      // 8-9. The warning goes and the normal refreshing state returns, details intact.
      await waitFor(() => expect(within(panel).queryByText(/stopped checking/)).not.toBeInTheDocument());
      expect(within(panel).getByText(/keeps refreshing until it does/)).toBeInTheDocument();
      expect(within(panel).getByText('Running · attempt 2')).toBeInTheDocument();

      // 10. Automatic polling is eligible again: the query is back in exactly the
      // state for which the page's refetchInterval answers 2000 ms…
      expect(analyticsQuery().state.error).toBeNull();
      expect(analyticsPollInterval(analyticsQuery().state.data as ProcessingRunAnalytics | undefined)).toBe(2_000);
      // …and the next automatic request actually happens, with no operator action.
      const afterRetry = requests();
      await waitFor(() => expect(requests()).toBeGreaterThan(afterRetry), { timeout: 4_000 });
    }, 15_000);

    it('does not claim to keep refreshing a Pending run whose analytics never loaded', async () => {
      arrange('Pending', []);
      vi.mocked(getRunAnalytics).mockRejectedValue(new ApiError({ status: 503, code: 'upstream_unavailable', detail: 'Down.' }));
      render();

      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(await within(panel).findByText(/Analysis details are unavailable/, {}, { timeout: 4000 })).toBeInTheDocument();
      expect(within(panel).queryByText(/keeps refreshing until it does/)).not.toBeInTheDocument();
    });

    it('promises a Retry only when it offers one', async () => {
      arrange('Pending', [unit({ status: 'Running', attemptCount: 2, completedAtUtc: null })]);
      const { queryClient } = render();
      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      expect(await within(panel).findByText('Running · attempt 2')).toBeInTheDocument();

      // The run's analytics no longer exist: retrying cannot help, so none is offered — or promised.
      vi.mocked(getRunAnalytics).mockRejectedValue(new ApiError({ status: 404, code: 'not_found', detail: 'Gone.' }));
      await act(async () => {
        await queryClient.refetchQueries({ queryKey: queryKeys.runAnalytics(runId) });
      });
      const warning = await within(panel).findByText(/could not be refreshed/, {}, { timeout: 4000 });
      expect(warning).not.toHaveTextContent('Retry resumes');
      expect(within(warning.closest('[role="status"]') as HTMLElement).queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    });

    it('falls back to the status readiness when the lifecycle endpoint is unavailable', async () => {
      arrange('Ready', []);
      vi.mocked(getRunAnalytics).mockRejectedValue(new ApiError({ status: 503, code: 'upstream_unavailable', detail: 'Down.' }));
      render();

      const panel = (await screen.findByText('Scene analytics')).closest('.panel') as HTMLElement;
      // The query retries once before failing terminally, so give it the retry.
      expect(await within(panel).findByText(/Analysis details are unavailable/, {}, { timeout: 4000 })).toBeInTheDocument();
      expect(within(panel).getByText('Analysed')).toBeInTheDocument();
    });
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
        analyticsReadiness: 'NotConfigured',
        phase: 'processing',
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

  /** Inside the shell, which writes the document title from the same crumbs. */
  const renderInShell = (id = videoId) => renderWithApp(<ProcessingPage />, {
    route: `/processing/${id}`,
    routePath: '/processing/:videoAssetId',
    shell: 'processing-detail',
  });

  /** `Processing › {identity}`, with the identity current and nothing in place of it. */
  async function expectVideoIdentity(identity: string) {
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByRole('link', { name: 'Processing' })).toHaveAttribute('href', '/processing');
    expect(await within(crumbs).findByText(identity)).toHaveAttribute('aria-current', 'page');
    expect(within(crumbs).getAllByRole('listitem')).toHaveLength(2);
    expect(within(crumbs).queryByText('Not found')).not.toBeInTheDocument();
    expect(within(crumbs).queryByText('Video')).not.toBeInTheDocument();
    expect(within(crumbs).queryByText(videoId)).not.toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe(`${identity} — Processing — MAVI`));
    expect(document.title).not.toContain(videoId);
  }

  it('keeps a missing video under Processing, named by its identifier rather than by its state (§5, §14)', async () => {
    vi.mocked(getVideo).mockRejectedValue(new ApiError({ status: 404, code: 'video_not_found', detail: 'No such video.' }));
    renderInShell();

    expect(await screen.findByText('Video was not found.')).toBeInTheDocument();
    await expectVideoIdentity(`Video ${videoId.slice(0, 8)}…`);
    expect(document.title).not.toContain('Not found');
  });

  it('names the video by its identifier while its record is unreadable, not by a bare `Video` (§5, §14)', async () => {
    vi.mocked(getVideo).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Video store unavailable.' }));
    renderInShell();

    // The run is still stated: only the file name is missing.
    expect(await screen.findByRole('heading', { name: 'Processing run' })).toBeInTheDocument();
    await waitFor(() => expect(getVideo).toHaveBeenCalled());
    await expectVideoIdentity(`Video ${videoId.slice(0, 8)}…`);
    expect(screen.queryByText('Video was not found.')).not.toBeInTheDocument();
  });

  it('names the video by its identifier while it loads, and by its file name once read', async () => {
    let resolve: (value: Awaited<ReturnType<typeof getVideo>>) => void = () => {};
    const original = vi.mocked(getVideo).getMockImplementation();
    vi.mocked(getVideo).mockImplementation((...args) => new Promise((done) => {
      resolve = done;
      void args;
    }));
    renderInShell();

    await screen.findByRole('heading', { name: 'Processing run' });
    await expectVideoIdentity(`Video ${videoId.slice(0, 8)}…`);

    const record = await (original as typeof getVideo)(videoId);
    await act(async () => { resolve(record); });
    await expectVideoIdentity(record.originalFileName);
  });

  it('keeps `Unknown video` for a route whose identifier is not one', async () => {
    renderInShell('not-a-guid');
    expect(await screen.findByText(/identifier in this route is invalid/)).toBeInTheDocument();
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByText('Unknown video')).toHaveAttribute('aria-current', 'page');
    await waitFor(() => expect(document.title).toBe('Unknown video — Processing — MAVI'));
    expect(getVideo).not.toHaveBeenCalled();
  });

  it('reports an unavailable status as unavailable rather than as no run', async () => {
    vi.mocked(getProcessingStatus).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Status store unavailable.' }));
    render();

    // The query retries once before failing terminally, so allow for it
    // rather than reading the retry window as the answer.
    expect(await screen.findByText('Processing status is unavailable.', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText('Not queued')).not.toBeInTheDocument();
  });

  it('states an unavailable status inside the primary region it replaces, with the retry in the alert', async () => {
    const user = userEvent.setup();
    vi.mocked(getProcessingStatus).mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Status store unavailable.' }));
    render();

    // §37.1: the primary column keeps its identity — the Processing run panel
    // is still there — and the failure is one alert inside it.
    const alert = await screen.findByRole('alert', {}, { timeout: 4000 });
    const panel = screen.getByRole('heading', { name: 'Processing run' }).closest('section')!;
    expect(panel).toContainElement(alert);
    expect(screen.getAllByRole('alert')).toHaveLength(1);

    const calls = vi.mocked(getProcessingStatus).mock.calls.length;
    vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'NotQueued', latestRun: null });
    await user.click(within(alert).getByRole('button', { name: 'Retry' }));
    expect(await within(panel).findByText('Not queued')).toBeInTheDocument();
    expect(vi.mocked(getProcessingStatus).mock.calls.length).toBeGreaterThan(calls);
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

  it('names the video when queueing is refused, with the API detail and code last', async () => {
    const user = userEvent.setup();
    vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'NotQueued', latestRun: null });
    vi.mocked(queueProcessing).mockRejectedValue(new ApiError({ status: 503, code: 'queue_unavailable', detail: 'The processing queue did not respond.' }));
    render();

    await user.click(await screen.findByRole('button', { name: 'Queue processing' }));
    expect(await screen.findByText('Processing could not be queued for source.mp4. The processing queue did not respond. (queue_unavailable)')).toBeInTheDocument();
    // The not-queued state is unchanged and the action is offered again.
    expect(within(await runPanel()).getByText('Not queued')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Queue processing' })).toBeEnabled();
  });

  it('keeps the queue action disabled until the authoritative refresh after it has answered', async () => {
    const user = userEvent.setup();
    let answer: (value: Awaited<ReturnType<typeof getProcessingStatus>>) => void = () => {};
    vi.mocked(getProcessingStatus)
      .mockResolvedValueOnce({ videoStatus: 'NotQueued', latestRun: null })
      .mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
    render();

    await user.click(await screen.findByRole('button', { name: 'Queue processing' }));
    await waitFor(() => expect(queueProcessing).toHaveBeenCalledOnce());
    // Queued on the server, but the page has not yet read that back: no second click.
    expect(screen.getByRole('button', { name: 'Queueing…' })).toBeDisabled();
    await act(async () => {
      answer({ videoStatus: 'Queued', latestRun: latestRun({ status: 'Queued', phase: 'queued', progressPercent: 0, startedAtUtc: null, workerId: null }) });
    });
    // The authoritative answer is Queued, which offers nothing to queue.
    await waitFor(() => expect(screen.queryByRole('button', { name: /Queue/ })).not.toBeInTheDocument());
    expect(queueProcessing).toHaveBeenCalledOnce();
  });

  it('keeps the retained run, labelled as last known, when a refresh of it fails — and recovers on Retry', async () => {
    const user = userEvent.setup();
    const failed = { videoStatus: 'Failed' as const, latestRun: latestRun({ status: 'Failed', phase: 'failed', progressPercent: 12, completedAtUtc: '2026-09-09T02:35:02Z', failureCode: 'vision_job_attempts_exhausted' }) };
    vi.mocked(getProcessingStatus)
      .mockResolvedValueOnce(failed)
      .mockRejectedValue(new ApiError({ status: 503, code: 'api_error', detail: 'Status store unavailable.' }));
    render();

    // The queue request succeeds; the refresh after it fails (the query's one retry included).
    await user.click(await screen.findByRole('button', { name: 'Retry processing' }));
    const panel = await runPanel();
    const warning = await within(panel).findByText('Showing the last known processing status; refreshing failed.', {}, { timeout: 5000 });
    expect(within(panel).getByText('vision_job_attempts_exhausted')).toBeInTheDocument();
    expect(screen.queryByText('Not queued')).not.toBeInTheDocument();

    vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'Queued', latestRun: latestRun({ status: 'Queued', phase: 'queued', progressPercent: 0, startedAtUtc: null, workerId: null }) });
    await user.click(within(warning.closest('.alert') as HTMLElement).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(within(panel).queryByText(/last known/)).not.toBeInTheDocument());
    expect(within(panel).getAllByText('Final count after completion', { selector: 'dd' })).toHaveLength(2);
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
        analyticsReadiness: 'NotConfigured',
        phase: 'failed',
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
        analyticsReadiness: 'NotConfigured',
        phase: 'processing',
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
        analyticsReadiness: 'NotConfigured',
        phase: 'completed',
      },
    });
    renderWithApp(<ProcessingPage />, {
      route: `/processing/${videoId}`,
      routePath: '/processing/:videoAssetId',
    });
    expect(await screen.findByText('15,000')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  describe('run phases (U1)', () => {
    // The shapes of the F4-A visual states (`processing-finalizing`,
    // `processing-failed-finalization`): the platform's own truth, not a UI guess.
    const finalizing = () => latestRun({ status: 'Running', phase: 'finalizing', progressPercent: 100 });
    const failedFinalization = () => latestRun({
      status: 'Failed',
      phase: 'failed',
      progressPercent: 100,
      completedAtUtc: '2026-09-09T02:35:02Z',
      failureCode: 'vision_finalization_staging_missing',
    });

    it('states a Finalizing run as Finalizing, with no inference progress and no running total', async () => {
      vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'Processing', latestRun: finalizing() });
      const { container } = render();
      const panel = await runPanel();

      const badge = await within(panel).findByText('Finalizing');
      expect(badge).toHaveAttribute('data-status', 'Finalizing');
      expect(badge).toHaveClass('badge--active');
      expect(within(panel).getByText(/Inference is complete/)).toBeInTheDocument();
      // No finalization percentage exists, so none is drawn — and a full
      // inference bar would read as done.
      expect(screen.queryByText('Progress')).not.toBeInTheDocument();
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      expect(container.textContent).not.toMatch(/\bRunning\b/);
      // Counts arrive with publication, which is what this run is waiting for.
      expect(screen.getByText('Frames processed').parentElement).toHaveTextContent('Final count after publication');
      expect(screen.getByText('Tracks created').parentElement).toHaveTextContent('Final count after publication');
      // Said once: the sentence no longer repeats when counts appear.
      expect(within(panel).getByText(/Inference is complete/)).not.toHaveTextContent(/counts/i);

      // The Context Bar keeps the video's own, still truthful, status.
      const bar = container.querySelector('.context-bar') as HTMLElement;
      expect(within(bar).getByText('Processing', { selector: '.badge' })).toHaveAttribute('data-status', 'Processing');
      expect(container.querySelectorAll('.badge')).toHaveLength(2);
    });

    it('takes Finalizing from the phase alone: the same Running run in inference reads as progress', async () => {
      vi.mocked(getProcessingStatus).mockResolvedValue({
        videoStatus: 'Processing',
        latestRun: { ...finalizing(), phase: 'processing' },
      });
      const { container } = render();
      const panel = await runPanel();

      expect(await within(panel).findByText('Progress')).toBeInTheDocument();
      expect(within(panel).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
      expect(screen.queryByText('Finalizing')).not.toBeInTheDocument();
      expect(screen.queryByText(/Inference is complete/)).not.toBeInTheDocument();
      expect(container.querySelectorAll('.badge')).toHaveLength(1);
    });

    it('states a finalization failure as one, with its code, and not as a processing failure', async () => {
      const user = userEvent.setup();
      vi.mocked(getProcessingStatus).mockResolvedValue({ videoStatus: 'Failed', latestRun: failedFinalization() });
      render();
      const panel = await runPanel();

      const alert = await within(panel).findByRole('alert');
      expect(alert).toHaveTextContent(/^Finalization failed/);
      expect(within(alert).getByText('vision_finalization_staging_missing').tagName).toBe('CODE');
      // R3: no inference bar captioned with a finalization failure — it would
      // read as a bar about publication — and no completion language: the run
      // is terminal, its counts were never published, and it ended by failing.
      expect(within(panel).queryByRole('progressbar')).not.toBeInTheDocument();
      expect(screen.queryByText(/Processing failed/)).not.toBeInTheDocument();
      expect(within(panel).getByText('Frames processed').parentElement).toHaveTextContent('Not published');
      expect(within(panel).getByText('Tracks created').parentElement).toHaveTextContent('Not published');
      expect(within(panel).queryByText(/after completion/)).not.toBeInTheDocument();
      expect(within(panel).getByText('Failed', { selector: 'dt' })).toBeInTheDocument();
      expect(within(panel).queryByText('Completed')).not.toBeInTheDocument();

      // Retry is unchanged: it queues a new run.
      await user.click(screen.getByRole('button', { name: 'Retry processing' }));
      await waitFor(() => expect(queueProcessing).toHaveBeenCalledWith(videoId));
    });

    it('leaves an ordinary failure described as a processing failure', async () => {
      vi.mocked(getProcessingStatus).mockResolvedValue({
        videoStatus: 'Failed',
        latestRun: { ...failedFinalization(), failureCode: 'worker_watchdog_timeout', progressPercent: 12 },
      });
      render();
      const panel = await runPanel();

      const alert = await within(panel).findByRole('alert');
      expect(alert).toHaveTextContent('Processing failed with worker_watchdog_timeout. Retrying queues a new run for this video.');
      expect(within(panel).getByText('Failed', { selector: '.progress__label span' })).toBeInTheDocument();
      expect(screen.queryByText(/Finalization failed/)).not.toBeInTheDocument();
      expect(screen.queryByText('Finalizing')).not.toBeInTheDocument();
      // F19: a terminal failure never says its counts come "after completion",
      // and its end time is when it failed.
      expect(within(panel).getByText('Frames processed').parentElement).toHaveTextContent('Not produced');
      expect(within(panel).getByText('Tracks created').parentElement).toHaveTextContent('Not produced');
      expect(within(panel).queryByText(/after completion/)).not.toBeInTheDocument();
      expect(within(panel).queryByText('Completed')).not.toBeInTheDocument();
    });

    it('leaves a queued run and a completed run exactly as they were', async () => {
      vi.mocked(getProcessingStatus).mockResolvedValue({
        videoStatus: 'Queued',
        latestRun: latestRun({ status: 'Queued', phase: 'queued', progressPercent: 0, startedAtUtc: null, workerId: null }),
      });
      const queued = render();
      expect(await within(await runPanel()).findByText('Progress')).toBeInTheDocument();
      expect(screen.queryByText('Finalizing')).not.toBeInTheDocument();
      queued.unmount();

      vi.mocked(getProcessingStatus).mockResolvedValue({
        videoStatus: 'Processed',
        latestRun: latestRun({
          status: 'Completed', phase: 'completed', progressPercent: 100, completedAtUtc: '2026-09-09T02:40:02Z',
          framesProcessed: 15_000, tracksCreated: 42,
        }),
      });
      render();
      const panel = await runPanel();
      expect(await within(panel).findByText('Completed', { selector: '.progress__label span' })).toBeInTheDocument();
      expect(within(panel).getByText('15,000')).toBeInTheDocument();
      expect(screen.queryByText('Finalizing')).not.toBeInTheDocument();
      expect(screen.queryByText(/Finalization failed/)).not.toBeInTheDocument();
    });
  });
});
