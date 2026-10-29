import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import {
  SIMILARITY_CANDIDATES_LABEL,
  getSimilarTracks,
  type SimilarTracksResponse,
  type TrackDetail,
  type TrackSearchItem,
} from '../../api/tracks';
import { renderWithApp } from '../../test/renderWithApp';
import TrackSimilarCandidates, { SIMILARITY_NOTE } from './TrackSimilarCandidates';

vi.mock('../../api/tracks', async () => {
  const actual = await vi.importActual<typeof import('../../api/tracks')>('../../api/tracks');
  return { ...actual, getSimilarTracks: vi.fn() };
});

const queryTrackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21450';
const cameraId = '018F3F5A-2F70-7A2B-8A12-2D02F4C21412';

const detail = {
  id: queryTrackId,
  videoAssetId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21421',
  objectClass: 'Vehicle',
  camera: { id: cameraId, code: 'CAM-01', name: 'North Gate' },
  observations: [],
} as unknown as TrackDetail;

function item(n: number, overrides: Partial<TrackSearchItem> = {}): TrackSearchItem {
  return {
    id: `018f3f5a-2f70-7a2b-8a12-2d02f4c2150${n}`,
    processingRunId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21431',
    videoAssetId: `018f3f5a-2f70-7a2b-8a12-2d02f4c2160${n}`,
    cameraId: cameraId.toLowerCase(),
    cameraCode: `CAM-0${n}`,
    cameraName: `Gate ${n}`,
    objectClass: 'Vehicle',
    startTimestampUtc: '2026-09-14T02:30:00Z',
    endTimestampUtc: '2026-09-14T02:30:08Z',
    startOffsetMs: 0,
    endOffsetMs: 8_000,
    durationMs: 8_000,
    detectionCount: 10,
    meanConfidence: 0.9,
    maxConfidence: 0.95,
    reviewStatus: 'Unreviewed',
    thumbnailArtifactId: null,
    thumbnailContentUrl: `/api/artifacts/thumb-${n}/content`,
    videoContentUrl: '/api/videos/x/content',
    ...overrides,
  };
}

function response(overrides: Partial<SimilarTracksResponse> = {}): SimilarTracksResponse {
  return {
    state: 'ready',
    reason: null,
    label: SIMILARITY_CANDIDATES_LABEL,
    queryTrackId,
    identity: { fingerprint: 'f'.repeat(64), modelId: 'siglip2-base-patch16-256', modelVersion: '2025-02' },
    snapshot: 'snap-token-1',
    snapshotUtc: '2026-10-29T08:00:00Z',
    // Deliberately out of order on the wire: the panel shows rank order.
    candidates: [
      { rank: 2, score: 0.81234, sourceObservationId: null, track: item(2) },
      { rank: 1, score: 0.9, sourceObservationId: null, track: item(1) },
    ],
    ...overrides,
  };
}

function renderPanel() {
  return renderWithApp(<TrackSimilarCandidates detail={detail} displayTimeZoneId="Asia/Kolkata" returnFrom="cameraId=abc&track=x" />);
}

describe('PoC S4 TrackSimilarCandidates', () => {
  beforeEach(() => {
    vi.mocked(getSimilarTracks).mockReset();
  });

  it('carries the similarity label and the not-identity note, and asks nothing until the operator does', () => {
    renderPanel();
    expect(screen.getByRole('heading', { name: SIMILARITY_CANDIDATES_LABEL })).toBeInTheDocument();
    expect(screen.getByText(SIMILARITY_NOTE)).toBeInTheDocument();
    expect(screen.getByLabelText('Same camera only')).not.toBeChecked();
    expect(screen.getByLabelText('Number of candidates')).toHaveValue('20');
    expect(getSimilarTracks).not.toHaveBeenCalled();
  });

  it('lists ready candidates in rank order with three-decimal scores, the model and links to Track detail', async () => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks).mockResolvedValue(response());
    renderPanel();

    await user.click(screen.getByRole('button', { name: 'Find similar' }));

    const list = await screen.findByRole('list', { name: 'Similar Track candidates' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Rank 1 · Score 0.900');
    expect(rows[0]).toHaveTextContent('Vehicle · CAM-01 · Gate 1');
    expect(rows[1]).toHaveTextContent('Rank 2 · Score 0.812');
    // A score, never a percentage "match".
    expect(list).not.toHaveTextContent('%');
    expect(screen.queryByText(/match/i)).not.toBeInTheDocument();

    const link = within(rows[0]).getByRole('link', { name: /Open Vehicle Track on CAM-01, rank 1, similarity score 0.900/ });
    expect(link).toHaveAttribute(
      'href',
      '/review/video/018f3f5a-2f70-7a2b-8a12-2d02f4c21601?trackId=018f3f5a-2f70-7a2b-8a12-2d02f4c21501'
        + '&from=' + encodeURIComponent('cameraId=abc&track=x'),
    );
    expect(rows[0].querySelector('img')).toHaveAttribute('src', '/api/artifacts/thumb-1/content');
    expect(screen.getByText('siglip2-base-patch16-256')).toBeInTheDocument();
    expect(screen.getByText('2025-02')).toBeInTheDocument();
    expect(screen.getByText('2 candidates · ranked by similarity score')).toBeInTheDocument();
    expect(getSimilarTracks).toHaveBeenCalledWith(queryTrackId, { k: 20 }, expect.any(AbortSignal));
  });

  it('sends the optional constraints: same camera and the chosen k', async () => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks).mockResolvedValue(response());
    renderPanel();

    await user.click(screen.getByLabelText('Same camera only'));
    await user.selectOptions(screen.getByLabelText('Number of candidates'), '5');
    await user.click(screen.getByRole('button', { name: 'Find similar' }));

    await waitFor(() => expect(getSimilarTracks).toHaveBeenCalledWith(
      queryTrackId, { k: 5, cameraId: cameraId.toLowerCase() }, expect.any(AbortSignal),
    ));
  });

  it('replays the held snapshot only on an explicit refresh, and a new query drops it', async () => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks).mockResolvedValue(response());
    renderPanel();

    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    await screen.findByRole('list', { name: 'Similar Track candidates' });
    expect(getSimilarTracks).toHaveBeenCalledTimes(1);

    // The constraint changed after the snapshot was taken: the refresh still
    // replays the request the snapshot belongs to.
    await user.click(screen.getByLabelText('Same camera only'));
    await user.click(screen.getByRole('button', { name: 'Refresh (same snapshot)' }));
    await waitFor(() => expect(getSimilarTracks).toHaveBeenCalledTimes(2));
    expect(getSimilarTracks).toHaveBeenLastCalledWith(queryTrackId, { k: 20, snapshot: 'snap-token-1' }, expect.any(AbortSignal));
    await screen.findByRole('list', { name: 'Similar Track candidates' });

    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    await waitFor(() => expect(getSimilarTracks).toHaveBeenCalledTimes(3));
    expect(getSimilarTracks).toHaveBeenLastCalledWith(
      queryTrackId, { k: 20, cameraId: cameraId.toLowerCase() }, expect.any(AbortSignal),
    );
  });

  it('says pending, with a way to check again', async () => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks).mockResolvedValue(response({ state: 'pending', candidates: [], snapshot: null, identity: null }));
    renderPanel();

    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    expect(await screen.findByText(/Similarity pending/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Refresh (same snapshot)' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Check again' }));
    await waitFor(() => expect(getSimilarTracks).toHaveBeenCalledTimes(2));
  });

  it.each([
    ['evidence_too_small', "Similarity unavailable: this Track's evidence crops are smaller than 80 px."],
    ['no_evidence', 'Similarity unavailable: this Track has no accepted evidence crops.'],
    ['evidence_unavailable', "Similarity unavailable: this Track's evidence crops could not be read."],
    ['something_new', 'Similarity unavailable for this Track (something_new).'],
  ])('states unavailable as a first-class answer (%s)', async (reason, sentence) => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks).mockResolvedValue(response({ state: 'unavailable', reason, candidates: [], snapshot: null }));
    renderPanel();

    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    expect(await screen.findByText(sentence)).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Similar Track candidates' })).not.toBeInTheDocument();
  });

  it.each([
    ['notAnalysed', null, /Similarity not analysed: this Track.s run has no appearance analysis/],
    ['failed', 'embedding_attempts_exhausted', /Similarity failed: this Track.s appearance analysis did not complete \(embedding_attempts_exhausted\)/],
  ] as const)('says a %s run is not pending and can be re-analysed', async (state, reason, sentence) => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks).mockResolvedValue(response({ state, reason, candidates: [], snapshot: null }));
    renderPanel();

    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    expect(await screen.findByText(sentence)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check again' })).not.toBeInTheDocument();
  });

  it('says when similarity is not configured', async () => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks).mockResolvedValue(response({ state: 'notConfigured', identity: null, candidates: [], snapshot: null }));
    renderPanel();

    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    expect(await screen.findByText('Similarity search is not configured in this installation.')).toBeInTheDocument();
  });

  it('says an empty ready answer as no candidates, not as an error', async () => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks).mockResolvedValue(response({ candidates: [] }));
    renderPanel();

    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    expect(await screen.findByText('No similarity candidates in this scope.')).toBeInTheDocument();
  });

  it('fails as an alert with a retry for a transient error, and without one for a refusal', async () => {
    const user = userEvent.setup();
    vi.mocked(getSimilarTracks)
      .mockRejectedValueOnce(new ApiError({ status: 500, code: 'api_error', detail: 'Boom.' }))
      .mockRejectedValueOnce(new ApiError({ status: 500, code: 'api_error', detail: 'Boom.' }))
      .mockResolvedValueOnce(response());
    const { unmount } = renderPanel();

    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    const alert = await screen.findByRole('alert', undefined, { timeout: 4000 });
    expect(alert).toHaveTextContent('Similar Tracks could not be loaded. Boom. (api_error)');
    await user.click(within(alert.closest('.alert') as HTMLElement).getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('list', { name: 'Similar Track candidates' })).toBeInTheDocument();
    unmount();

    vi.mocked(getSimilarTracks).mockRejectedValue(new ApiError({ status: 400, code: 'similarity_query_invalid', detail: 'Bad k.' }));
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Find similar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('similarity_query_invalid');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });
});
