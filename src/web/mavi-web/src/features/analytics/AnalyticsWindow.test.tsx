import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getAnalyticsAggregates,
  getAnalyticsHeatmap,
  type AnalyticsAggregateResponse,
  type AnalyticsHeatmapResponse,
} from '../../api/analytics';
import { getCamera } from '../../api/cameras';
import { getCameraScene } from '../../api/scene';
import { getSystemConfig } from '../../api/system';
import type { AnalyticsCoverage } from '../../api/tracks';
import { renderWithApp } from '../../test/renderWithApp';
import AnalyticsPage from './AnalyticsPage';

/*
 * The analytical window as the operator sees it and as the server is asked it
 * (cold review, PR #198). Two rules:
 *
 * - The question on screen and the question executed are the same question. A
 *   From/To draft that is not a whole, unambiguous wall time in the configured
 *   zone refuses the query exactly as a refused window does — Refresh, the
 *   automatic fetch and a mode switch alike — and the previous committed window
 *   is never asked in its place.
 * - §24: a wall-time field is typed in the product's own format, which is
 *   stated beside it with the operative zone, never the browser's locale form.
 *
 * Every assertion here is on what reached the API, not only on what is shown.
 */

vi.mock('../../api/cameras', () => ({ getCamera: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/scene', async () => {
  const actual = await vi.importActual<typeof import('../../api/scene')>('../../api/scene');
  return { ...actual, getCameraScene: vi.fn() };
});
vi.mock('../../api/analytics', async () => {
  const actual = await vi.importActual<typeof import('../../api/analytics')>('../../api/analytics');
  return { ...actual, getAnalyticsAggregates: vi.fn(), getAnalyticsHeatmap: vi.fn() };
});

const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';
const revisionId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21481';

// Only the clock is fixed, so the initial window is known exactly: the last 24
// hours, snapped down to a whole 15 minutes.
const NOW = new Date('2026-10-09T10:07:00Z');
const FROM_UTC = '2026-10-08T10:00:00.000Z';
const TO_UTC = '2026-10-09T10:00:00.000Z';

const coverage: AnalyticsCoverage = {
  sceneRevisionId: revisionId,
  algorithmVersion: 'scene-analytics-v1',
  evaluatedRuns: 2,
  pendingRuns: 0,
  failedRuns: 0,
  notConfiguredRuns: 0,
  disabledRuns: 0,
  staleRuns: 0,
  analysedTracks: 5,
  unavailableTracks: 0,
  complete: true,
};

const aggregates: AnalyticsAggregateResponse = {
  cameraId,
  sceneRevisionId: revisionId,
  sceneRevisionNumber: 4,
  algorithmVersion: 'scene-analytics-v1',
  snapshotVisibilitySequence: 7,
  fromUtc: FROM_UTC,
  toUtc: TO_UTC,
  bucketSeconds: 900,
  objectClass: null,
  coverage,
  buckets: [{ startUtc: FROM_UTC, endUtc: '2026-10-08T10:15:00.000Z' }],
  zones: [],
  lines: [],
  classes: [{ objectClass: 'Person', counts: [5], windowDistinctTrackCount: 5 }],
};

const heatmap: AnalyticsHeatmapResponse = {
  cameraId,
  sceneRevisionId: revisionId,
  sceneRevisionNumber: 4,
  algorithmVersion: 'scene-analytics-v1',
  snapshotVisibilitySequence: 7,
  fromUtc: FROM_UTC,
  toUtc: TO_UTC,
  objectClass: null,
  processingRunId: null,
  coverage,
  gridWidth: 4,
  gridHeight: 3,
  sampleCount: 2,
  trackCount: 1,
  maxCellValue: 2,
  values: [0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
};

const aggregateCalls = () => vi.mocked(getAnalyticsAggregates).mock.calls;
const heatmapCalls = () => vi.mocked(getAnalyticsHeatmap).mock.calls;
const from = () => screen.getByLabelText('From') as HTMLInputElement;
const to = () => screen.getByLabelText('To') as HTMLInputElement;
const refresh = () => screen.getByRole('button', { name: /Refresh/i });

async function settled() {
  renderWithApp(<AnalyticsPage />, {
    route: `/cameras/${cameraId}/analytics`,
    routePath: '/cameras/:cameraId/analytics',
  });
  await screen.findByRole('table');
}

/** Replace a field's text the way an operator does: select it, type over it. */
async function retype(field: HTMLInputElement, text: string) {
  await userEvent.clear(field);
  if (text) await userEvent.type(field, text);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  vi.mocked(getCamera).mockResolvedValue({
    id: cameraId, code: 'CAM-01', name: 'North Gate', description: null, locationName: null,
    timeZoneId: 'Asia/Kolkata', isActive: true, createdAtUtc: '2026-09-14T02:30:00Z', updatedAtUtc: '2026-09-14T02:30:00Z',
  });
  vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' } as never);
  vi.mocked(getCameraScene).mockResolvedValue({
    cameraId, configured: true, activeRevision: null,
    history: [{
      revisionId, revisionNumber: 4, createdAtUtc: '2026-09-14T02:30:00Z', createdBy: 'operator', note: null,
      analyticsEnabled: true, zoneCount: 1, tripLineCount: 0,
    }],
  });
  vi.mocked(getAnalyticsAggregates).mockReset().mockResolvedValue(aggregates);
  vi.mocked(getAnalyticsHeatmap).mockReset().mockResolvedValue(heatmap);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('an invalid From/To draft refuses the query (cold review F2)', () => {
  it('asks the committed window first, in UTC', async () => {
    await settled();
    expect(aggregateCalls()).toHaveLength(1);
    expect(aggregateCalls()[0][1]).toMatchObject({ fromUtc: FROM_UTC, toUtc: TO_UTC, bucketSeconds: 900 });
  });

  it('will not refresh the previous window while From is empty', async () => {
    await settled();

    await retype(from(), '');
    expect(from()).toHaveAttribute('aria-invalid', 'true');
    expect(refresh()).toBeDisabled();
    await userEvent.click(refresh());

    // The old window, which is no longer the question on screen, is not asked.
    expect(aggregateCalls()).toHaveLength(1);
    // Nor is its answer presented as the answer to the invalid one.
    expect(screen.getByText('Adjust the window')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('treats a partly typed time as no time', async () => {
    await settled();

    await retype(from(), '2026-10-0');
    expect(from()).toHaveAttribute('aria-invalid', 'true');
    expect(refresh()).toBeDisabled();
    expect(aggregateCalls()).toHaveLength(1);
  });

  it('refuses a wall time that does not exist in the configured zone', async () => {
    // Europe/London springs forward at 01:00 on 29 March 2026: 01:30 never happens.
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Europe/London' } as never);
    await settled();

    await retype(from(), '2026-03-29 01:30:00');
    expect(from()).toHaveAttribute('aria-invalid', 'true');
    expect(from()).toHaveAccessibleDescription(/does not exist in the configured timezone/);
    expect(refresh()).toBeDisabled();
    await userEvent.click(refresh());
    expect(aggregateCalls()).toHaveLength(1);
  });

  it('refuses a wall time that is ambiguous in the configured zone', async () => {
    // Europe/London falls back at 02:00 on 25 October 2026: 01:30 happens twice.
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Europe/London' } as never);
    await settled();

    await retype(from(), '2026-10-25 01:30:00');
    expect(from()).toHaveAttribute('aria-invalid', 'true');
    expect(from()).toHaveAccessibleDescription(/ambiguous in the configured timezone/);
    expect(refresh()).toBeDisabled();
    await userEvent.click(refresh());
    expect(aggregateCalls()).toHaveLength(1);
  });

  it('will not switch to the heatmap and ask it the previous window', async () => {
    await settled();

    await retype(from(), '');
    await userEvent.click(screen.getByRole('button', { name: 'Heatmap' }));

    expect(screen.getByText('Adjust the window')).toBeInTheDocument();
    expect(heatmapCalls()).toHaveLength(0);
    expect(refresh()).toBeDisabled();
  });

  it('asks the corrected window once, in UTC, and Refresh asks it again', async () => {
    await settled();

    await retype(from(), '');
    // Pasted whole: the correction is one edit, so the count is the product's,
    // not an artefact of the test client's zero staleTime between keystrokes.
    from().focus();
    await userEvent.paste('2026-10-08 12:00:00');

    // 12:00 in Asia/Kolkata is 06:30 UTC; the To bound is unchanged.
    await waitFor(() => expect(aggregateCalls()).toHaveLength(2));
    expect(aggregateCalls()[1][1]).toMatchObject({ fromUtc: '2026-10-08T06:30:00.000Z', toUtc: TO_UTC });
    expect(from()).not.toHaveAttribute('aria-invalid');
    await screen.findByRole('table');

    expect(refresh()).toBeEnabled();
    await userEvent.click(refresh());
    await waitFor(() => expect(aggregateCalls()).toHaveLength(3));
    expect(aggregateCalls()[2][1]).toMatchObject({ fromUtc: '2026-10-08T06:30:00.000Z', toUtc: TO_UTC });
  });

  it('keeps a time as it is typed, and asks no window but the one typed', async () => {
    await settled();

    // Typed key by key: `12:00` is already a whole wall time and commits, and
    // the seconds that follow must land after it, not after a rewritten value.
    await retype(from(), '2026-10-08 12:00:00');
    expect(from()).toHaveValue('2026-10-08 12:00:00');
    expect(from()).not.toHaveAttribute('aria-invalid');
    await screen.findByRole('table');
    for (const call of aggregateCalls()) {
      expect([FROM_UTC, '2026-10-08T06:30:00.000Z']).toContain(call[1].fromUtc);
      expect(call[1].toUtc).toBe(TO_UTC);
    }
  });

  it('keeps an invalid To as the operator left it when From is committed (§21)', async () => {
    await settled();

    await retype(to(), '2026-10-09 1');
    expect(to()).toHaveAttribute('aria-invalid', 'true');
    from().focus();
    await userEvent.clear(from());
    await userEvent.paste('2026-10-08 12:00:00');

    // From committed; To still holds what was typed, still refuses the query.
    expect(to()).toHaveValue('2026-10-09 1');
    expect(to()).toHaveAttribute('aria-invalid', 'true');
    expect(refresh()).toBeDisabled();
    expect(aggregateCalls()).toHaveLength(1);
  });

  it('lets a preset replace the invalid draft, even when it names the same window', async () => {
    await settled();

    await retype(from(), '');
    expect(refresh()).toBeDisabled();

    // The same 15-minute step as the initial window: the committed window does
    // not change, so only the preset itself can restore the draft.
    await userEvent.click(within(screen.getByRole('group', { name: 'Window presets' })).getByRole('button', { name: 'Last 24 hours' }));

    expect(from()).toHaveValue('2026-10-08 15:30:00');
    expect(from()).not.toHaveAttribute('aria-invalid');
    expect(refresh()).toBeEnabled();
    expect(await screen.findByRole('table')).toBeInTheDocument();
    // No request for a window the operator never saw.
    for (const call of aggregateCalls()) expect(call[1]).toMatchObject({ fromUtc: FROM_UTC, toUtc: TO_UTC });
  });

  it('also refuses an invalid To draft', async () => {
    await settled();

    await retype(to(), '2026-13-01 00:00:00');
    expect(to()).toHaveAttribute('aria-invalid', 'true');
    expect(refresh()).toBeDisabled();
    await userEvent.click(refresh());
    expect(aggregateCalls()).toHaveLength(1);
  });
});

describe('wall-time fields state their format and zone (§24, cold review F3)', () => {
  it('shows each bound in the product format, never the browser\'s locale form', async () => {
    await settled();

    expect(from()).toHaveAttribute('type', 'text');
    expect(from()).toHaveValue('2026-10-08 15:30:00');
    expect(to()).toHaveValue('2026-10-09 15:30:00');
  });

  it('states the format and the operative zone beside the fields, and describes both fields with it', async () => {
    await settled();

    const band = screen.getByRole('group', { name: 'Analytics window' });
    const note = within(band).getByText('YYYY-MM-DD HH:mm:ss', { exact: false }).closest('.analytics-window__format') as HTMLElement;
    expect(note).toBeVisible();
    expect(note).toHaveTextContent('Asia/Kolkata');
    expect(from()).toHaveAccessibleDescription(/YYYY-MM-DD HH:mm:ss.*Asia\/Kolkata/);
    expect(to()).toHaveAccessibleDescription(/YYYY-MM-DD HH:mm:ss.*Asia\/Kolkata/);
  });

  it('names the configured zone, not the browser\'s, when they differ', async () => {
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Europe/London' } as never);
    await settled();

    const band = screen.getByRole('group', { name: 'Analytics window' });
    expect(within(band).getByText('Europe/London', { exact: false })).toBeVisible();
    // 10:00 UTC on 8 October is 11:00 in London (BST).
    expect(from()).toHaveValue('2026-10-08 11:00:00');
  });

  it('never falls back to UTC when the configured zone is unavailable', async () => {
    vi.mocked(getSystemConfig).mockRejectedValue(new Error('config unavailable'));
    renderWithApp(<AnalyticsPage />, {
      route: `/cameras/${cameraId}/analytics`,
      routePath: '/cameras/:cameraId/analytics',
    });
    await screen.findAllByRole('alert');

    expect(from()).toBeDisabled();
    expect(to()).toBeDisabled();
    expect(from()).toHaveAccessibleDescription(/display timezone is unavailable/i);
    const band = screen.getByRole('group', { name: 'Analytics window' });
    expect(band).not.toHaveTextContent(/\bUTC\b/);
  });
});
