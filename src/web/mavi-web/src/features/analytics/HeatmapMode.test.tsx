import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getAnalyticsAggregates,
  getAnalyticsHeatmap,
  type AnalyticsHeatmapResponse,
} from '../../api/analytics';
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
  return { ...actual, getAnalyticsAggregates: vi.fn(), getAnalyticsHeatmap: vi.fn() };
});

const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';

const camera = {
  id: cameraId, code: 'CAM-01', name: 'North Gate', description: null, locationName: null,
  timeZoneId: 'Asia/Kolkata', isActive: true,
  createdAtUtc: '2026-09-14T02:30:00Z', updatedAtUtc: '2026-09-14T02:30:00Z',
};

const coverage: AnalyticsCoverage = {
  sceneRevisionId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21481',
  algorithmVersion: 'scene-analytics-v1',
  evaluatedRuns: 2,
  pendingRuns: 0,
  failedRuns: 0,
  notConfiguredRuns: 0,
  disabledRuns: 0,
  staleRuns: 0,
  analysedTracks: 7,
  unavailableTracks: 0,
  complete: true,
};

function map(overrides: Partial<AnalyticsHeatmapResponse> = {}): AnalyticsHeatmapResponse {
  // A 4x3 grid, so a test can name an exact cell.
  const values = new Array(12).fill(0);
  values[1] = 2;
  values[9] = 6;
  return {
    cameraId,
    sceneRevisionId: coverage.sceneRevisionId,
    sceneRevisionNumber: 4,
    algorithmVersion: 'scene-analytics-v1',
    snapshotVisibilitySequence: 31,
    fromUtc: '2026-09-21T00:00:00Z',
    toUtc: '2026-09-21T02:00:00Z',
    objectClass: null,
    processingRunId: null,
    coverage,
    gridWidth: 4,
    gridHeight: 3,
    sampleCount: 8,
    trackCount: 3,
    maxCellValue: 6,
    values,
    ...overrides,
  };
}

async function openHeatmap() {
  renderWithApp(<AnalyticsPage />, {
    route: `/cameras/${cameraId}/analytics`,
    routePath: '/cameras/:cameraId/analytics',
  });
  await userEvent.click(await screen.findByRole('button', { name: 'Heatmap' }));
}

beforeEach(() => {
  vi.mocked(getCamera).mockResolvedValue(camera);
  vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' } as never);
  // Activity is the mode the surface opens in, so its answer has to be a whole
  // one even in a test about the heatmap.
  vi.mocked(getAnalyticsAggregates).mockResolvedValue({
    cameraId,
    sceneRevisionId: coverage.sceneRevisionId,
    sceneRevisionNumber: 4,
    algorithmVersion: 'scene-analytics-v1',
    snapshotVisibilitySequence: 31,
    fromUtc: '2026-09-21T00:00:00Z',
    toUtc: '2026-09-21T02:00:00Z',
    bucketSeconds: 3_600,
    objectClass: null,
    coverage,
    buckets: [{ startUtc: '2026-09-21T00:00:00Z', endUtc: '2026-09-21T01:00:00Z' }],
    zones: [],
    lines: [],
    classes: [{ objectClass: 'Person' as const, counts: [3], windowDistinctTrackCount: 3 }],
  });
  vi.mocked(getAnalyticsHeatmap).mockResolvedValue(map());
});

describe('Heatmap mode', () => {
  it('summarises the map instead of enumerating its cells', async () => {
    await openHeatmap();

    const summary = await screen.findByRole('region', { name: 'Heatmap summary' });
    expect(summary).toHaveTextContent('4 by 3 grid');
    expect(summary).toHaveTextContent('8 samples from 3 Tracks');
    // Cell 9 of a 4x3 grid is row 2, column 1: the lower third, the left third.
    expect(summary).toHaveTextContent('busiest cell holds 6 samples, lower left of the frame');

    // The matrix itself is hidden: 12 rectangles here, but 9,216 at the largest
    // supported grid, and none of them says anything on its own.
    expect(document.querySelector('.heatmap__matrix')).toHaveAttribute('aria-hidden', 'true');
  });

  it('says in words that this is sample density, not people and not probability', async () => {
    await openHeatmap();

    const inspector = await screen.findByRole('complementary', { name: 'Analytics inspector' });
    expect(inspector).toHaveTextContent('trajectory sample density');
    expect(inspector).toHaveTextContent(/not people density/i);
    expect(inspector).toHaveTextContent(/not a probability or a prediction/i);
  });

  it('gives the legend numeric endpoints, because the scale is relative to this answer', async () => {
    await openHeatmap();

    const legend = (await screen.findByText('0 samples')).closest('ul')!;
    expect(within(legend).getByText('0 samples')).toBeInTheDocument();
    expect(within(legend).getByText('6 samples')).toBeInTheDocument();
  });

  it('has a real opacity control rather than a fixed blend', async () => {
    await openHeatmap();

    const opacity = await screen.findByLabelText('Opacity');
    expect(opacity).toHaveValue('75');

    // A real control: moving it changes the composite and says where it is.
    fireEvent.change(opacity, { target: { value: '40' } });
    expect(opacity).toHaveValue('40');
    expect(screen.getByText('40%')).toBeInTheDocument();
    expect(document.querySelector('.heatmap__matrix')).toHaveStyle({ opacity: '0.4' });
  });

  it('draws no cell where nothing was measured', async () => {
    await openHeatmap();
    await screen.findByRole('region', { name: 'Heatmap summary' });

    // Two of the twelve cells hold samples; the other ten are absent, not
    // painted with the bottom of the scale, so "nothing here" stays nothing.
    expect(document.querySelectorAll('.heatmap__cell')).toHaveLength(2);
  });

  it('is not refused by the aggregate bucket bound, which it has no interval for', async () => {
    // A 60-second interval over a long window overflows Activity's axis. The
    // heatmap takes no interval at all, so the same window is a perfectly good
    // question for it and must still be asked.
    renderWithApp(<AnalyticsPage />, {
      route: `/cameras/${cameraId}/analytics`,
      routePath: '/cameras/:cameraId/analytics',
    });
    await screen.findByRole('button', { name: 'Heatmap' });

    await userEvent.selectOptions(screen.getByLabelText('Interval'), '60');
    await userEvent.clear(screen.getByLabelText('From'));
    await userEvent.type(screen.getByLabelText('From'), '2026-08-01T00:00');
    expect(await screen.findByText(/Adjust the window/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Heatmap' }));

    expect(await screen.findByRole('region', { name: 'Heatmap summary' })).toBeInTheDocument();
    expect(screen.queryByText(/Adjust the window/i)).not.toBeInTheDocument();
  });

  it('says which bound a refused scope exceeded and offers a narrower window', async () => {
    vi.mocked(getAnalyticsHeatmap).mockRejectedValue(new ApiError({
      status: 422,
      code: 'analytics_heatmap_scope_too_large',
      detail: 'too large',
      extensions: { dimension: 'candidateTracks', limit: 2_000 },
    }));
    await openHeatmap();

    expect(await screen.findByText(/This window covers too much to map/i)).toBeInTheDocument();
    expect(screen.getByText(/more than 2,000 analysed Tracks/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Use the last hour/i })).toBeInTheDocument();
  });

  it('refuses to draw a partial map when evidence could not be read', async () => {
    vi.mocked(getAnalyticsHeatmap).mockRejectedValue(new ApiError({
      status: 503,
      code: 'analytics_evidence_unreadable',
      detail: 'Trajectory evidence for an analysed Track could not be read.',
    }));
    await openHeatmap();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/where the readable files went, not where anything went/i);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('draws no map at all for an incomplete scope', async () => {
    vi.mocked(getAnalyticsHeatmap).mockResolvedValue(map({
      coverage: { ...coverage, pendingRuns: 3, complete: false },
    }));
    await openHeatmap();

    expect(await screen.findByText(/Not every run in this window has been analysed/i)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Heatmap summary' })).not.toBeInTheDocument();
  });

  it('reports a complete window that simply held nothing as exactly that', async () => {
    vi.mocked(getAnalyticsHeatmap).mockResolvedValue(map({
      values: new Array(12).fill(0), sampleCount: 0, trackCount: 0, maxCellValue: 0,
    }));
    await openHeatmap();

    const summary = await screen.findByRole('region', { name: 'Heatmap summary' });
    expect(summary).toHaveTextContent('No samples fell inside this window.');
    expect(document.querySelectorAll('.heatmap__cell')).toHaveLength(0);
  });
});
