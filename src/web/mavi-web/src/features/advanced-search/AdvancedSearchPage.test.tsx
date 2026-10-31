import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listCameras } from '../../api/cameras';
import { ApiError } from '../../api/client';
import { getQueryContract, runQuery, type QueryContract, type QueryEnvelope, type StructuredQuery } from '../../api/query';
import { getCameraScene } from '../../api/scene';
import { getSystemConfig } from '../../api/system';
import { listVideos, type VideoAsset } from '../../api/videos';
import { renderWithApp } from '../../test/renderWithApp';
import AdvancedSearchPage, { trackReviewPath, truncationText } from './AdvancedSearchPage';
import { createMaviQueryClient } from '../../app/queryClient';
import { MemoryRouter } from 'react-router-dom';
import { buildQuery, canonicalUtc, initialBuilderState, stateFromQuery } from './queryBuilder';

vi.mock('../../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));
vi.mock('../../api/scene', () => ({ getCameraScene: vi.fn() }));
vi.mock('../../api/videos', async () => {
  const actual = await vi.importActual<typeof import('../../api/videos')>('../../api/videos');
  return { ...actual, listVideos: vi.fn() };
});
vi.mock('../../api/query', async () => {
  const actual = await vi.importActual<typeof import('../../api/query')>('../../api/query');
  return { ...actual, getQueryContract: vi.fn(), runQuery: vi.fn() };
});

const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';
const videoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21420';
const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21430';
const revisionId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21481';
const lineId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21490';
const eventId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21501';

const contract: QueryContract = {
  contractVersion: 'mavi-query-v1',
  units: [
    {
      unit: 'track', dataAvailable: true, unavailableReason: null,
      predicates: ['timeWindow', 'cameraIds', 'objectClass', 'objectSubclass', 'minDurationMs', 'minConfidence', 'zone', 'line', 'motion', 'attributes', 'plateText', 'similarTo'],
      groupDimensions: ['camera', 'objectClass', 'objectSubclass'], distinctFields: ['camera', 'objectClass', 'video'],
    },
    {
      unit: 'event', dataAvailable: true, unavailableReason: null,
      predicates: ['timeWindow', 'cameraIds', 'objectClass', 'zone', 'line', 'ruleIds', 'catalogueVersion'],
      groupDimensions: ['camera', 'rule', 'objectClass', 'direction', 'zone', 'line'], distinctFields: ['camera', 'track', 'rule'],
    },
    {
      unit: 'entity', dataAvailable: false, unavailableReason: 'entity_data_unavailable',
      predicates: ['timeWindow', 'cameraIds'], groupDimensions: ['camera'], distinctFields: ['camera'],
    },
  ],
  operations: ['find', 'count', 'countDistinct', 'groupBy', 'timeBucket', 'first', 'last', 'top', 'compare'],
  objectClasses: ['Person', 'Vehicle'],
  objectSubclasses: ['car'],
  zoneRelations: ['entered', 'exited', 'dwelled'],
  crossingDirections: ['aToB', 'bToA'],
  motionDirections: ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'],
  plateMatches: ['contains', 'prefix', 'exact'],
  attributes: [{ type: 'upper-colour', objectClass: 'Person', values: ['red', 'blue'] }],
  attributeDisclosure: 'zero-shot, uncalibrated, Development',
  eventRuleIds: ['line-crossing', 'zone-dwell', 'stopped-vehicle', 'wrong-way', 'co-occurrence', 'repeated-visit'],
  eventCatalogueVersion: 'mavi-events-v1',
  bounds: {
    maximumCameraIds: 64, defaultFindLimit: 50, maximumFindLimit: 200, maximumTopK: 50, maximumSimilarK: 50,
    minimumBucketSeconds: 60, maximumBucketSeconds: 86_400, maximumBuckets: 512, maximumMatchedRecords: 50_000,
  },
  refusalCodes: ['unknown_member'],
  disclosure: 'PoC profile, Development evidence, not Production-qualified.',
};

const video: VideoAsset = {
  id: videoId, cameraId, originalFileName: 'gate.mp4',
  recordingStartUtc: '2026-09-21T08:00:10Z', recordingEndUtc: '2026-09-21T13:59:20Z',
  recordingTimeZoneId: 'UTC', recordingUtcOffsetMinutes: 0, durationMs: 1, width: 1280, height: 720,
  frameRateNumerator: 25, frameRateDenominator: 1, codecName: 'h264', processingStatus: 'Completed',
  importedAtUtc: '2026-09-21T15:00:00Z',
};

function envelope(overrides: Partial<QueryEnvelope> = {}, result: Partial<QueryEnvelope['result']> = {}): QueryEnvelope {
  return {
    contractVersion: 'mavi-query-v1',
    resolvedQuery: {
      contractVersion: 'mavi-query-v1', unit: 'track',
      where: { timeWindow: { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T14:00:00.000Z' } },
      operation: { op: 'count' }, requireCompleteCoverage: false,
    },
    queryFingerprint: 'f'.repeat(64),
    unit: 'track',
    operation: 'count',
    snapshot: { visibilitySequence: 42, evaluatedAtUtc: '2026-09-21T15:00:00Z', similaritySnapshot: null },
    identity: { cameras: [], attributeIdentityFingerprint: null, attributeDisclosure: null, plateIdentityFingerprint: null, embeddingIdentityFingerprint: null, eventCatalogueVersion: null },
    coverage: { complete: true, components: [] },
    result: {
      kind: 'value', tracks: null, events: null, truncation: null, value: 7, dimension: null, groups: null,
      bucketSeconds: null, buckets: null, comparison: null, reason: null, message: null, ...result,
    },
    disclosure: 'PoC profile, Development evidence, not Production-qualified.',
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(getQueryContract).mockResolvedValue(contract);
  vi.mocked(listCameras).mockResolvedValue([{
    id: cameraId, code: 'GATE', name: 'Main gate', description: null, locationName: null, timeZoneId: 'UTC',
    isActive: true, createdAtUtc: '', updatedAtUtc: '',
  }]);
  vi.mocked(listVideos).mockResolvedValue([video]);
  vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: null } as never);
  vi.mocked(getCameraScene).mockResolvedValue({
    cameraId, configured: true, history: [],
    activeRevision: {
      revisionId, revisionNumber: 2, cameraId, createdAtUtc: '', createdBy: '', note: null, referenceFrameVideoAssetId: null,
      referenceFrameOffsetMs: null, analyticsEnabled: true, zones: [],
      tripLines: [{ lineId, name: 'Main Gate', enabled: true, a: { x: 0, y: 0 }, b: { x: 1, y: 1 }, directed: true, aToBLabel: 'Inbound', bToALabel: 'Outbound' }],
    },
  });
  vi.mocked(runQuery).mockReset();
});

describe('the query builder', () => {
  it('loads a proposed query that builds back to exactly that query, or says why it cannot (D-S10-10)', () => {
    const proposedQuery: StructuredQuery = {
      contractVersion: 'mavi-query-v1', unit: 'track',
      where: {
        timeWindow: { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T14:00:00.000Z' },
        cameraIds: [cameraId], objectClass: 'Vehicle', line: { lineId, direction: 'bToA' },
      },
      operation: { op: 'timeBucket', bucketSeconds: 900 },
      requireCompleteCoverage: false,
    };
    const loaded = stateFromQuery(proposedQuery);
    expect(loaded.problem).toBeNull();
    const { requireCompleteCoverage: _, ...expected } = proposedQuery;
    expect(buildQuery(loaded.state!, contract).query).toEqual(expected);

    expect(stateFromQuery({ ...proposedQuery, where: { ...proposedQuery.where, minDurationMs: 1 } }).problem).toMatch(/minimum duration/);
    expect(stateFromQuery({ ...proposedQuery, operation: { op: 'timeBucket', bucketSeconds: 1_800 } }).problem).toMatch(/1800 seconds/);
    expect(stateFromQuery({ ...proposedQuery, where: { ...proposedQuery.where, line: undefined, zone: { zoneId: lineId, loitering: true } } }).problem)
      .toMatch(/loitering/);
    const window = { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T14:00:00.000Z' };
    expect(stateFromQuery({ contractVersion: 'mavi-query-v1', unit: 'track', where: { timeWindow: window, attributes: [{ type: 'upper-colour', value: 'red' }] }, operation: { op: 'count' } }).problem)
      .toMatch(/attributes without an object class/);
  });

  it.each<[string, StructuredQuery]>([
    ['an Event zone with rules, found newest first', {
      contractVersion: 'mavi-query-v1', unit: 'event',
      where: { timeWindow: { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T14:00:00.000Z' }, cameraIds: [cameraId], zone: { zoneId: lineId }, ruleIds: ['line-crossing', 'zone-dwell'] },
      operation: { op: 'find', limit: 20, order: 'newest' },
    }],
    ['a compare with its baseline', {
      contractVersion: 'mavi-query-v1', unit: 'track',
      where: { timeWindow: { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T09:00:00.000Z' }, objectClass: 'Person' },
      operation: { op: 'compare', baseline: { fromUtc: '2026-09-20T08:00:00.000Z', toUtc: '2026-09-20T09:00:00.000Z' } },
    }],
    ['a top with k, and attributes with their class', {
      contractVersion: 'mavi-query-v1', unit: 'track',
      where: { timeWindow: { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T14:00:00.000Z' }, objectClass: 'Person', attributes: [{ type: 'upper-colour', value: 'red' }] },
      operation: { op: 'top', by: 'camera', k: 3 },
    }],
    ['a plate prefix counted per distinct video', {
      contractVersion: 'mavi-query-v1', unit: 'track',
      where: { timeWindow: { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T14:00:00.000Z' }, objectClass: 'Vehicle', plateText: { text: 'MH12', match: 'prefix' } },
      operation: { op: 'countDistinct', field: 'video' },
    }],
  ])('loads %s and builds it back unchanged', (_, query) => {
    const loaded = stateFromQuery(query);
    expect(loaded.problem).toBeNull();
    expect(buildQuery(loaded.state!, contract).query).toEqual(query);
  });

  it('builds only what the contract allows and states its window explicitly', () => {
    const state = {
      ...initialBuilderState({ fromUtc: '2026-09-21T08:00:00Z', toUtc: '2026-09-21T14:00:00Z' }),
      unit: 'entity' as const, objectClass: 'Person' as const, plateText: 'AB12', op: 'groupBy' as const, dimension: 'rule',
    };
    const built = buildQuery(state, contract);
    // Entity takes neither a class nor a plate, and groups only by camera.
    expect(built.query).toEqual({
      contractVersion: 'mavi-query-v1', unit: 'entity',
      where: { timeWindow: { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T14:00:00.000Z' } },
      operation: { op: 'groupBy', by: 'camera' },
    });
  });

  it('does not send a row count or rank size the contract would refuse', () => {
    const base = initialBuilderState({ fromUtc: '2026-09-21T08:00:00Z', toUtc: '2026-09-21T14:00:00Z' });
    expect(buildQuery({ ...base, op: 'find', limit: Number('') || Number.NaN }, contract).query).toBeNull();
    expect(buildQuery({ ...base, op: 'find', limit: 201 }, contract).problem).toMatch(/1 to 200/);
    expect(buildQuery({ ...base, op: 'top', k: 0 }, contract).query).toBeNull();
  });

  it('does not combine attributes with a plate text', () => {
    const state = {
      ...initialBuilderState({ fromUtc: '2026-09-21T08:00:00Z', toUtc: '2026-09-21T14:00:00Z' }),
      objectClass: 'Person' as const, attributes: { 'upper-colour': 'red' }, plateText: 'AB12C',
    };
    expect(buildQuery(state, contract).problem).toMatch(/cannot be combined/);
  });

  it('pins a geometric match to the revision it was matched against in the Review link', () => {
    const row = {
      trackId, cameraId, cameraCode: 'GATE', cameraName: 'Main gate', videoAssetId: videoId, processingRunId: videoId,
      objectClass: 'Person', objectSubclass: null, startTimestampUtc: '', endTimestampUtc: '', startOffsetMs: 0,
      durationMs: 0, meanConfidence: 0, thumbnailArtifactId: null, similarityScore: null,
    };
    expect(trackReviewPath(row)).toBe(`/review/video/${videoId}?trackId=${trackId}`);
    expect(trackReviewPath(row, {
      cameraId, cameraCode: 'GATE', cameraName: 'Main gate', sceneRevisionId: revisionId, sceneRevisionNumber: 2, algorithmVersion: 'scene-analytics-v1',
    })).toBe(`/review/video/${videoId}?trackId=${trackId}&sceneRevisionId=${revisionId}&analyticsAlgorithmVersion=scene-analytics-v1`);
  });

  it('says a partial list total is only a lower bound', () => {
    expect(truncationText({ truncated: false, returned: 2, total: 2, limit: 50, totalIsLowerBound: true }))
      .toBe('Showing 2 of at least 2 found so far: not every part of the scope has been analysed.');
  });

  it('refuses an impossible calendar date rather than sending the rolled-over window', () => {
    expect(canonicalUtc('2026-02-30T08:00:00Z')).toBeNull();
    expect(canonicalUtc('2026-09-21T24:00:00Z')).toBeNull();
    expect(canonicalUtc('2026-02-28T08:00:00.5+00:00')).toBe('2026-02-28T08:00:00.500Z');
    const window = initialBuilderState({ fromUtc: '2026-02-30T08:00:00Z', toUtc: '2026-03-03T08:00:00Z' });
    expect(buildQuery(window, contract).query).toBeNull();
    const baseline = {
      ...initialBuilderState({ fromUtc: '2026-09-21T08:00:00Z', toUtc: '2026-09-21T14:00:00Z' }),
      op: 'compare' as const, baselineFromUtc: '2026-09-31T08:00:00Z', baselineToUtc: '2026-10-01T14:00:00Z',
    };
    expect(buildQuery(baseline, contract).problem).toMatch(/baseline/);
  });

  it('refuses to build a window without an explicit UTC offset', () => {
    const built = buildQuery({ ...initialBuilderState({ fromUtc: '2026-09-21T08:00:00', toUtc: '2026-09-21T14:00:00Z' }) }, contract);
    expect(built.query).toBeNull();
  });

  it('drops a line unless exactly one camera is chosen', () => {
    const base = { ...initialBuilderState({ fromUtc: '2026-09-21T08:00:00Z', toUtc: '2026-09-21T14:00:00Z' }), lineId };
    expect(buildQuery(base, contract).query?.where.line).toBeUndefined();
    expect(buildQuery({ ...base, cameraIds: [cameraId], lineDirection: 'aToB' }, contract).query?.where.line)
      .toEqual({ lineId, direction: 'aToB' });
  });
});

describe('Advanced Search', () => {
  it('loads a query proposed by Ask MAVI into the builder and does not run it (D-S10-10)', async () => {
    const askQuery: StructuredQuery = {
      contractVersion: 'mavi-query-v1', unit: 'track',
      where: { timeWindow: { fromUtc: '2026-09-21T09:00:00.000Z', toUtc: '2026-09-21T10:00:00.000Z' }, objectClass: 'Vehicle' },
      operation: { op: 'count' }, requireCompleteCoverage: false,
    };
    const queryClient = createMaviQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[{ pathname: '/query', state: { askQuery } }]}><AdvancedSearchPage /></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/Loaded from Ask MAVI\. Nothing has run/)).toBeInTheDocument();
    expect(screen.getByLabelText('From (UTC)')).toHaveValue('2026-09-21T09:00:00.000Z');
    expect(runQuery).not.toHaveBeenCalled();
  });

  it('composes the demo question, shows it as resolved and draws the hourly buckets', async () => {
    vi.mocked(runQuery).mockResolvedValue(envelope({ operation: 'timeBucket' }, {
      kind: 'buckets', value: null, bucketSeconds: 3600,
      buckets: [
        { startUtc: '2026-09-21T08:00:00Z', endUtc: '2026-09-21T09:00:00Z', count: 3 },
        { startUtc: '2026-09-21T09:00:00Z', endUtc: '2026-09-21T10:00:00Z', count: 0 },
      ],
    }));
    const user = userEvent.setup();
    renderWithApp(<AdvancedSearchPage />);

    await screen.findByRole('heading', { name: 'Advanced Search' });
    await waitFor(() => expect(screen.getByLabelText('From (UTC)')).toHaveValue('2026-09-21T08:00:00.000Z'));
    await user.click(screen.getByRole('checkbox', { name: /GATE/ }));
    await user.selectOptions(screen.getByLabelText('Class'), 'Person');
    await user.selectOptions(await screen.findByLabelText('Line'), lineId);
    await user.selectOptions(screen.getByLabelText('Direction'), 'aToB');
    await user.selectOptions(screen.getByLabelText('Operation'), 'timeBucket');
    await user.click(screen.getByRole('button', { name: 'Run query' }));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0]).toEqual({
      contractVersion: 'mavi-query-v1', unit: 'track',
      where: {
        timeWindow: { fromUtc: '2026-09-21T08:00:00.000Z', toUtc: '2026-09-21T14:00:00.000Z' },
        cameraIds: [cameraId], objectClass: 'Person', line: { lineId, direction: 'aToB' },
      },
      operation: { op: 'timeBucket', bucketSeconds: 3600 },
    });
    const figure = await screen.findByRole('figure');
    expect(within(figure).getByRole('table')).toBeInTheDocument();
    expect(within(figure).getAllByRole('row')).toHaveLength(3);
    expect(screen.getByLabelText('Resolved query')).toHaveTextContent('"op": "count"');
    expect(screen.getByText('Coverage complete for this scope.')).toBeInTheDocument();
  });

  it('clears a plate text hidden by choosing Person, so the visible query is the one sent', async () => {
    vi.mocked(runQuery).mockResolvedValue(envelope());
    const user = userEvent.setup();
    renderWithApp(<AdvancedSearchPage />);
    await waitFor(() => expect(screen.getByLabelText('From (UTC)')).not.toHaveValue(''));
    await user.type(screen.getByLabelText('Plate text'), 'AB12C');
    await user.selectOptions(screen.getByLabelText('Class'), 'Person');
    expect(screen.queryByLabelText('Plate text')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Class'), 'Vehicle');
    // The plate field is empty again: the text did not survive hidden.
    expect(screen.getByLabelText('Plate text')).toHaveValue('');
    await user.selectOptions(screen.getByLabelText('Class'), 'Person');
    await user.click(screen.getByRole('button', { name: 'Run query' }));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0].where).not.toHaveProperty('plateText');
    expect(vi.mocked(runQuery).mock.calls[0][0].where.objectClass).toBe('Person');
  });

  it('withholds a figure when coverage is incomplete, and says what is missing', async () => {
    vi.mocked(runQuery).mockResolvedValue(envelope({
      coverage: {
        complete: false,
        components: [{
          kind: 'events', window: 'query', complete: false, cameraId,
          sceneAnalytics: { sceneRevisionId: revisionId, algorithmVersion: 'scene-analytics-v1', evaluatedRuns: 1, pendingRuns: 0, failedRuns: 0, notConfiguredRuns: 0, disabledRuns: 0, staleRuns: 0, analysedTracks: 1, unavailableTracks: 0, complete: true },
          derivedRuns: 0, eventsPendingRuns: 1, attributes: null, plates: null, reason: null,
        }],
      },
    }, { kind: 'withheld', value: null, reason: 'coverage_incomplete', message: 'Not every part of the scope has been analysed.' }));
    const user = userEvent.setup();
    renderWithApp(<AdvancedSearchPage />);
    await waitFor(() => expect(screen.getByLabelText('From (UTC)')).not.toHaveValue(''));
    await user.click(screen.getByRole('button', { name: 'Run query' }));

    expect(await screen.findByText(/No figure/)).toBeInTheDocument();
    expect(screen.getByText(/1 analysed run\(s\) whose events are not derived yet/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Result value')).not.toBeInTheDocument();
  });

  it('shows the Entity unit as defined but without data, never as zero', async () => {
    vi.mocked(runQuery).mockResolvedValue(envelope({ unit: 'entity', coverage: { complete: false, components: [] } }, {
      kind: 'empty', value: null, reason: 'entity_data_unavailable',
      message: 'No Entity exists until ReID candidates are confirmed (S7, ADR-023).',
    }));
    const user = userEvent.setup();
    renderWithApp(<AdvancedSearchPage />);
    await user.click(await screen.findByRole('radio', { name: /Entities/ }));
    await user.click(screen.getByRole('button', { name: 'Run query' }));

    expect(await screen.findByText(/No data: No Entity exists/)).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('lists operator-confirmed Entities with a link to each, labelled as a judgement and not an identification', async () => {
    vi.mocked(runQuery).mockResolvedValue(envelope({ unit: 'entity' }, {
      kind: 'rows', value: null, truncation: { truncated: false, returned: 1, total: 1, limit: 50, totalIsLowerBound: false },
      entities: [{
        entityId: 'E1', displayCode: 'P-0000000000e3', entityType: 'Person', firstStartUtc: '2026-09-21T08:10:00Z',
        lastEndUtc: '2026-09-21T09:30:00Z', cameraIds: [cameraId, 'c2'], memberTrackIds: [trackId, 't2'],
      }],
    }));
    const user = userEvent.setup();
    renderWithApp(<AdvancedSearchPage />);
    await user.click(await screen.findByRole('radio', { name: /Entities/ }));
    await user.click(screen.getByRole('button', { name: 'Run query' }));

    const table = await screen.findByRole('table', { name: 'Entities' });
    expect(within(table).getByText('P-0000000000e3 · Person (operator-confirmed, not identification)')).toBeInTheDocument();
    expect(within(table).getByRole('link', { name: 'Open Entity' })).toHaveAttribute('href', '/entities?entity=e1');
  });

  it('drills through from Track and Event rows', async () => {
    vi.mocked(runQuery).mockResolvedValueOnce(envelope({}, {
      kind: 'rows', value: null,
      truncation: { truncated: true, returned: 1, total: 4, limit: 1, totalIsLowerBound: false },
      tracks: [{
        trackId, cameraId, cameraCode: 'GATE', cameraName: 'Main gate', videoAssetId: videoId, processingRunId: videoId,
        objectClass: 'Person', objectSubclass: null, startTimestampUtc: '2026-09-21T08:10:00Z', endTimestampUtc: '2026-09-21T08:10:08Z',
        startOffsetMs: 590_000, durationMs: 8_000, meanConfidence: 0.8, thumbnailArtifactId: null, similarityScore: null,
      }],
    }));
    const user = userEvent.setup();
    renderWithApp(<AdvancedSearchPage />);
    await waitFor(() => expect(screen.getByLabelText('From (UTC)')).not.toHaveValue(''));
    await user.click(screen.getByRole('button', { name: 'Run query' }));

    expect(await screen.findByText('Showing 1 of 4.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open these Tracks in Search' })).toHaveAttribute(
      'href', '/search?fromUtc=2026-09-21T08%3A00%3A00.000Z&toUtc=2026-09-21T14%3A00%3A00.000Z');
    expect(screen.getByRole('link', { name: 'Review Track' })).toHaveAttribute('href', `/review/video/${videoId}?trackId=${trackId}`);

    vi.mocked(runQuery).mockResolvedValueOnce(envelope({
      unit: 'event',
      identity: {
        cameras: [{ cameraId, cameraCode: 'GATE', cameraName: 'Main gate', sceneRevisionId: revisionId, sceneRevisionNumber: 2, algorithmVersion: 'scene-analytics-v1' }],
        attributeIdentityFingerprint: null, attributeDisclosure: null, plateIdentityFingerprint: null, embeddingIdentityFingerprint: null, eventCatalogueVersion: 'mavi-events-v1',
      },
    }, {
      kind: 'rows', value: null, truncation: { truncated: false, returned: 1, total: 1, limit: 50, totalIsLowerBound: false },
      events: [{
        eventId, ruleId: 'line-crossing', ruleVersion: 1, cameraId, cameraCode: 'GATE', cameraName: 'Main gate', videoAssetId: videoId,
        primaryTrackId: trackId, objectClass: 'Person', zoneId: null, zoneName: null, lineId, lineName: 'Main Gate', direction: 'AToB',
        startUtc: '2026-09-21T08:10:04Z', endUtc: '2026-09-21T08:10:04Z', startOffsetMs: 594_000,
      }],
    }));
    await user.click(screen.getByRole('button', { name: 'Run query' }));
    const review = await screen.findByRole('link', { name: 'Review at event' });
    expect(review.getAttribute('href')).toBe(
      `/review/video/${videoId}?trackId=${trackId}&sceneRevisionId=${revisionId}&analyticsAlgorithmVersion=scene-analytics-v1&seekMs=594000`);
    expect(screen.getByRole('link', { name: 'Camera events' })).toHaveAttribute('href', `/cameras/${cameraId}/events`);
  });

  it('shows a refusal with its typed code and where it applies', async () => {
    vi.mocked(runQuery).mockRejectedValue(new ApiError({
      status: 400, code: 'query_refused', detail: 'x',
      extensions: { refusal: { code: 'geometry_requires_single_camera', path: '/where/cameraIds', message: 'Name exactly one camera.' } },
    }));
    const user = userEvent.setup();
    renderWithApp(<AdvancedSearchPage />);
    await waitFor(() => expect(screen.getByLabelText('From (UTC)')).not.toHaveValue(''));
    await user.click(screen.getByRole('button', { name: 'Run query' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Refused: geometry_requires_single_camera');
    expect(alert).toHaveTextContent('/where/cameraIds');
  });
});
