import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './client';
import { conflictingDecision, decideTrackReview, getTrackReview, newDecisionId } from './review';
import { addCaseItem, listCases } from './cases';
import { auditPath, auditQueryString } from './audit';

const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21450';

const decision = {
  decisionId: '0b9f1c9e-6a43-4c1f-9d3e-1f2a3b4c5d6e', trackId, decision: 'Confirmed', previousStatus: 'Unreviewed',
  resultingStatus: 'Confirmed', note: null, operatorId: 'SITE\\asha', operatorDisplayName: 'Asha', identitySource: 'windows-negotiate',
  decidedAtUtc: '2026-10-31T08:00:00Z', auditEntryId: 'a1',
};

function respond(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
}

afterEach(() => vi.unstubAllGlobals());

describe('PoC S11-full review client', () => {
  it('posts a decision with its client decisionId and the status it expects', async () => {
    const fetch = respond({ trackId, reviewStatus: 'Confirmed', latestDecision: decision, replayed: false });
    vi.stubGlobal('fetch', fetch);
    const id = newDecisionId();
    const result = await decideTrackReview(trackId, { decisionId: id, decision: 'Confirmed', expectedReviewStatus: 'Unreviewed', note: 'clear view' });

    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe(`/api/tracks/${trackId}/review`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ decisionId: id, decision: 'Confirmed', expectedReviewStatus: 'Unreviewed', note: 'clear view' });
    expect(result.reviewStatus).toBe('Confirmed');
    expect(result.latestDecision.operatorDisplayName).toBe('Asha');
  });

  it('makes RFC 4122 v4 decision ids, distinct per decision', () => {
    const a = newDecisionId();
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newDecisionId()).not.toBe(a);
  });

  it('reads the conflicting decision a 409 carries', async () => {
    vi.stubGlobal('fetch', respond({ status: 409, code: 'track_review_conflict', currentReviewStatus: 'Rejected',
      currentDecision: { ...decision, decision: 'Rejected', resultingStatus: 'Rejected' } }, 409));
    const error = await decideTrackReview(trackId, { decisionId: newDecisionId(), decision: 'Confirmed', expectedReviewStatus: 'Unreviewed' })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe('track_review_conflict');
    expect(conflictingDecision(error)?.decision).toBe('Rejected');
  });

  it('refuses a review state outside the vocabulary as a contract fault', async () => {
    vi.stubGlobal('fetch', respond({ trackId, processingRunId: 'r', reviewStatus: 'Matched', latestDecision: null, otherRuns: [], statement: 's' }));
    await expect(getTrackReview(trackId)).rejects.toMatchObject({ code: 'review_contract_invalid' });
  });
});

describe('PoC S11-full case and audit clients', () => {
  it('narrows a case list to the cases holding a subject', async () => {
    const fetch = respond({ statement: 's', cases: [] });
    vi.stubGlobal('fetch', fetch);
    await listCases({ kind: 'AnalyticEvent', subjectId: 'ABC' }, 50);
    expect(fetch.mock.calls[0][0]).toBe('/api/cases?subjectKind=AnalyticEvent&subjectId=abc&limit=50');
  });

  it('adds an item with its kind, subject and note', async () => {
    const fetch = respond({
      itemId: 'i1', kind: 'Track', subjectId: trackId, note: 'seen at gate',
      addedBy: { operatorId: 'o', displayName: 'Asha', identitySource: 'windows-negotiate', atUtc: '2026-10-31T08:00:00Z', auditEntryId: 'a' },
      removedBy: null, removalNote: null, subject: { available: true, earlierRun: false },
    }, 201);
    vi.stubGlobal('fetch', fetch);
    await addCaseItem('c1', { kind: 'Track', subjectId: trackId, note: 'seen at gate' });
    expect(fetch.mock.calls[0][0]).toBe('/api/cases/c1/items');
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ kind: 'Track', subjectId: trackId, note: 'seen at gate' });
  });

  it('repeats subject filters in the audit query and in the audit link', () => {
    expect(auditQueryString({ subjects: ['track:t1', 'case:c1'], action: 'cases.item-added' }, 'cur', 50))
      .toBe('subject=track%3At1&subject=case%3Ac1&action=cases.item-added&limit=50&cursor=cur');
    expect(auditPath('case:c1')).toBe('/audit?subject=case%3Ac1');
  });
});
