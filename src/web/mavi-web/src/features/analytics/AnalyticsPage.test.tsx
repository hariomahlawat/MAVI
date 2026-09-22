import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAnalyticsAggregates, type AnalyticsAggregateResponse } from '../../api/analytics';
import { getCamera } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import type { AnalyticsCoverage } from '../../api/tracks';
import { renderWithApp } from '../../test/renderWithApp';
import AnalyticsPage from './AnalyticsPage';

vi.mock('../../api/cameras', () => ({ getCamera: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
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
});

describe('Analytics Workbench', () => {
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
