import { ApiError, apiJson, apiRequest } from './client';

/**
 * Track review decisions (PoC S11-full; ADR-027 §1, §5). Every route requires the
 * operator (ADR-010). A decision says whether the detection is correct — never who
 * or which object the Track shows — and it is appended, never edited: the status
 * is the projection of the latest decision.
 */

export const REVIEW_STATUSES = ['Unreviewed', 'Confirmed', 'Rejected'] as const;
export type ReviewStatus = (typeof REVIEW_STATUSES)[number];

export const REVIEW_DECISIONS = ['Confirmed', 'Rejected', 'Cleared'] as const;
export type ReviewDecisionKind = (typeof REVIEW_DECISIONS)[number];

/** The longest note the platform accepts (`TrackReviewDecision.NormaliseNote`). */
export const REVIEW_NOTE_MAXIMUM = 1000;

export const TRACK_REVIEW_CONFLICT = 'track_review_conflict';
export const TRACK_REVIEW_DECISION_CONFLICT = 'track_review_decision_conflict';
export const TRACK_REVIEW_NOTHING_TO_CLEAR = 'track_review_nothing_to_clear';

export type ReviewDecision = {
  decisionId: string;
  trackId: string;
  decision: ReviewDecisionKind;
  previousStatus: ReviewStatus;
  resultingStatus: ReviewStatus;
  note: string | null;
  operatorId: string;
  operatorDisplayName: string;
  identitySource: string;
  decidedAtUtc: string;
  auditEntryId: string;
};

export type OtherRun = {
  processingRunId: string;
  completedAtUtc: string | null;
  reviewedTrackCount: number;
};

export type TrackReviewState = {
  trackId: string;
  processingRunId: string;
  reviewStatus: ReviewStatus;
  latestDecision: ReviewDecision | null;
  otherRuns: OtherRun[];
  statement: string;
};

export type TrackReviewDecided = {
  trackId: string;
  reviewStatus: ReviewStatus;
  latestDecision: ReviewDecision;
  replayed: boolean;
  /** The decision this request recorded or, on a replay, recorded before; it differs from latestDecision when later decisions followed. */
  decision: ReviewDecision;
};

export type TrackReviewHistoryPage = {
  trackId: string;
  items: ReviewDecision[];
  nextCursor: string | null;
};

export type TrackReviewRequest = {
  decisionId: string;
  decision: ReviewDecisionKind;
  expectedReviewStatus: ReviewStatus;
  note?: string;
};

// --- Narrowing ----------------------------------------------------------------------
// The wire is not trusted to have the shape a caller hopes for: a value outside the
// vocabulary is a contract fault, reported as one, never rendered as a status.

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function text(value: unknown): value is string {
  return typeof value === 'string';
}

export function isReviewStatus(value: unknown): value is ReviewStatus {
  return (REVIEW_STATUSES as readonly unknown[]).includes(value);
}

function isDecisionKind(value: unknown): value is ReviewDecisionKind {
  return (REVIEW_DECISIONS as readonly unknown[]).includes(value);
}

/** One decision as the platform sends it, or null when it is not one. */
export function narrowDecision(value: unknown): ReviewDecision | null {
  if (!isRecord(value)) return null;
  const { decisionId, trackId, decision, previousStatus, resultingStatus, note, operatorId, operatorDisplayName, identitySource,
    decidedAtUtc, auditEntryId } = value;
  if (!text(decisionId) || !text(trackId) || !isDecisionKind(decision) || !isReviewStatus(previousStatus)
    || !isReviewStatus(resultingStatus) || !(note === null || note === undefined || text(note)) || !text(operatorId)
    || !text(operatorDisplayName) || !text(identitySource) || !text(decidedAtUtc) || !text(auditEntryId)) return null;
  return {
    decisionId, trackId, decision, previousStatus, resultingStatus, note: note ?? null, operatorId, operatorDisplayName,
    identitySource, decidedAtUtc, auditEntryId,
  };
}

function contractFault(what: string): ApiError {
  return new ApiError({ status: 502, code: 'review_contract_invalid', detail: `The ${what} did not have the expected shape.` });
}

export function narrowReviewState(value: unknown): TrackReviewState {
  if (!isRecord(value) || !text(value.trackId) || !text(value.processingRunId) || !isReviewStatus(value.reviewStatus)
    || !Array.isArray(value.otherRuns) || !text(value.statement)) throw contractFault('review state');
  const latestDecision = value.latestDecision === null || value.latestDecision === undefined ? null : narrowDecision(value.latestDecision);
  if (value.latestDecision && !latestDecision) throw contractFault('review state');
  const otherRuns: OtherRun[] = [];
  for (const run of value.otherRuns) {
    if (!isRecord(run) || !text(run.processingRunId) || typeof run.reviewedTrackCount !== 'number') throw contractFault('review state');
    otherRuns.push({
      processingRunId: run.processingRunId,
      completedAtUtc: text(run.completedAtUtc) ? run.completedAtUtc : null,
      reviewedTrackCount: run.reviewedTrackCount,
    });
  }
  return {
    trackId: value.trackId, processingRunId: value.processingRunId, reviewStatus: value.reviewStatus, latestDecision, otherRuns,
    statement: value.statement,
  };
}

export function narrowDecided(value: unknown): TrackReviewDecided {
  if (!isRecord(value) || !text(value.trackId) || !isReviewStatus(value.reviewStatus)) throw contractFault('review decision');
  const latestDecision = narrowDecision(value.latestDecision);
  if (!latestDecision) throw contractFault('review decision');
  const decision = value.decision === undefined ? latestDecision : narrowDecision(value.decision);
  if (!decision) throw contractFault('review decision');
  return { trackId: value.trackId, reviewStatus: value.reviewStatus, latestDecision, replayed: value.replayed === true, decision };
}

export function narrowHistory(value: unknown): TrackReviewHistoryPage {
  if (!isRecord(value) || !text(value.trackId) || !Array.isArray(value.items)) throw contractFault('review history');
  const items = value.items.map(narrowDecision);
  if (items.some((item) => item === null)) throw contractFault('review history');
  return { trackId: value.trackId, items: items as ReviewDecision[], nextCursor: text(value.nextCursor) ? value.nextCursor : null };
}

/** The decision a 409 `track_review_conflict` names: the one recorded first. */
export function conflictingDecision(error: unknown): ReviewDecision | null {
  return error instanceof ApiError ? narrowDecision(error.extensions.currentDecision) : null;
}

// --- Routes ---------------------------------------------------------------------------

const enc = encodeURIComponent;

export async function getTrackReview(trackId: string, signal?: AbortSignal): Promise<TrackReviewState> {
  return narrowReviewState(await apiRequest<unknown>('/api/tracks/' + enc(trackId) + '/review', { signal }));
}

export async function getTrackReviewHistory(trackId: string, cursor?: string | null, limit = 20, signal?: AbortSignal): Promise<TrackReviewHistoryPage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  return narrowHistory(await apiRequest<unknown>('/api/tracks/' + enc(trackId) + '/review-history?' + params.toString(), { signal }));
}

export async function decideTrackReview(trackId: string, request: TrackReviewRequest): Promise<TrackReviewDecided> {
  const body: TrackReviewRequest = {
    decisionId: request.decisionId,
    decision: request.decision,
    expectedReviewStatus: request.expectedReviewStatus,
    ...(request.note && request.note.trim() ? { note: request.note } : {}),
  };
  return narrowDecided(await apiJson<unknown>('/api/tracks/' + enc(trackId) + '/review', 'POST', body));
}

/** A fresh client decision id: one per submitted decision, so a replay of the same submission is recognised. */
export function newDecisionId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  // `randomUUID` exists only in a secure context; a plain-HTTP host name on the
  // site LAN is not one, while `getRandomValues` is always available. RFC 4122 v4.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** "Confirmed detection" etc.: the words the operator chose, never an identity claim. */
export function decisionLabel(decision: ReviewDecisionKind): string {
  switch (decision) {
    case 'Confirmed': return 'Detection confirmed';
    case 'Rejected': return 'Detection rejected';
    case 'Cleared': return 'Review cleared';
  }
}
