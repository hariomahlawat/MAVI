import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { InfiniteData } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import {
  decideTrackReview,
  getTrackReview,
  getTrackReviewHistory,
  type ReviewDecision,
  type TrackReviewState,
} from '../../api/review';
import type { TrackDetail, TrackSearchResponse } from '../../api/tracks';
import { createMaviQueryClient, queryKeys } from '../../app/queryClient';
import { renderWithApp } from '../../test/renderWithApp';
import TrackReviewPanel, { applyReviewDecision } from './TrackReviewPanel';
import { OPERATOR_REQUIRED } from './operator';

vi.mock('../../api/review', async () => {
  const actual = await vi.importActual<typeof import('../../api/review')>('../../api/review');
  return { ...actual, getTrackReview: vi.fn(), decideTrackReview: vi.fn(), getTrackReviewHistory: vi.fn() };
});

const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21450';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function decision(overrides: Partial<ReviewDecision> = {}): ReviewDecision {
  return {
    decisionId: '0b9f1c9e-6a43-4c1f-9d3e-1f2a3b4c5d6e', trackId, decision: 'Confirmed', previousStatus: 'Unreviewed',
    resultingStatus: 'Confirmed', note: null, operatorId: 'SITE\\asha', operatorDisplayName: 'Asha', identitySource: 'windows-negotiate',
    decidedAtUtc: '2026-10-31T08:00:00Z', auditEntryId: 'a1', ...overrides,
  };
}

function state(overrides: Partial<TrackReviewState> = {}): TrackReviewState {
  return {
    trackId, processingRunId: 'run-2', reviewStatus: 'Unreviewed', latestDecision: null, otherRuns: [],
    statement: 'A review decision says whether the detection is correct. It never says who or which object the Track shows.',
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

/** The words no review surface may use: a decision is about the detection, never identity. */
const IDENTITY_WORDS = /same person|same vehicle|\bmatched\b|linked identity|identified/i;

const statusBadge = () => within(screen.getByRole('region', { name: 'Review decision' })).getAllByText(/^(Unreviewed|Confirmed|Rejected)$/)[0];

describe('PoC S11-full Track review controls', () => {
  beforeEach(() => {
    vi.mocked(getTrackReview).mockReset();
    vi.mocked(decideTrackReview).mockReset();
    vi.mocked(getTrackReviewHistory).mockReset();
  });

  it('sends the decision with a client decisionId and the expected status, waits, then shows the persisted status', async () => {
    const user = userEvent.setup();
    vi.mocked(getTrackReview).mockResolvedValueOnce(state());
    const answer = deferred<Awaited<ReturnType<typeof decideTrackReview>>>();
    vi.mocked(decideTrackReview).mockReturnValue(answer.promise);
    renderWithApp(<TrackReviewPanel trackId={trackId.toUpperCase()} reviewStatus="Unreviewed" displayTimeZoneId="UTC" />);

    const confirm = await screen.findByRole('button', { name: 'Confirm detection' });
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.type(screen.getByRole('textbox', { name: /Note/ }), 'clear frontal view');
    await user.click(confirm);

    expect(decideTrackReview).toHaveBeenCalledWith(trackId, expect.objectContaining({
      decision: 'Confirmed', expectedReviewStatus: 'Unreviewed', note: 'clear frontal view',
    }));
    expect(vi.mocked(decideTrackReview).mock.calls[0][1].decisionId).toMatch(UUID);
    // No optimistic update: while the server has not answered, nothing changed.
    expect(statusBadge()).toHaveTextContent('Unreviewed');
    expect(screen.getByRole('button', { name: 'Confirm detection' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();

    vi.mocked(getTrackReview).mockResolvedValue(state({ reviewStatus: 'Confirmed', latestDecision: decision({ note: 'clear frontal view' }) }));
    answer.resolve({ trackId, reviewStatus: 'Confirmed', latestDecision: decision({ note: 'clear frontal view' }), replayed: false });

    expect(await screen.findByText('Recorded: Detection confirmed. Status: Confirmed.')).toBeInTheDocument();
    expect(statusBadge()).toHaveTextContent('Confirmed');
    expect(screen.getByText('Asha')).toBeInTheDocument();
    expect(screen.getByText('via windows-negotiate')).toBeInTheDocument();
    expect(screen.getAllByText('clear frontal view').length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(IDENTITY_WORDS);
  });

  it('offers Clear only when the Track carries a decision', async () => {
    vi.mocked(getTrackReview).mockResolvedValueOnce(state());
    const first = renderWithApp(<TrackReviewPanel trackId={trackId} reviewStatus="Unreviewed" />);
    await screen.findByText('No decision has been recorded for this Track.');
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();
    first.unmount();

    vi.mocked(getTrackReview).mockResolvedValueOnce(state({ reviewStatus: 'Rejected', latestDecision: decision({ decision: 'Rejected', resultingStatus: 'Rejected' }) }));
    renderWithApp(<TrackReviewPanel trackId={trackId} reviewStatus="Rejected" />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Clear' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
  });

  it('names the decision recorded first on a 409 conflict, and refreshes', async () => {
    const user = userEvent.setup();
    vi.mocked(getTrackReview).mockResolvedValueOnce(state());
    vi.mocked(decideTrackReview).mockRejectedValue(new ApiError({
      status: 409, code: 'track_review_conflict', detail: "The Track's review status changed since it was read.",
      extensions: { currentReviewStatus: 'Rejected', currentDecision: decision({ decision: 'Rejected', resultingStatus: 'Rejected', operatorDisplayName: 'Ravi' }) },
    }));
    renderWithApp(<TrackReviewPanel trackId={trackId} reviewStatus="Unreviewed" displayTimeZoneId="UTC" />);
    const confirm = await screen.findByRole('button', { name: 'Confirm detection' });
    await waitFor(() => expect(confirm).toBeEnabled());

    vi.mocked(getTrackReview).mockResolvedValue(state({ reviewStatus: 'Rejected', latestDecision: decision({ decision: 'Rejected', resultingStatus: 'Rejected', operatorDisplayName: 'Ravi' }) }));
    await user.click(confirm);

    expect(await screen.findByText(/Another decision was recorded first: Detection rejected by Ravi at /)).toBeInTheDocument();
    await waitFor(() => expect(getTrackReview).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(statusBadge()).toHaveTextContent('Rejected'));
  });

  it('is operable from the keyboard', async () => {
    const user = userEvent.setup();
    vi.mocked(getTrackReview).mockResolvedValue(state({ reviewStatus: 'Confirmed', latestDecision: decision() }));
    vi.mocked(decideTrackReview).mockResolvedValue({ trackId, reviewStatus: 'Rejected', latestDecision: decision({ decision: 'Rejected', resultingStatus: 'Rejected' }), replayed: false });
    renderWithApp(<TrackReviewPanel trackId={trackId} reviewStatus="Confirmed" />);
    const reject = await screen.findByRole('button', { name: 'Reject' });
    await waitFor(() => expect(reject).toBeEnabled());

    // Confirm detection is disabled (already Confirmed), so Tab reaches Reject first, then Clear.
    await user.tab();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Clear' })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Reject' })).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(decideTrackReview).toHaveBeenCalledWith(trackId, expect.objectContaining({ decision: 'Rejected', expectedReviewStatus: 'Confirmed' })));
  });

  it('states that operator identity is required, without an error wall, when the route answers 401', async () => {
    vi.mocked(getTrackReview).mockRejectedValue(new ApiError({ status: 401, code: 'api_error', detail: 'Unauthorized' }));
    renderWithApp(<TrackReviewPanel trackId={trackId} reviewStatus="Unreviewed" />);
    expect(await screen.findByText(new RegExp(OPERATOR_REQUIRED))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm detection' })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    // The persisted status from the anonymous detail is still shown.
    expect(statusBadge()).toHaveTextContent('Unreviewed');
  });

  it('says an earlier run has reviewed Tracks and links to that run in search', async () => {
    vi.mocked(getTrackReview).mockResolvedValueOnce(state({
      otherRuns: [
        { processingRunId: 'AAAAAAAA-0000-4000-8000-000000000001', completedAtUtc: '2026-10-01T00:00:00Z', reviewedTrackCount: 3 },
        { processingRunId: 'aaaaaaaa-0000-4000-8000-000000000002', completedAtUtc: '2026-10-02T00:00:00Z', reviewedTrackCount: 0 },
      ],
    }));
    renderWithApp(<TrackReviewPanel trackId={trackId} reviewStatus="Unreviewed" runCompletedAtUtc="2026-10-30T00:00:00Z" />);
    const notices = await screen.findByRole('list', { name: 'Review decisions in other runs' });
    expect(within(notices).getAllByRole('listitem')).toHaveLength(1);
    expect(notices).toHaveTextContent('Earlier run has 3 reviewed Tracks');
    expect(within(notices).getByRole('link', { name: 'Search that run' }))
      .toHaveAttribute('href', '/search?processingRunId=aaaaaaaa-0000-4000-8000-000000000001');
  });

  it('pages the decision history on Review, and links the audit trail of the Track', async () => {
    const user = userEvent.setup();
    vi.mocked(getTrackReview).mockResolvedValueOnce(state({ reviewStatus: 'Confirmed', latestDecision: decision() }));
    vi.mocked(getTrackReviewHistory)
      .mockResolvedValueOnce({ trackId, items: [decision()], nextCursor: '7' })
      .mockResolvedValueOnce({ trackId, items: [decision({ decisionId: 'd0', decision: 'Rejected', resultingStatus: 'Rejected', previousStatus: 'Unreviewed', identitySource: 'development-unattributed', operatorDisplayName: 'development-unattributed' })], nextCursor: null });
    renderWithApp(<TrackReviewPanel trackId={trackId} reviewStatus="Confirmed" showHistory />);
    expect(await screen.findByRole('link', { name: 'Audit trail' })).toHaveAttribute('href', `/audit?subject=track%3A${trackId}`);

    await user.click(screen.getByText('Decision history'));
    const history = await screen.findByRole('list', { name: 'Decision history, newest first' });
    expect(within(history).getAllByRole('listitem')).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Load older decisions' }));
    await waitFor(() => expect(within(history).getAllByRole('listitem')).toHaveLength(2));
    expect(vi.mocked(getTrackReviewHistory).mock.calls[1][1]).toBe('7');
    expect(within(history).getByText('Not attributable to a person')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load older decisions' })).not.toBeInTheDocument();
  });
});

describe('one persisted status across search, inspector and Review', () => {
  it('patches the Track detail and every loaded search page from the response, then marks them stale', () => {
    const client = createMaviQueryClient();
    const otherId = '118f3f5a-2f70-7a2b-8a12-2d02f4c21450';
    client.setQueryData(queryKeys.track(trackId, ''), { id: trackId, reviewStatus: 'Unreviewed' } as TrackDetail);
    client.setQueryData(queryKeys.track(trackId, 'rev@1'), { id: trackId, reviewStatus: 'Unreviewed' } as TrackDetail);
    client.setQueryData<InfiniteData<TrackSearchResponse>>(queryKeys.trackSearch('q'), {
      pageParams: [null],
      pages: [{ items: [{ id: trackId.toUpperCase(), reviewStatus: 'Unreviewed' }, { id: otherId, reviewStatus: 'Unreviewed' }], nextCursor: null } as unknown as TrackSearchResponse],
    });
    client.setQueryData(queryKeys.trackReview(trackId), { trackId, reviewStatus: 'Unreviewed', latestDecision: null });

    applyReviewDecision(client, { trackId, reviewStatus: 'Confirmed', latestDecision: decision(), replayed: false });

    expect(client.getQueryData<TrackDetail>(queryKeys.track(trackId, ''))?.reviewStatus).toBe('Confirmed');
    expect(client.getQueryData<TrackDetail>(queryKeys.track(trackId, 'rev@1'))?.reviewStatus).toBe('Confirmed');
    const items = client.getQueryData<InfiniteData<TrackSearchResponse>>(queryKeys.trackSearch('q'))!.pages[0].items;
    expect(items.map((item) => item.reviewStatus)).toEqual(['Confirmed', 'Unreviewed']);
    expect(client.getQueryData<TrackReviewState>(queryKeys.trackReview(trackId))?.latestDecision?.decisionId).toBe(decision().decisionId);
    expect(client.getQueryState(queryKeys.trackSearch('q'))?.isInvalidated).toBe(true);
    expect(client.getQueryState(queryKeys.track(trackId, ''))?.isInvalidated).toBe(true);
    client.clear();
  });
});
