import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAnalyticsAggregates, type AnalyticsAggregateResponse } from '../../api/analytics';
import { getCamera } from '../../api/cameras';
import { getCameraScene, type CameraScene } from '../../api/scene';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import type { AnalyticsCoverage } from '../../api/tracks';
import { renderWithApp } from '../../test/renderWithApp';
import AnalyticsPage from './AnalyticsPage';

vi.mock('../../api/cameras', () => ({ getCamera: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/scene', async () => {
  const actual = await vi.importActual<typeof import('../../api/scene')>('../../api/scene');
  return { ...actual, getCameraScene: vi.fn() };
});
vi.mock('../../api/analytics', async () => {
  const actual = await vi.importActual<typeof import('../../api/analytics')>('../../api/analytics');
  return { ...actual, getAnalyticsAggregates: vi.fn() };
});

const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';
const zoneId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21461';

const camera = {
  id: cameraId,
  code: 'CAM-01',
  name: 'North Gate',
  description: null,
  locationName: null,
  timeZoneId: 'Asia/Kolkata',
  isActive: true,
  createdAtUtc: '2026-09-14T02:30:00Z',
  updatedAtUtc: '2026-09-14T02:30:00Z',
};

const completeCoverage: AnalyticsCoverage = {
  sceneRevisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21481',
  algorithmVersion: 'scene-analytics-v1',
  evaluatedRuns: 3,
  pendingRuns: 0,
  failedRuns: 0,
  notConfiguredRuns: 0,
  disabledRuns: 0,
  staleRuns: 0,
  analysedTracks: 12,
  unavailableTracks: 0,
  complete: true,
};

function answer(overrides: Partial<AnalyticsAggregateResponse> = {}): AnalyticsAggregateResponse {
  return {
    cameraId,
    sceneRevisionId: completeCoverage.sceneRevisionId,
    sceneRevisionNumber: 4,
    algorithmVersion: 'scene-analytics-v1',
    snapshotVisibilitySequence: 22,
    fromUtc: '2026-09-21T00:00:00Z',
    toUtc: '2026-09-21T02:00:00Z',
    bucketSeconds: 3_600,
    objectClass: null,
    coverage: completeCoverage,
    buckets: [
      { startUtc: '2026-09-21T00:00:00Z', endUtc: '2026-09-21T01:00:00Z' },
      { startUtc: '2026-09-21T01:00:00Z', endUtc: '2026-09-21T02:00:00Z' },
    ],
    zones: [
      {
        zoneId,
        name: 'Gate apron',
        entryCounts: [3, 2],
        exitCounts: [1, 4],
        uniqueTrackCounts: [4, 4],
        occupancyAtStart: [0, 2],
        peakOccupancy: 5,
        peakOccupancyAtUtc: '2026-09-21T01:00:00Z',
        windowEntryCount: 5,
        windowExitCount: 5,
        windowUniqueTrackCount: 6,
        repeatedVisitTrackCount: 2,
      },
    ],
    lines: [],
    classes: [{ objectClass: 'Person', counts: [4, 4], windowDistinctTrackCount: 6 }],
    ...overrides,
  };
}

/** The camera's scene, with the answer's revision enabling analytics or not. */
function sceneWith(revisionId: string, analyticsEnabled: boolean): CameraScene {
  return {
    cameraId,
    configured: true,
    activeRevision: null,
    history: [{
      revisionId, revisionNumber: 4, createdAtUtc: '2026-09-14T02:30:00Z', createdBy: 'operator', note: null,
      analyticsEnabled, zoneCount: 0, tripLineCount: 0,
    }],
  };
}

function render() {
  return renderWithApp(<AnalyticsPage />, {
    route: `/cameras/${cameraId}/analytics`,
    routePath: '/cameras/:cameraId/analytics',
  });
}

beforeEach(() => {
  vi.mocked(getCamera).mockResolvedValue(camera);
  vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' } as never);
  vi.mocked(getAnalyticsAggregates).mockResolvedValue(answer());
  vi.mocked(getCameraScene).mockResolvedValue(sceneWith(completeCoverage.sceneRevisionId!, true));
});

describe('Analytics identity (§5, §14)', () => {
  const fallback = `Camera ${cameraId.slice(0, 8)}…`;
  const renderInShell = () => renderWithApp(<AnalyticsPage />, {
    route: `/cameras/${cameraId}/analytics`,
    routePath: '/cameras/:cameraId/analytics',
    shell: 'analytics',
  });

  /** `Cameras › {identity} › Analytics` in the bar and the title, the full GUID in neither. */
  async function expectCameraIdentity(identity: string) {
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByRole('link', { name: 'Cameras' })).toHaveAttribute('href', '/cameras');
    // The camera still links to its scene configuration while it is unresolved.
    expect(await within(crumbs).findByRole('link', { name: identity })).toHaveAttribute('href', `/cameras/${cameraId}/scene`);
    expect(within(crumbs).getByText('Analytics')).toHaveAttribute('aria-current', 'page');
    expect(crumbs.textContent).not.toContain(cameraId);
    await waitFor(() => expect(document.title).toBe(`Analytics — ${identity} — Cameras — MAVI`));
    expect(document.title).not.toContain(cameraId);
  }

  it('names a camera that is still loading by its shortened identifier, then by its code and name', async () => {
    let resolve: (value: typeof camera) => void = () => {};
    vi.mocked(getCamera).mockImplementation(() => new Promise((done) => { resolve = done; }));
    renderInShell();

    await expectCameraIdentity(fallback);
    await act(async () => { resolve(camera); });
    await expectCameraIdentity('CAM-01 · North Gate');
    expect(screen.queryByText(fallback)).not.toBeInTheDocument();
  });

  it.each([
    ['missing', new ApiError({ status: 404, code: 'camera_not_found', detail: 'Camera was not found.' })],
    ['unavailable', new ApiError({ status: 503, code: 'api_error', detail: 'Camera store unavailable.' })],
  ])('keeps the camera named by its identifier when it is %s', async (_, error) => {
    vi.mocked(getCamera).mockRejectedValue(error);
    renderInShell();

    await waitFor(() => expect(getCamera).toHaveBeenCalled());
    await expectCameraIdentity(fallback);
  });
});

describe('Analytics Workbench', () => {
  it('is one `.page` Workbench surface like every routed surface (S1e, D9)', async () => {
    const { container } = render();
    await screen.findByRole('link', { name: 'CAM-01 · North Gate' });
    const page = container.querySelector('section.page');
    expect(page).not.toBeNull();
    expect(page).toHaveClass('page--full', 'page--workspace');
    expect(container.querySelectorAll('section.page')).toHaveLength(1);
    expect(page?.querySelector('.workspace--workbench')).not.toBeNull();
  });

  it('names the camera and its analytics surface, and offers the way back to the scene', async () => {
    render();

    expect(await screen.findByRole('link', { name: /Scene configuration/i })).toHaveAttribute(
      'href',
      `/cameras/${cameraId}/scene`,
    );
    expect(await screen.findByRole('link', { name: 'CAM-01 · North Gate' })).toBeInTheDocument();
  });

  it('shows the bucket figures with their counting definition', async () => {
    render();

    expect(await screen.findByRole('table')).toBeInTheDocument();
    // The default metric counts distinct active Tracks.
    expect(screen.getByText('Distinct Person Tracks')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
    const inspector = screen.getByRole('complementary', { name: 'Analytics inspector' });
    expect(within(inspector).getByText('Not additive')).toBeInTheDocument();
    // Once in the metric's definition, once in the table's caption, which is
    // the same definition serving as the accessible name of the numbers.
    expect(within(inspector).getAllByText(/counts each Track once/i)).toHaveLength(2);
  });

  it('never presents the buckets of a non-additive metric as a total', async () => {
    render();
    await screen.findByRole('table');

    // The two buckets read 4 and 4; the window figure is 6, not 8, because two
    // Tracks span both buckets. A surface that summed the column would be wrong.
    expect(screen.queryByText('8')).not.toBeInTheDocument();
  });

  it('draws a complete scope holding no facts as the real zero it is', async () => {
    vi.mocked(getAnalyticsAggregates).mockResolvedValue(answer({
      zones: [],
      lines: [],
      classes: [{ objectClass: 'Person', counts: [0, 0], windowDistinctTrackCount: 0 }],
    }));
    render();

    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(screen.getByText('Coverage complete')).toBeInTheDocument();
    expect(screen.queryByText(/has been analysed/i)).not.toBeInTheDocument();
  });

  it('withholds figures for an incomplete scope rather than drawing them as an observation', async () => {
    vi.mocked(getAnalyticsAggregates).mockResolvedValue(answer({
      coverage: { ...completeCoverage, pendingRuns: 2, complete: false },
    }));
    render();

    expect(await screen.findByText(/Not every run in this window has been analysed/i)).toBeInTheDocument();
    // The chart and its semantic twin are both absent: there is no observation
    // to report, and an empty chart would claim the pending runs hold nothing.
    expect(screen.queryByRole('figure')).not.toBeInTheDocument();
    expect(screen.getByText('Coverage incomplete')).toBeInTheDocument();
    expect(screen.getByText(/2 runs not yet analysed/i)).toBeInTheDocument();
  });

  it('distinguishes a camera with no scene from a camera with nothing to report', async () => {
    vi.mocked(getAnalyticsAggregates).mockResolvedValue(answer({
      sceneRevisionId: null,
      sceneRevisionNumber: null,
      zones: [],
      lines: [],
      classes: [],
    }));
    render();

    // The stage says it, and says what to do about it. The inspector's
    // provenance row says the same words for a different reason, so the two are
    // told apart by where they are.
    expect(await screen.findByText('No scene configured', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Configure the scene/i })).toBeInTheDocument();
  });

  it('calls a camera with no scene not configured, never coverage incomplete (F25)', async () => {
    vi.mocked(getAnalyticsAggregates).mockResolvedValue(answer({
      sceneRevisionId: null,
      sceneRevisionNumber: null,
      coverage: { ...completeCoverage, sceneRevisionId: null, evaluatedRuns: 0, notConfiguredRuns: 3, complete: false },
      zones: [],
      lines: [],
      classes: [],
    }));
    render();

    const stage = (await screen.findByText('No scene configured', { selector: '.empty strong' })).closest('.empty');
    expect(stage).toHaveClass('empty--hatched');
    // The Context Bar names the condition rather than a shortfall Processing could fix.
    expect(screen.getByText('No scene configured', { selector: '.badge, .badge *' })).toBeInTheDocument();
    expect(screen.queryByText('Coverage incomplete')).not.toBeInTheDocument();
    const strip = screen.getByRole('region', { name: 'Analytics coverage' });
    expect(within(strip).queryByRole('link', { name: 'Processing' })).not.toBeInTheDocument();
  });

  it('calls a scope analysed against an earlier revision stale, and still offers Processing (F25)', async () => {
    vi.mocked(getAnalyticsAggregates).mockResolvedValue(answer({
      coverage: { ...completeCoverage, staleRuns: 1, complete: false },
    }));
    render();

    expect(await screen.findByText('Coverage stale')).toBeInTheDocument();
    const strip = screen.getByRole('region', { name: 'Analytics coverage' });
    expect(within(strip).getByRole('link', { name: 'Processing' })).toHaveAttribute('href', '/processing');
  });

  it('states the display timezone once, in the Context Bar (§24)', async () => {
    render();
    await screen.findByRole('table');

    const zones = screen.getAllByText('Asia/Kolkata');
    expect(zones).toHaveLength(1);
    expect(zones[0].closest('.context-bar')).not.toBeNull();
  });

  it('asks the question in one band and sets the window in another (F22)', async () => {
    render();
    await screen.findByRole('table');

    const question = screen.getByRole('group', { name: 'Analytics question' });
    expect(within(question).getByRole('group', { name: 'Analytics mode' })).toBeInTheDocument();
    expect(within(question).getByLabelText('Metric')).toBeInTheDocument();
    expect(within(question).getByRole('button', { name: /Refresh/i })).toBeInTheDocument();

    const window = screen.getByRole('group', { name: 'Analytics window' });
    expect(within(window).getByRole('group', { name: 'Window presets' })).toBeInTheDocument();
    expect(within(window).getByLabelText('From')).toBeInTheDocument();
    expect(within(window).getByLabelText('To')).toBeInTheDocument();
    expect(within(window).getByLabelText('Interval')).toBeInTheDocument();
    expect(within(window).getByLabelText('Object class')).toBeInTheDocument();
  });

  it('marks the field that repairs a refused window, and says why Refresh is unavailable (F22)', async () => {
    render();
    await screen.findByRole('table');

    await userEvent.selectOptions(screen.getByLabelText('Interval'), '60');
    await userEvent.clear(screen.getByLabelText('From'));
    await userEvent.type(screen.getByLabelText('From'), '2026-08-01T00:00');
    await screen.findByText(/Adjust the window/i);

    const interval = screen.getByLabelText('Interval');
    expect(interval).toHaveAttribute('aria-invalid', 'true');
    expect(interval).toHaveAccessibleDescription(/the most that can be shown is 512/i);
    expect(screen.getByLabelText('From')).not.toHaveAttribute('aria-invalid');
    const refresh = screen.getByRole('button', { name: /Refresh/i });
    expect(refresh).toBeDisabled();
    expect(refresh).toHaveAttribute('title', 'Adjust the window before refreshing.');
  });

  it('keeps the figures and Not additive in view, and the definition and provenance one step away (F23)', async () => {
    render();
    const inspector = await screen.findByRole('complementary', { name: 'Analytics inspector' });
    await within(inspector).findByRole('table');

    expect(within(inspector).getByText('Not additive')).toBeVisible();
    const disclosures = [...inspector.querySelectorAll('details')];
    expect(disclosures.map((d) => d.querySelector('summary')?.textContent)).toEqual(['How this is counted', 'Provenance']);
    expect(disclosures.every((d) => !d.open)).toBe(true);
    expect(within(disclosures[1]).getByText('Scene revision')).toBeInTheDocument();
    // Sections inside the one inspector, not panels inside it (§11).
    expect(inspector.querySelector('.panel, .card')).toBeNull();
  });

  it('labels each bucket with a compact time, without seconds (F24)', async () => {
    render();
    const table = await screen.findByRole('table');

    const rowHeaders = within(table).getAllByRole('rowheader');
    expect(rowHeaders).toHaveLength(2);
    for (const header of rowHeaders) expect(header.textContent).not.toMatch(/:\d{2}:\d{2}/);
  });

  it('says analytics are disabled for a window with no runs under a disabled revision (Codex P1)', async () => {
    // No runs: the server counts no disabled run, and the coverage reads complete.
    vi.mocked(getAnalyticsAggregates).mockResolvedValue(answer({
      coverage: { ...completeCoverage, evaluatedRuns: 0, analysedTracks: 0 },
      zones: [],
      lines: [],
      classes: [{ objectClass: 'Person', counts: [0, 0], windowDistinctTrackCount: 0 }],
    }));
    vi.mocked(getCameraScene).mockResolvedValue(sceneWith(completeCoverage.sceneRevisionId!, false));
    render();

    const stage = (await screen.findByText('Analytics disabled by the scene', { selector: '.empty strong' })).closest('.empty');
    expect(stage).toHaveClass('empty--hatched');
    expect(screen.getByText('Analytics disabled')).toBeInTheDocument();
    expect(screen.queryByText('Coverage complete')).not.toBeInTheDocument();
    expect(screen.queryByRole('figure')).not.toBeInTheDocument();
  });

  it('still draws a complete zero when the scene cannot be read (Codex P1)', async () => {
    // The scene decides only when it says "disabled"; unread, the counters do.
    vi.mocked(getAnalyticsAggregates).mockResolvedValue(answer({
      coverage: { ...completeCoverage, evaluatedRuns: 0, analysedTracks: 0 },
      zones: [],
      lines: [],
      classes: [{ objectClass: 'Person', counts: [0, 0], windowDistinctTrackCount: 0 }],
    }));
    vi.mocked(getCameraScene).mockRejectedValue(new Error('scene unavailable'));
    render();

    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(screen.getByText('Coverage complete')).toBeInTheDocument();
  });

  it('gives each compact bucket time its full form on hover (§24, Codex P2)', async () => {
    render();
    const table = await screen.findByRole('table');

    const first = within(table).getAllByRole('rowheader')[0].querySelector('time');
    expect(first).toHaveAttribute('datetime', '2026-09-21T00:00:00Z');
    // Seconds and year present in the full form.
    expect(first?.getAttribute('title')).toMatch(/2026.*05:30:00/);
  });

  it('says a camera is missing rather than showing an empty surface', async () => {
    vi.mocked(getAnalyticsAggregates).mockRejectedValue(
      new ApiError({ status: 404, code: 'camera_not_found', detail: 'Camera was not found.' }),
    );
    render();

    expect(await screen.findByText(/This camera does not exist/i)).toBeInTheDocument();
  });

  it('offers a retry when analytics could not be read at all', async () => {
    vi.mocked(getAnalyticsAggregates).mockRejectedValue(
      new ApiError({ status: 503, code: 'analytics_evidence_unreadable', detail: 'Evidence could not be read.' }),
    );
    render();

    expect(await screen.findByRole('alert')).toHaveTextContent('Evidence could not be read.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('refuses a window the contract could not transport, before asking for it', async () => {
    vi.mocked(getAnalyticsAggregates).mockClear();
    render();
    await screen.findByRole('table');
    const calls = vi.mocked(getAnalyticsAggregates).mock.calls.length;

    await userEvent.selectOptions(screen.getByLabelText('Interval'), '60');
    await userEvent.clear(screen.getByLabelText('From'));
    await userEvent.type(screen.getByLabelText('From'), '2026-08-01T00:00');

    expect(await screen.findByText(/Adjust the window/i)).toBeInTheDocument();
    // The advice sits on the field that is repaired, not only on the stage.
    expect(screen.getByText(/the most that can be shown is/i)).toBeInTheDocument();
    // The refused question was never put to the server.
    expect(vi.mocked(getAnalyticsAggregates).mock.calls.length).toBe(calls);
  });

  it('will not let manual Refresh ask a question the contract would refuse', async () => {
    // The automatic path is gated on the query being executable, but TanStack
    // Query's imperative refetch() ignores `enabled`. Without the same gate on
    // the manual path the surface promises "a question the contract will refuse
    // is not asked" and then asks it anyway the moment Refresh is pressed.
    vi.mocked(getAnalyticsAggregates).mockClear();
    render();
    await screen.findByRole('table');

    await userEvent.selectOptions(screen.getByLabelText('Interval'), '60');
    await userEvent.clear(screen.getByLabelText('From'));
    await userEvent.type(screen.getByLabelText('From'), '2026-08-01T00:00');
    expect(await screen.findByText(/Adjust the window/i)).toBeInTheDocument();

    // The contract first: what must not happen is the request. Asserted on the
    // query function itself, not on rendered text, and proven to fail against
    // the pre-repair head (it issued a second call).
    const refresh = screen.getByRole('button', { name: /Refresh/i });
    const calls = vi.mocked(getAnalyticsAggregates).mock.calls.length;
    await userEvent.click(refresh);
    expect(vi.mocked(getAnalyticsAggregates).mock.calls.length).toBe(calls);

    // Then the affordance: a control that silently does nothing is worse than
    // one that says it cannot act, so the button carries the refusal too.
    expect(refresh).toBeDisabled();

    // And the refusal is still on screen and still true afterwards.
    expect(screen.getByText(/Adjust the window/i)).toBeInTheDocument();
  });

  it('still refreshes an ordinary valid query', async () => {
    // The complement: the gate must refuse refused questions, not Refresh.
    render();
    await screen.findByRole('table');

    const refresh = screen.getByRole('button', { name: /Refresh/i });
    expect(refresh).toBeEnabled();

    const calls = vi.mocked(getAnalyticsAggregates).mock.calls.length;
    await userEvent.click(refresh);

    await waitFor(() =>
      expect(vi.mocked(getAnalyticsAggregates).mock.calls.length).toBeGreaterThan(calls));
  });

  it('will not stamp figures with a timezone it does not have', async () => {
    // Every number here is stamped with an instant. Formatting them against a
    // guessed UTC would present a wall-clock time the operator does not live in
    // as a fact about when something happened.
    vi.mocked(getSystemConfig).mockRejectedValue(new Error('config unavailable'));
    render();

    expect(await screen.findByRole('alert')).toHaveTextContent(/display timezone is unavailable/i);
    expect(screen.queryByRole('figure')).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('keeps the last answer on screen when a refresh fails, and says it may be stale', async () => {
    render();
    await screen.findByRole('table');

    vi.mocked(getAnalyticsAggregates).mockRejectedValue(new Error('network'));
    await userEvent.click(screen.getByRole('button', { name: /Refresh/i }));

    await waitFor(() => expect(screen.getByText(/may no longer be current/i)).toBeInTheDocument());
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});
