import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AnalyticsHeatmapResponse } from '../../api/analytics';
import type { SceneRevision } from '../../api/scene';
import type { TrackDetail } from '../../api/tracks';
import HeatmapInspector from '../analytics/HeatmapInspector';
import HeatmapStage from '../analytics/HeatmapStage';
import { geometryNames } from '../../shared/evidence/analyticsLabels';
import { formatDuration } from '../../shared/format/duration';
import contract from '../../../../../../tests/fixtures/scene-analytics/c1-operator-contract.json';
import { buildAnalyticsEvidence } from './analyticsEvidence';
import TrackAnalyticsExplanation from './TrackAnalyticsExplanation';

/*
 * Slice 7 corpus C1, the UI leg (plan §7).
 *
 * `c1-operator-contract.json` is not written by hand. The integration test
 * `SemanticAcceptanceTests.TheExplanationHeatmapAndOperatorContractCarryTheSameAnswer`
 * reads it back from the real HTTP API over the C1 world — one authored trajectory
 * through the real decoder, engine and fenced commit — and fails if the server's
 * bytes differ from it. So this suite drives the operator components with what the
 * server is proved to send, and asserts the same hand-derived answer the backend
 * trace asserts:
 *
 *   zone "Gate": one visit, entered and left, dwell bracketed to [4400, 4800] ms,
 *     not loitering;
 *   line "Kerb": two crossings, A→B ("inbound") at 1.2–1.4 s then B→A ("outbound")
 *     at 6.8–7.0 s;
 *   heading East ("Right" in the image-direction vocabulary), never stationary;
 *   heatmap: all 41 authored samples, one Track, binned by the frozen rule.
 *
 * The heatmap expectation is recomputed here from the authored path, in this
 * language, rather than read out of the contract — so the browser's view of the
 * matrix is checked against the path, not against itself.
 */

const detail = contract.trackDetail as unknown as TrackDetail;
const revision = contract.sceneRevision as unknown as SceneRevision;
const heatmap = contract.heatmap as unknown as AnalyticsHeatmapResponse;
const analytics = detail.analytics!;
const names = geometryNames(revision.zones, revision.tripLines, revision.revisionNumber);

/** The C1 authored path, restated from `SemanticAcceptanceTests.AuthoredPoints`. */
function authoredPoints(): [number, number][] {
  const lerp = (from: number, to: number, at: number, start: number, end: number) =>
    from + ((to - from) * (at - start)) / (end - start);
  const round6 = (value: number) => Math.round(value * 1e6) / 1e6;
  const points: [number, number][] = [];
  for (let t = 0; t <= 8000; t += 200) {
    const [x, y] = t <= 2000
      ? [0.25, lerp(0.8, 0.36, t, 0, 2000)]
      : t <= 5800
        ? [lerp(0.25, 0.28, t, 2000, 5800), lerp(0.36, 0.3, t, 2000, 5800)]
        : [lerp(0.28, 0.6, t, 6000, 8000), lerp(0.3, 0.78, t, 6000, 8000)];
    points.push([round6(x), round6(y)]);
  }
  return points;
}

/** The frozen binning rule: floor(v · extent), the closed far edge clamped in, row-major. */
function expectedMatrix(width: number, height: number): number[] {
  const cells = new Array<number>(width * height).fill(0);
  for (const [x, y] of authoredPoints()) {
    const column = Math.min(Math.floor(x * width), width - 1);
    const row = Math.min(Math.floor(y * height), height - 1);
    cells[row * width + column] += 1;
  }
  return cells;
}

describe('C1 through the operator contract', () => {
  it('is the analysed identity the facts were derived under', () => {
    expect(analytics.status).toBe('Analysed');
    expect(analytics.sceneRevisionId).toBe(revision.revisionId);
    expect(analytics.sceneRevisionNumber).toBe(1);
    expect(heatmap.sceneRevisionId).toBe(revision.revisionId);
    expect(heatmap.coverage.evaluatedRuns).toBe(1);
  });

  it('builds the evidence overlay the frozen rules predict', () => {
    const model = buildAnalyticsEvidence(analytics, revision);

    const gate = model.zones.find((zone) => zone.name === 'Gate')!;
    expect(gate.interacted).toBe(true);
    expect(gate.visitCount).toBe(1);

    const kerb = model.lines.find((line) => line.name === 'Kerb')!;
    expect(kerb.interacted).toBe(true);
    expect(kerb.crossingCount).toBe(2);

    // In time order, one each way, labelled with the operator's own words.
    expect(model.crossings.map((crossing) => crossing.directionLabel)).toEqual(['inbound', 'outbound']);
    expect(model.crossings[0].offsetMs).toBeGreaterThanOrEqual(1200);
    expect(model.crossings[0].offsetMs).toBeLessThanOrEqual(1400);
    expect(model.crossings[1].offsetMs).toBeGreaterThanOrEqual(6800);
    expect(model.crossings[1].offsetMs).toBeLessThanOrEqual(7000);
    // The persisted crossing point lies on the line y = 0.5, exactly as sealed.
    for (const crossing of model.crossings) expect(crossing.y).toBeCloseTo(0.5, 6);

    // One zone interval on the timeline and no stationary interval at all.
    expect(model.intervals).toHaveLength(1);
  });

  it('explains it to the operator in those terms', () => {
    render(
      <TrackAnalyticsExplanation
        analytics={analytics}
        scene={{ status: 'ready', revision, names }}
        geometry={names}
      />,
    );
    const panel = screen.getByRole('region', { name: 'Scene analytics' });

    expect(within(panel).getByText('Scene revision 1 · Engine v1')).toBeInTheDocument();

    const visit = analytics.zoneVisits[0];
    expect(visit.dwellMs).toBeGreaterThanOrEqual(4400);
    expect(visit.dwellMs).toBeLessThanOrEqual(4800);
    const zones = within(panel).getByText('Gate').closest('li')!;
    expect(zones).toHaveTextContent(`Gate · 1 visit · dwell ${formatDuration(visit.dwellMs)}`);
    expect(zones).not.toHaveTextContent('Loitering');

    const line = within(panel).getByText('Kerb').closest('li')!;
    expect(line).toHaveTextContent('Kerb · 2 crossings');
    const crossings = within(line).getAllByRole('listitem').map((item) => item.textContent ?? '');
    expect(crossings[0]).toMatch(/^inbound at /);
    expect(crossings[1]).toMatch(/^outbound at /);

    // The engine's East sector, in the operator's image-direction vocabulary — the
    // same vocabulary the Development real-worker run showed as "Up (image direction)".
    expect(panel).toHaveTextContent('Right (image direction)');
    expect(panel).toHaveTextContent('Never stationary');
  });

  it('draws the heatmap from exactly the authored samples', () => {
    const expected = expectedMatrix(heatmap.gridWidth, heatmap.gridHeight);
    const maximum = Math.max(...expected);

    expect(heatmap.values).toEqual(expected);
    expect(heatmap.sampleCount).toBe(41);
    expect(heatmap.trackCount).toBe(1);
    expect(heatmap.maxCellValue).toBe(maximum);

    render(<HeatmapStage response={heatmap} opacity={0.8} onOpacityChange={() => {}} />);
    const summary = screen.getByRole('region', { name: 'Heatmap summary' });
    expect(summary).toHaveTextContent(
      `Trajectory sample density over a ${heatmap.gridWidth} by ${heatmap.gridHeight} grid: 41 samples from 1 Track.`,
    );
    expect(summary).toHaveTextContent(`The busiest cell holds ${maximum} samples`);
  });

  it('states the heatmap provenance the explanation states', () => {
    render(<HeatmapInspector response={heatmap} displayTimeZoneId="UTC" />);
    expect(screen.getByText('Revision 1')).toBeInTheDocument();
    expect(screen.getByText('Engine v1')).toBeInTheDocument();
    expect(screen.getByText('41')).toBeInTheDocument();
  });
});
