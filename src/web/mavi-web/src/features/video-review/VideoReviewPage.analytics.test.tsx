import { screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getCameraSceneRevision } from '../../api/scene';
import { getSystemConfig } from '../../api/system';
import { getTrack, type TrackDetail, type TrackDetailAnalytics } from '../../api/tracks';
import {
  ANALYSED_REVISION_ID,
  OTHER_REVISION_ID,
  ZONE_B,
  analysedAnalytics,
  lineCrossing,
  sceneRevision,
  sceneTripLine,
  sceneZone,
  zoneSummary,
  zoneVisit,
} from '../../test/analyticsFixtures';
import { renderWithApp } from '../../test/renderWithApp';
import VideoReviewPage from './VideoReviewPage';

vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/scene', async () => {
  const actual = await vi.importActual<typeof import('../../api/scene')>('../../api/scene');
  return { ...actual, getCameraSceneRevision: vi.fn(), getCameraScene: vi.fn() };
});
vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, getTrack: vi.fn() };
});

const videoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';
const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21451';
const cameraId = '11111111-1111-7111-8111-111111111111';

const revision = sceneRevision({
  zones: [sceneZone(), sceneZone({ zoneId: ZONE_B, name: 'Loading bay', enabled: false })],
  tripLines: [sceneTripLine()],
});

function detail(analytics: TrackDetailAnalytics): TrackDetail {
  return {
    id: trackId,
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
    videoAssetId: videoId,
    camera: { id: cameraId, code: 'CAM-01', name: 'North Gate' },
    objectClass: 'Person',
    localTrackNumber: 7,
    startOffsetMs: 10_000,
    endOffsetMs: 20_000,
    startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:10Z',
    durationMs: 10_000,
    detectionCount: 42,
    meanConfidence: 0.91,
    maxConfidence: 0.98,
    reviewStatus: 'Unreviewed',
    processing: {
      pipelineVersion: 'phase1', detectorName: 'RTMDet', detectorVersion: '1',
      trackerName: 'ByteTrack', trackerVersion: '1', completedAtUtc: '2026-09-14T02:40:00Z',
    },
    video: {
      recordingStartUtc: '2026-09-14T02:26:42Z', recordingEndUtc: '2026-09-14T02:36:42Z',
      durationMs: 600_000, width: 1920, height: 1080,
      frameRateNumerator: 25, frameRateDenominator: 1,
      videoContentUrl: '/api/videos/' + videoId + '/content',
    },
    representative: null, observations: [], // The legacy shape: no Representative relation, no Evidence Set.
    trajectoryArtifactId: null,
    trajectoryContentUrl: null,
    analytics,
  };
}

const analysed = analysedAnalytics({
  zoneSummaries: [zoneSummary()],
  zoneVisits: [zoneVisit()],
  lineCrossings: [lineCrossing()],
});

function open(analytics: TrackDetailAnalytics = analysed) {
  vi.mocked(getTrack).mockResolvedValue(detail(analytics));
  return renderWithApp(<VideoReviewPage />, {
    route: `/review/video/${videoId}?trackId=${trackId}`,
    routePath: '/review/video/:videoAssetId',
  });
}

beforeEach(() => {
  vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'Asia/Kolkata' } as never);
  vi.mocked(getCameraSceneRevision).mockResolvedValue(revision);
  // jsdom lays nothing out, so the overlay stage needs a measurable box.
  for (const [name, value] of Object.entries({ clientWidth: 800, clientHeight: 450 })) {
    Object.defineProperty(HTMLElement.prototype, name, { configurable: true, get: () => value });
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Review draws the revision the facts were measured against', () => {
  it('fetches the pinned revision by its own number and never the active scene', async () => {
    open();
    await waitFor(() => expect(getCameraSceneRevision).toHaveBeenCalled());

    // The number the facts carry, not a revision resolved from the camera's
    // current scene. The active-scene endpoint is not called at all, so there
    // is no code path by which today's geometry could be drawn over yesterday's
    // facts.
    expect(vi.mocked(getCameraSceneRevision).mock.calls[0].slice(0, 2)).toEqual([cameraId, 4]);
    const scene = await import('../../api/scene');
    expect(scene.getCameraScene).not.toHaveBeenCalled();
  });

  it('draws the pinned geometry and marks only what this Track touched', async () => {
    open();
    const zones = await screen.findAllByTestId('evidence-zone');
    expect(zones).toHaveLength(2);
    expect(zones[0]).toHaveAttribute('data-matched', 'true');
    // Disabled in this revision, so analytics never evaluated it: context at
    // most, never a match.
    expect(zones[1]).toHaveAttribute('data-enabled', 'false');
    expect(zones[1]).toHaveAttribute('data-matched', 'false');

    expect(await screen.findByTestId('evidence-line')).toBeInTheDocument();
    expect(await screen.findByTestId('evidence-crossing')).toBeInTheDocument();
  });

  it('puts the analytical facts on the one timeline, in their own lanes', async () => {
    open();
    await screen.findByRole('region', { name: 'Scene analytics' });
    await waitFor(() => {
      const lanes = screen.getAllByRole('listitem').map((item) => item.dataset.lane).filter(Boolean);
      expect(lanes).toContain('subject');
      expect(lanes).toContain('zone');
    });
    const items = screen.getAllByRole('listitem');

    // Exactly one timeline and one player, still.
    expect(screen.getAllByRole('list', { name: /timeline evidence/ })).toHaveLength(1);
    expect(document.querySelectorAll('video')).toHaveLength(1);

    // The crossing is a marker with an exact-seek control, and the entry and
    // exit of the visit are markers too because this visit crossed both edges.
    const markers = items.filter((item) => item.className.includes('__marker'));
    expect(markers.map((m) => m.dataset.kind).sort())
      .toEqual(['crossing', 'zone-entry', 'zone-exit']);
    for (const marker of markers) {
      expect(marker.querySelector('button')).toBeInTheDocument();
    }
  });

  it('explains the facts beside the player, with the pinned identity', async () => {
    open();
    const panel = await screen.findByRole('region', { name: 'Scene analytics' });
    // Wait for the pinned revision, which is what turns the stable ids into
    // the names the operator gave the geometry.
    await waitFor(() => expect(panel).toHaveTextContent('Forecourt · 1 visit'));
    expect(panel).toHaveTextContent('Gate line · 1 crossing');
    expect(panel).toHaveTextContent('Scene revision 4 · Engine v1 · reference point: Box centre');
  });

  it('keeps the primary Track summary ahead of the analytics panel', async () => {
    // Section 4.5.1: the primary summary and the player share the initial
    // viewport at 1366x768, so the explanation follows rather than displaces it.
    open();
    await screen.findByRole('region', { name: 'Scene analytics' });
    const headings = screen.getAllByRole('heading').map((h) => h.textContent);
    expect(headings.indexOf('Track summary')).toBeLessThan(headings.indexOf('Scene analytics'));
  });
});

describe('Review fails closed on a geometry problem', () => {
  it('draws no geometry when the served revision is not the one named', async () => {
    vi.mocked(getCameraSceneRevision).mockResolvedValue(
      sceneRevision({ revisionId: OTHER_REVISION_ID }),
    );
    open();

    const panel = await screen.findByRole('region', { name: 'Scene analytics' });
    await waitFor(() => expect(panel).toHaveTextContent('is not the one these facts were measured against'));
    // Not one outline from the wrong revision.
    expect(screen.queryByTestId('evidence-zone')).not.toBeInTheDocument();
    expect(screen.queryByTestId('evidence-line')).not.toBeInTheDocument();
    // The facts themselves survive, named by identifier.
    expect(panel).toHaveTextContent('1 visit');
  });

  it('keeps the facts and the raw evidence when the revision cannot be loaded', async () => {
    vi.mocked(getCameraSceneRevision).mockRejectedValue(new Error('offline'));
    open();

    const panel = await screen.findByRole('region', { name: 'Scene analytics' });
    await waitFor(() => expect(panel).toHaveTextContent('could not be loaded'));
    expect(screen.queryByTestId('evidence-zone')).not.toBeInTheDocument();
    // The player, the timeline and the subject interval are unaffected: a
    // geometry failure is not a Track failure.
    expect(document.querySelectorAll('video')).toHaveLength(1);
    expect(screen.getByRole('list', { name: /timeline evidence/ })).toBeInTheDocument();
    // The crossing is still persisted evidence and keeps its place in time.
    const items = screen.getAllByRole('listitem');
    expect(items.some((item) => item.dataset.kind === 'crossing')).toBe(true);
  });

  it('asks for no geometry at all when analytics produced no facts', async () => {
    open(analysedAnalytics({ status: 'Unavailable', unavailableReason: 'trajectory_too_short' }));
    const panel = await screen.findByRole('region', { name: 'Scene analytics' });
    expect(panel).toHaveTextContent('trajectory_too_short');
    expect(getCameraSceneRevision).not.toHaveBeenCalled();
    expect(screen.queryByTestId('evidence-zone')).not.toBeInTheDocument();
  });

  it('refuses to guess a revision when the identity is incomplete', async () => {
    open(analysedAnalytics({ sceneRevisionNumber: null, zoneVisits: [zoneVisit()] }));
    const panel = await screen.findByRole('region', { name: 'Scene analytics' });
    expect(panel).toHaveTextContent('do not name a complete scene revision');
    expect(getCameraSceneRevision).not.toHaveBeenCalled();
  });

  it('separates two analytical identities in the cache', async () => {
    // Two Tracks analysed under different revisions must not share a geometry
    // entry, or the second would be drawn over the first's outlines.
    const view = open();
    await waitFor(() => expect(getCameraSceneRevision).toHaveBeenCalledTimes(1));
    view.unmount();

    vi.mocked(getCameraSceneRevision).mockResolvedValue(
      sceneRevision({ revisionId: OTHER_REVISION_ID, revisionNumber: 7 }),
    );
    open(analysedAnalytics({
      sceneRevisionId: OTHER_REVISION_ID,
      sceneRevisionNumber: 7,
      zoneVisits: [zoneVisit()],
    }));
    await waitFor(() => expect(getCameraSceneRevision).toHaveBeenCalledTimes(2));
    expect(vi.mocked(getCameraSceneRevision).mock.calls[1].slice(0, 2)).toEqual([cameraId, 7]);
    // And the first revision is still the one the first identity named.
    expect(vi.mocked(getCameraSceneRevision).mock.calls[0][1]).toBe(4);
    expect(ANALYSED_REVISION_ID).not.toBe(OTHER_REVISION_ID);
  });
});
