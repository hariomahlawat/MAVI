import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { getCameraScene, getCameraSceneRevision, type CameraScene } from '../../api/scene';
import { getSystemConfig } from '../../api/system';
import { getTrack, searchTracks, type AnalyticsCoverage, type TrackDetail, type TrackSearchItem } from '../../api/tracks';
import { listVideos } from '../../api/videos';
import { notConfiguredAnalytics } from '../../test/analyticsFixtures';
import { renderWithApp } from '../../test/renderWithApp';
import { reviewPath } from './TrackResultList';
import VisualSearchPage from './VisualSearchPage';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/scene', async () => {
  const actual = await vi.importActual<typeof import('../../api/scene')>('../../api/scene');
  return { ...actual, getCameraScene: vi.fn(), getCameraSceneRevision: vi.fn() };
});
vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, searchTracks: vi.fn(), getTrack: vi.fn() };
});
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});

const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';
const revisionId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21481';
const zoneId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21461';
const lineId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21471';
const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21451';

const camera = {
  id: cameraId, code: 'CAM-01', name: 'North Gate', description: null, locationName: null,
  timeZoneId: 'Asia/Kolkata', isActive: true, createdAtUtc: '2026-09-14T02:30:00Z', updatedAtUtc: '2026-09-14T02:30:00Z',
};

const scene: CameraScene = {
  cameraId,
  configured: true,
  activeRevision: {
    revisionId, revisionNumber: 4, cameraId, createdAtUtc: '2026-09-20T06:30:00Z', createdBy: 'development-unattributed',
    note: null, referenceFrameVideoAssetId: null, referenceFrameOffsetMs: null, analyticsEnabled: true,
    zones: [{ zoneId, name: 'Forecourt', kind: 'Restricted', enabled: true, vertices: [], loiteringThresholdSeconds: 120 }],
    tripLines: [{ lineId, name: 'Gate A', enabled: true, a: { x: 0.6, y: 0.4 }, b: { x: 0.9, y: 0.4 }, directed: true, aToBLabel: 'inbound', bToALabel: 'outbound' }],
  },
  history: [{ revisionId, revisionNumber: 4, createdAtUtc: '2026-09-20T06:30:00Z', createdBy: 'development-unattributed', note: null, analyticsEnabled: true, zoneCount: 1, tripLineCount: 1 }],
};

function coverage(overrides: Partial<AnalyticsCoverage> = {}): AnalyticsCoverage {
  return {
    sceneRevisionId: revisionId, algorithmVersion: 'scene-analytics-v1',
    evaluatedRuns: 2, pendingRuns: 1, failedRuns: 0, notConfiguredRuns: 0, disabledRuns: 1, staleRuns: 0,
    analysedTracks: 17, unavailableTracks: 2, complete: false, ...overrides,
  };
}

function item(overrides: Partial<TrackSearchItem> = {}): TrackSearchItem {
  return {
    id: trackId, processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431', videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
    cameraId, cameraCode: 'CAM-01', cameraName: 'North Gate', objectClass: 'Person',
    startTimestampUtc: '2026-09-14T02:30:00Z', endTimestampUtc: '2026-09-14T02:30:08Z', startOffsetMs: 10_000, endOffsetMs: 18_000,
    durationMs: 8_000, detectionCount: 32, meanConfidence: 0.91, maxConfidence: 0.97, reviewStatus: 'Unreviewed',
    thumbnailArtifactId: null, thumbnailContentUrl: null, videoContentUrl: '/api/videos/018f3f5a-2f70-7a2b-8a12-2d02f4c21421/content',
    analytics: { sceneRevisionId: revisionId, algorithmVersion: 'scene-analytics-v1', zones: [{ zoneId, visitCount: 2, totalDwellMs: 14_000, loitering: true }], lines: [], motion: null },
    ...overrides,
  };
}

function detail(): TrackDetail {
  const summary = item();
  return {
    id: trackId, processingRunId: summary.processingRunId, videoAssetId: summary.videoAssetId,
    camera: { id: cameraId, code: 'CAM-01', name: 'North Gate' }, objectClass: 'Person', localTrackNumber: 7,
    startOffsetMs: 10_000, endOffsetMs: 18_000, startTimestampUtc: summary.startTimestampUtc, endTimestampUtc: summary.endTimestampUtc,
    durationMs: 8_000, detectionCount: 32, meanConfidence: 0.91, maxConfidence: 0.97, reviewStatus: 'Unreviewed',
    processing: { pipelineVersion: 'phase1', detectorName: null, detectorVersion: null, trackerName: null, trackerVersion: null, completedAtUtc: '2026-09-14T02:40:00Z' },
    video: { recordingStartUtc: '2026-09-14T02:26:42Z', recordingEndUtc: '2026-09-14T02:36:42Z', durationMs: 600_000, width: 1920, height: 1080, frameRateNumerator: 25, frameRateDenominator: 1, videoContentUrl: summary.videoContentUrl },
    representative: null, trajectoryArtifactId: null, trajectoryContentUrl: null,
    analytics: notConfiguredAnalytics({
      sceneRevisionId: revisionId, sceneRevisionNumber: 4, status: 'Analysed', referencePoint: 'bbox-centre', sampleCount: 120, gapCount: 0, gapTotalMs: 0,
      zoneSummaries: [{ zoneId, visitCount: 2, totalDwellMs: 14_000, firstEntryTimestampUtc: '2026-09-14T02:30:01Z', lastExitTimestampUtc: '2026-09-14T02:30:07Z', loitering: true, loiteringThresholdSeconds: 120, loiteringDwellMs: 14_000 }],
      lineCrossings: [{ lineId, crossingIndex: 0, offsetMs: 2_000, timestampUtc: '2026-09-14T02:30:02Z', direction: 'aToB', pointX: 0.25, pointY: 0.5 }],
      motion: { heading: 'NE', pathLengthNormalised: 0.42, meanDisplacementRate: 0.01, longestStationaryMs: 2_500, totalStationaryMs: 2_500, stationaryIntervals: [], stationaryZoneIds: [] },
    }),
  };
}

function Location() {
  const location = useLocation();
  return <output aria-label="Current search location">{location.pathname + location.search}</output>;
}

describe('Slice 4 Investigation analytics', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(listCameras).mockResolvedValue([camera]);
    vi.mocked(listVideos).mockResolvedValue([]);
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' });
    vi.mocked(getCameraScene).mockResolvedValue(scene);
    vi.mocked(getCameraSceneRevision).mockResolvedValue(scene.activeRevision!);
    vi.mocked(searchTracks).mockResolvedValue({ items: [item()], nextCursor: null, analyticsCoverage: coverage() });
    vi.mocked(getTrack).mockResolvedValue(detail());
  });

  it('offers the Analytics group only once a camera scope resolves a scene, and names its geometry', async () => {
    const user = userEvent.setup();
    vi.mocked(searchTracks).mockResolvedValue({ items: [item({ analytics: undefined })], nextCursor: null });
    renderWithApp(<><Location /><VisualSearchPage /></>, { route: '/search' });
    await screen.findByRole('link', { name: 'Review evidence' });

    const group = screen.getByRole('region', { name: 'Analytics' });
    expect(within(group).getByText(/Choose a camera, video or processing run/)).toBeInTheDocument();
    expect(screen.getByLabelText('Zone')).toBeDisabled();
    expect(screen.getByLabelText('Motion direction')).toBeDisabled();
    expect(getCameraScene).not.toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText('Camera'), cameraId);
    await waitFor(() => expect(screen.getByLabelText('Zone')).toBeEnabled());
    expect(getCameraScene).toHaveBeenCalledWith(cameraId, expect.anything());
    expect(within(screen.getByLabelText('Zone')).getByRole('option', { name: 'Forecourt' })).toBeInTheDocument();
    expect(within(screen.getByLabelText('Trip line')).getByRole('option', { name: 'Gate A' })).toBeInTheDocument();

    // Dependents unlock with their parent; the line's own labels name its directions.
    expect(screen.getByLabelText('Zone relation')).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Zone'), zoneId);
    expect(screen.getByLabelText('Zone relation')).toBeEnabled();
    await user.selectOptions(screen.getByLabelText('Zone relation'), 'entered');
    await user.type(screen.getByLabelText('Minimum dwell (seconds)'), '2.5');
    await user.selectOptions(screen.getByLabelText('Trip line'), lineId);
    expect(within(screen.getByLabelText('Crossing direction')).getByRole('option', { name: 'inbound' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Crossing direction'), 'aToB');
    await user.selectOptions(screen.getByLabelText('Motion direction'), 'NE');
    expect(within(screen.getByLabelText('Motion direction')).getByRole('option', { name: 'Up-right' })).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: /Loitering/ }));
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(screen.getByLabelText('Current search location')).toHaveTextContent('zoneId='));
    const location = screen.getByLabelText('Current search location').textContent ?? '';
    expect(location).toContain(`cameraId=${cameraId}`);
    expect(location).toContain(`zoneId=${zoneId}&zoneRelation=entered&minDwellMs=2500`);
    expect(location).toContain(`lineId=${lineId}&crossingDirection=aToB`);
    expect(location).toContain('motionDirection=NE');
    expect(location).toContain('loitering=true');
    expect(vi.mocked(searchTracks).mock.calls.at(-1)?.[0]).toEqual(expect.objectContaining({
      cameraId, zoneId, zoneRelation: 'entered', minDwellMs: 2500, lineId, crossingDirection: 'aToB', motionDirection: 'NE', loitering: true,
    }));
  });

  it('clears the geometry draft when the camera changes, keeping generic intent', async () => {
    const user = userEvent.setup();
    const other = { ...camera, id: '018f3f5a-2f70-7a2b-8a12-2d02f4c21413', code: 'CAM-02', name: 'South Gate' };
    vi.mocked(listCameras).mockResolvedValue([camera, other]);
    renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&zoneId=${zoneId}&motionDirection=S` });
    await waitFor(() => expect(screen.getByLabelText('Zone')).toHaveValue(zoneId));
    await waitFor(() => expect(within(screen.getByLabelText('Camera')).getByRole('option', { name: /CAM-02/ })).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText('Camera'), other.id);

    expect(screen.getByLabelText('Zone')).toHaveValue('');
    expect(screen.getByLabelText('Motion direction')).toHaveValue('S');
  });

  it('shows analytic chips in operator words and removes dependents with their parent', async () => {
    const user = userEvent.setup();
    renderWithApp(<><Location /><VisualSearchPage /></>, {
      route: `/search?cameraId=${cameraId}&sceneRevisionId=${revisionId}&analyticsAlgorithmVersion=scene-analytics-v1&zoneId=${zoneId}&zoneRelation=exited&minDwellMs=2500&lineId=${lineId}&crossingDirection=bToA&motionDirection=NW&minStationaryMs=10000&loitering=true`,
    });
    const chips = await screen.findByRole('group', { name: 'Committed filters' });

    await waitFor(() => expect(within(chips).getByTitle(/^Exited:/)).toHaveTextContent('Forecourt'));
    expect(within(chips).getByTitle(/^Scene revision:/)).toHaveTextContent('Revision 4');
    expect(within(chips).getByTitle(/^Analytics engine:/)).toHaveTextContent('Engine v1');
    expect(within(chips).getByTitle(/^Minimum dwell:/)).toHaveTextContent('2.5 s');
    expect(within(chips).getByTitle(/^Crossed:/)).toHaveTextContent('Gate A · outbound');
    expect(within(chips).getByTitle(/^Moving:/)).toHaveTextContent('Up-left');
    expect(within(chips).getByTitle(/^Stationary for:/)).toHaveTextContent('10 s');
    expect(within(chips).getByTitle(/^Loitering:/)).toHaveTextContent('in the zone');

    await user.click(within(chips).getByRole('button', { name: 'Remove exited filter' }));

    await waitFor(() => expect(screen.getByLabelText('Current search location')).not.toHaveTextContent('zoneId='));
    const location = screen.getByLabelText('Current search location').textContent ?? '';
    expect(location).not.toContain('zoneRelation');
    expect(location).not.toContain('minDwellMs');
    expect(location).toContain('loitering=true');
    expect(location).toContain(`lineId=${lineId}`);

    await user.click(within(chips).getByRole('button', { name: 'Remove scene revision filter' }));
    await waitFor(() => expect(screen.getByLabelText('Current search location')).not.toHaveTextContent('analyticsAlgorithmVersion'));
  });

  it('shows a persistent coverage strip beneath the header naming every non-zero bucket and unavailable Tracks', async () => {
    renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&loitering=true` });

    const strip = await screen.findByRole('region', { name: 'Analytics coverage' });
    expect(strip).toHaveTextContent('2 of 4 runs analysed');
    expect(strip).toHaveTextContent('Revision 4 · Engine v1');
    expect(strip).toHaveTextContent('1 run not yet analysed · 1 run with analytics disabled by the scene revision');
    expect(strip).toHaveTextContent('17 Tracks analysed · 2 Tracks could not be analysed');
    expect(within(strip).getByRole('link', { name: 'Processing' })).toHaveAttribute('href', '/processing');
    // Beneath the header, inside the results column, not in the notices band.
    expect(strip.closest('.results')).not.toBeNull();
    expect(strip.previousElementSibling).toHaveClass('results__head');
  });

  it('says complete coverage is complete and needs no Processing link', async () => {
    vi.mocked(searchTracks).mockResolvedValue({
      items: [item()], nextCursor: null,
      analyticsCoverage: coverage({ evaluatedRuns: 3, pendingRuns: 0, disabledRuns: 0, unavailableTracks: 0, complete: true }),
    });
    renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&loitering=true` });

    const strip = await screen.findByRole('region', { name: 'Analytics coverage' });
    expect(strip).toHaveTextContent('All 3 runs analysed');
    expect(strip).toHaveClass('coverage--success');
    expect(within(strip).queryByRole('link', { name: 'Processing' })).not.toBeInTheDocument();
    expect(strip).not.toHaveTextContent('could not be analysed');
  });

  it('never renders incomplete analytics as ordinary zero matches', async () => {
    vi.mocked(searchTracks).mockResolvedValue({
      items: [], nextCursor: null, analyticsCoverage: coverage({ evaluatedRuns: 0, pendingRuns: 2, disabledRuns: 0, analysedTracks: 0, unavailableTracks: 0 }),
    });
    renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&loitering=true` });

    const empty = await screen.findByText('Not analysed yet.');
    expect(empty.closest('.empty')).toHaveClass('empty--hatched');
    expect(screen.queryByText('No Tracks matched this search.')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Analytics coverage' })).toHaveTextContent('2 runs not yet analysed');
  });

  it('distinguishes no scene, disabled analytics, partial and complete zero results', async () => {
    vi.mocked(searchTracks).mockResolvedValueOnce({
      items: [], nextCursor: null,
      analyticsCoverage: coverage({ sceneRevisionId: null, evaluatedRuns: 0, pendingRuns: 0, disabledRuns: 0, notConfiguredRuns: 3, analysedTracks: 0, unavailableTracks: 0 }),
    });
    const first = renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&loitering=true` });
    await screen.findByText('No scene configured for this camera.');
    expect(screen.getByRole('region', { name: 'Analytics coverage' })).toHaveTextContent('no scene configured');
    first.unmount();

    vi.mocked(searchTracks).mockResolvedValueOnce({
      items: [], nextCursor: null,
      analyticsCoverage: coverage({ evaluatedRuns: 0, pendingRuns: 0, disabledRuns: 3, analysedTracks: 0, unavailableTracks: 0 }),
    });
    const second = renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&loitering=true` });
    await screen.findByText('Analytics disabled by the active scene revision.');
    second.unmount();

    vi.mocked(searchTracks).mockResolvedValueOnce({
      items: [], nextCursor: null,
      analyticsCoverage: coverage({ evaluatedRuns: 3, pendingRuns: 0, disabledRuns: 0, analysedTracks: 40, unavailableTracks: 0, complete: true }),
    });
    renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&loitering=true` });
    await screen.findByText('No evaluated Tracks matched this search.');
  });

  it('reads the inspector against the identity the search pinned and summarises the facts', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&zoneId=${zoneId}` });
    const rows = within(await screen.findByRole('list', { name: 'Track results' })).getAllByRole('listitem');
    await user.click(within(rows[0]).getByRole('button', { name: /^Select / }));

    await waitFor(() => expect(getTrack).toHaveBeenCalledWith(trackId, expect.anything(), {
      sceneRevisionId: revisionId, analyticsAlgorithmVersion: 'scene-analytics-v1',
    }));
    const summary = await screen.findByRole('region', { name: 'Scene analytics' });
    expect(summary).toHaveTextContent('Revision 4 · Engine v1');
    expect(summary).toHaveTextContent('Forecourt · 2 visits · dwell');
    expect(summary).toHaveTextContent('Loitering');
    expect(summary).toHaveTextContent('Gate A · 1 crossing · first inbound at');
    expect(summary).toHaveTextContent('Up-right');
    // And the review link carries the identity beside the return context.
    const open = screen.getByRole('link', { name: 'Open' });
    expect(open.getAttribute('href')).toContain(`sceneRevisionId=${revisionId}`);
    expect(open.getAttribute('href')).toContain('analyticsAlgorithmVersion=scene-analytics-v1');
  });

  it('reads the inspector against the current identity on an ordinary search', async () => {
    const user = userEvent.setup();
    vi.mocked(searchTracks).mockResolvedValue({ items: [item({ analytics: undefined })], nextCursor: null });
    renderWithApp(<VisualSearchPage />, { route: '/search' });
    const rows = within(await screen.findByRole('list', { name: 'Track results' })).getAllByRole('listitem');
    await user.click(within(rows[0]).getByRole('button', { name: /^Select / }));

    await waitFor(() => expect(getTrack).toHaveBeenCalledWith(trackId, expect.anything(), undefined));
    expect(screen.queryByRole('region', { name: 'Analytics coverage' })).not.toBeInTheDocument();
  });

  it('keeps a committed zone in force by identifier when the scene cannot be loaded', async () => {
    vi.mocked(getCameraScene).mockRejectedValue(new Error('offline'));
    renderWithApp(<VisualSearchPage />, { route: `/search?cameraId=${cameraId}&zoneId=${zoneId}` });

    const chips = await screen.findByRole('group', { name: 'Committed filters' });
    await waitFor(() => expect(screen.getByText(/Scene geometry is unavailable/)).toBeInTheDocument());
    expect(within(chips).getByTitle(/^Dwelled in:/)).toHaveTextContent(zoneId.slice(0, 8));
    expect(screen.getByLabelText('Zone')).toHaveValue(zoneId);
    expect(vi.mocked(searchTracks).mock.calls[0][0].zoneId).toBe(zoneId);
  });

  it('builds review links that carry the pinned identity outside the return context', () => {
    const path = reviewPath({ id: trackId.toUpperCase(), videoAssetId: 'v' }, `cameraId=${cameraId}`, {
      sceneRevisionId: revisionId.toUpperCase(), analyticsAlgorithmVersion: 'scene-analytics-v1',
    });
    const url = new URL(path, 'http://x');
    expect(url.searchParams.get('from')).toBe(`cameraId=${cameraId}&track=${trackId}`);
    expect(url.searchParams.get('sceneRevisionId')).toBe(revisionId);
    expect(url.searchParams.get('analyticsAlgorithmVersion')).toBe('scene-analytics-v1');
    expect(reviewPath({ id: trackId, videoAssetId: 'v' }, '')).not.toContain('sceneRevisionId');
  });
});
