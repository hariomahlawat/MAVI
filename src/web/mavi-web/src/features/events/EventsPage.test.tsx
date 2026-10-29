import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getCamera } from '../../api/cameras';
import {
  eventReviewPath,
  getEvent,
  getEventCatalogue,
  getEventTimeline,
  serializeEventTimelineQuery,
  type EventDetail,
  type EventTimeline,
  type RuleCatalogue,
} from '../../api/events';
import { getSystemConfig } from '../../api/system';
import { listVideos, type VideoAsset } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import EventsPage, { coverageGaps, recordingsWindow } from './EventsPage';

vi.mock('../../api/cameras', () => ({ getCamera: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});
vi.mock('../../api/events', async () => {
  const actual = await vi.importActual<typeof import('../../api/events')>('../../api/events');
  return { ...actual, getEventCatalogue: vi.fn(), getEventTimeline: vi.fn(), getEvent: vi.fn() };
});

const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';
const otherCameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21499';
const videoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21420';
const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21430';
const revisionId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21481';
const crossingId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21501';
const stopId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21502';

const catalogue: RuleCatalogue = {
  catalogueVersion: 'mavi-events-v1',
  catalogueSha256: 'a'.repeat(64),
  rules: [
    { ruleId: 'line-crossing', ruleVersion: 1, title: 'Line crossing', description: '', enabled: true, disabledReason: null, parameters: [] },
    {
      ruleId: 'stopped-vehicle', ruleVersion: 1, title: 'Stopped vehicle', description: '', enabled: true, disabledReason: null,
      parameters: [{ name: 'minimumStationarySeconds', value: '30', unit: 's', source: 'owner-decision', reference: 'S2 decision 10' }],
    },
    {
      ruleId: 'repeated-visit', ruleVersion: 1, title: 'Repeated visit', description: '', enabled: false,
      disabledReason: 'requires_entity_confirmation', parameters: [],
    },
  ],
};

function video(overrides: Partial<VideoAsset> = {}): VideoAsset {
  return {
    id: videoId,
    cameraId,
    originalFileName: 'gate.mp4',
    recordingStartUtc: '2026-09-21T04:00:10Z',
    recordingEndUtc: '2026-09-21T04:03:20Z',
    recordingTimeZoneId: 'UTC',
    recordingUtcOffsetMinutes: 0,
    durationMs: 190_000,
    width: 1280,
    height: 720,
    frameRateNumerator: 25,
    frameRateDenominator: 1,
    codecName: 'h264',
    processingStatus: 'Completed',
    importedAtUtc: '2026-09-21T05:00:00Z',
    ...overrides,
  };
}

const completeAnalytics = {
  sceneRevisionId: revisionId, algorithmVersion: 'scene-analytics-v1', evaluatedRuns: 1, pendingRuns: 0, failedRuns: 0,
  notConfiguredRuns: 0, disabledRuns: 0, staleRuns: 0, analysedTracks: 3, unavailableTracks: 0, complete: true,
};

function timeline(overrides: Partial<EventTimeline> = {}): EventTimeline {
  return {
    cameraId,
    sceneRevisionId: revisionId,
    sceneRevisionNumber: 2,
    analyticsAlgorithmVersion: 'scene-analytics-v1',
    catalogueVersion: 'mavi-events-v1',
    snapshotVisibilitySequence: 9,
    fromUtc: '2026-09-21T04:00:00.000Z',
    toUtc: '2026-09-21T04:04:00.000Z',
    bucketSeconds: 60,
    coverage: { analytics: completeAnalytics, derivedRuns: 1, eventsPendingRuns: 0, complete: true },
    buckets: [0, 1, 2, 3].map((index) => ({
      startUtc: new Date(Date.parse('2026-09-21T04:00:00Z') + index * 60_000).toISOString(),
      endUtc: new Date(Date.parse('2026-09-21T04:00:00Z') + (index + 1) * 60_000).toISOString(),
    })),
    ruleCounts: [{ ruleId: 'line-crossing', count: 1 }, { ruleId: 'stopped-vehicle', count: 1 }],
    crossingCounts: [{ lineId: 'l', name: 'Arch gate', aToBLabel: 'Exit', bToALabel: 'Entry', aToBCounts: [0, 1, 0, 0], bToACounts: [0, 0, 0, 0] }],
    events: [
      {
        eventId: crossingId, ruleId: 'line-crossing', ruleVersion: 1, startUtc: '2026-09-21T04:01:05Z', endUtc: '2026-09-21T04:01:05Z',
        startOffsetMs: 55_000, endOffsetMs: 55_000, videoAssetId: videoId, processingRunId: 'r', primaryTrackId: trackId,
        objectClass: 'Vehicle', zoneId: null, zoneName: null, lineId: 'l', lineName: 'Arch gate', direction: 'AToB',
        directionLabel: 'Exit', participantCount: 1,
      },
      {
        eventId: stopId, ruleId: 'stopped-vehicle', ruleVersion: 1, startUtc: '2026-09-21T04:00:20Z', endUtc: '2026-09-21T04:01:00Z',
        startOffsetMs: 10_000, endOffsetMs: 50_000, videoAssetId: videoId, processingRunId: 'r', primaryTrackId: trackId,
        objectClass: 'Vehicle', zoneId: 'z', zoneName: 'Parking bay', lineId: null, lineName: null, direction: null,
        directionLabel: null, participantCount: 1,
      },
    ],
    limit: 1000,
    truncated: false,
    ...overrides,
  };
}

const stopDetail: EventDetail = {
  event: timeline().events[1],
  cameraId,
  sceneAnalysisId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21600',
  sceneRevisionId: revisionId,
  sceneRevisionNumber: 2,
  analyticsAlgorithmVersion: 'scene-analytics-v1',
  catalogueVersion: 'mavi-events-v1',
  catalogueSha256: 'a'.repeat(64),
  inputSha256: 'b'.repeat(64),
  derivedAtUtc: '2026-09-21T05:10:00Z',
  participants: [{
    trackId, role: 'subject', objectClass: 'Vehicle', videoAssetId: videoId, startOffsetMs: 5_000, endOffsetMs: 80_000,
    thumbnailContentUrl: '/api/artifacts/018f3f5a-2f70-7a2b-8a12-2d02f4c21700/content',
  }],
  inputs: [{ kind: 'stationaryInterval', reference: `${trackId}#0`, startOffsetMs: 8_000, endOffsetMs: 52_000 }],
  parameters: [{ name: 'minimumStationarySeconds', value: '30', unit: 's', source: 'owner-decision', reference: 'S2 decision 10' }],
  details: [{ name: 'stationaryInZoneMs', value: '40000' }],
};

function renderPage() {
  return renderWithApp(<EventsPage />, { route: `/cameras/${cameraId}/events`, routePath: '/cameras/:cameraId/events' });
}

beforeEach(() => {
  vi.mocked(getCamera).mockResolvedValue({
    id: cameraId, code: 'POC-S2-05', name: 'Archway gate', description: null, locationName: null, timeZoneId: 'UTC',
    isActive: true, createdAtUtc: '2026-09-14T02:30:00Z', updatedAtUtc: '2026-09-14T02:30:00Z',
  });
  vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'UTC' } as never);
  vi.mocked(getEventCatalogue).mockResolvedValue(catalogue);
  vi.mocked(listVideos).mockResolvedValue([video(), video({ id: 'x', cameraId: otherCameraId, recordingStartUtc: '2020-01-01T00:00:00Z' })]);
  vi.mocked(getEventTimeline).mockResolvedValue(timeline());
  vi.mocked(getEvent).mockResolvedValue(stopDetail);
});

describe('EventsPage', () => {
  it('asks for this camera\'s recordings window and only the enabled rules', async () => {
    renderPage();

    await waitFor(() => expect(getEventTimeline).toHaveBeenCalled());
    const [calledCamera, query] = vi.mocked(getEventTimeline).mock.calls[0];
    expect(calledCamera).toBe(cameraId);
    expect(query.fromUtc).toBe('2026-09-21T04:00:00.000Z');
    expect(query.toUtc).toBe('2026-09-21T04:04:00.000Z');
    expect(query.bucketSeconds).toBe(60);
    expect([...query.ruleIds].sort()).toEqual(['line-crossing', 'stopped-vehicle']);
  });

  it('shows a disabled rule with its reason rather than hiding it', async () => {
    renderPage();

    const repeated = await screen.findByRole('checkbox', { name: /Repeated visit/ });
    expect(repeated).toBeDisabled();
    expect(repeated).not.toBeChecked();
    expect(screen.getByText(/needs confirmed Entities/)).toBeInTheDocument();
    expect(screen.getByText(/not Production-qualified/)).toBeInTheDocument();
  });

  it('lists events with counts per rule and crossings per bucket and direction', async () => {
    renderPage();

    expect(await screen.findByText('Line crossing — Arch gate (Exit): Vehicle', { selector: 'td' })).toBeInTheDocument();
    expect(screen.getByText('Stopped vehicle — Parking bay: Vehicle', { selector: 'td' })).toBeInTheDocument();
    const counts = screen.getByRole('list', { name: 'Events per rule' });
    expect(within(counts).getByText(/Line crossing/)).toHaveTextContent('Line crossing: 1');
    const crossings = screen.getByRole('table', { name: 'Crossings of Arch gate' });
    expect(within(crossings).getByRole('columnheader', { name: 'Exit' })).toBeInTheDocument();
    expect(within(crossings).getByRole('row', { name: /Window 1 0/ })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Complete: 1 run(s) evaluated against scene revision 2.');
  });

  it('drills through to the provenance and to Review at the event instant against the event\'s revision', async () => {
    const user = userEvent.setup();
    renderPage();

    const row = (await screen.findByText('Stopped vehicle — Parking bay: Vehicle', { selector: 'td' })).closest('tr')!;
    await user.click(within(row).getByRole('button', { name: 'Evidence' }));

    const evidence = await screen.findByRole('region', { name: 'Event evidence' });
    expect(getEvent).toHaveBeenCalledWith(stopId, expect.anything());
    expect(within(evidence).getByText(/minimumStationarySeconds: 30 s/)).toBeInTheDocument();
    expect(within(evidence).getByText(/owner decision: S2 decision 10/)).toBeInTheDocument();
    expect(within(evidence).getByText('Revision 2, analytics scene-analytics-v1')).toBeInTheDocument();
    expect(within(evidence).getByRole('img', { name: 'Vehicle Track crop' })).toHaveAttribute(
      'src', '/api/artifacts/018f3f5a-2f70-7a2b-8a12-2d02f4c21700/content');
    const review = within(evidence).getByRole('link', { name: 'Review at event' });
    expect(review).toHaveAttribute(
      'href',
      `/review/video/${videoId}?trackId=${trackId}&sceneRevisionId=${revisionId}&analyticsAlgorithmVersion=scene-analytics-v1&seekMs=10000`,
    );
  });

  it('never shows an incomplete answer as zero events', async () => {
    vi.mocked(getEventTimeline).mockResolvedValue(timeline({
      events: [],
      ruleCounts: [],
      crossingCounts: [],
      coverage: { analytics: { ...completeAnalytics, staleRuns: 1, complete: false }, derivedRuns: 0, eventsPendingRuns: 1, complete: false },
    }));
    renderPage();

    const status = await screen.findByText(/^Incomplete:/);
    expect(status).toHaveTextContent('1 run(s) analysed against an older scene revision (stale)');
    expect(status).toHaveTextContent('1 analysed run(s) whose events are not derived yet');
    expect(status).toHaveTextContent('Missing runs are not shown as zero events.');
    expect(screen.getByText('No events in the evaluated runs so far.')).toBeInTheDocument();
  });

  it('discloses truncation', async () => {
    vi.mocked(getEventTimeline).mockResolvedValue(timeline({ truncated: true, limit: 1 }));
    renderPage();

    expect(await screen.findByText(/Showing the first 1 events; counts cover all of them\./)).toBeInTheDocument();
  });
});

describe('events helpers', () => {
  it('snaps the recordings window outward to whole minutes', () => {
    expect(recordingsWindow([video()])).toEqual({
      fromUtc: '2026-09-21T04:00:00.000Z', toUtc: '2026-09-21T04:04:00.000Z', bucketSeconds: 60,
    });
    expect(recordingsWindow([])).toBeNull();
  });

  it('names every gap, and none when complete', () => {
    expect(coverageGaps({ analytics: completeAnalytics, derivedRuns: 1, eventsPendingRuns: 0, complete: true })).toEqual([]);
  });

  it('serialises a query canonically', () => {
    expect(serializeEventTimelineQuery({
      fromUtc: 'a', toUtc: 'b', bucketSeconds: 60, ruleIds: ['zone-dwell', 'line-crossing'],
    })).toBe('fromUtc=a&toUtc=b&bucketSeconds=60&ruleId=line-crossing&ruleId=zone-dwell');
  });

  it('builds the Review link with a whole non-negative seek', () => {
    expect(eventReviewPath(
      { ...stopDetail, event: { ...stopDetail.event, startOffsetMs: 1234.7 } },
      { trackId: trackId.toUpperCase(), videoAssetId: videoId.toUpperCase() },
    )).toBe(`/review/video/${videoId}?trackId=${trackId}&sceneRevisionId=${revisionId}&analyticsAlgorithmVersion=scene-analytics-v1&seekMs=1234`);
  });
});
