import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData, type QueryClient } from '@tanstack/react-query';
import { useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { auditPath } from '../../api/audit';
import {
  REVIEW_NOTE_MAXIMUM,
  TRACK_REVIEW_CONFLICT,
  TRACK_REVIEW_DECISION_CONFLICT,
  TRACK_REVIEW_NOTHING_TO_CLEAR,
  conflictingDecision,
  decideTrackReview,
  decisionLabel,
  getTrackReview,
  getTrackReviewHistory,
  isReviewStatus,
  newDecisionId,
  type OtherRun,
  type ReviewDecision,
  type ReviewDecisionKind,
  type TrackReviewDecided,
} from '../../api/review';
import type { TrackDetail, TrackSearchResponse } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import KeyValue from '../../shared/components/KeyValue';
import StatusBadge from '../../shared/components/StatusBadge';
import { displayTimestamp } from '../../shared/format/format';
import { ActorIdentity, OperatorRequiredNotice, isOperatorRequired, operatorMessage, retryOnce } from './operator';

/**
 * Applies a recorded decision to every cache that shows the Track's status, then
 * marks them stale so the next read is the server's. Nothing is changed before
 * the server answers: there is no optimistic update, so the inspector, the
 * search list and Review show one persisted value — the response's.
 *
 * The search pages are patched in place and marked stale without an immediate
 * refetch: refetching an open, paginated search would move the operator's
 * position in it, and the one value that changed is already the server's.
 */
export function applyReviewDecision(queryClient: QueryClient, result: TrackReviewDecided): void {
  const trackId = result.trackId.toLowerCase();
  queryClient.setQueryData(queryKeys.trackReview(trackId), (old: unknown) =>
    old && typeof old === 'object' ? { ...old, reviewStatus: result.reviewStatus, latestDecision: result.latestDecision } : old);
  queryClient.setQueriesData<TrackDetail>({ queryKey: ['track', trackId] }, (old) =>
    old ? { ...old, reviewStatus: result.reviewStatus } : old);
  patchSearchStatus(queryClient, trackId, result.reviewStatus);
  void queryClient.invalidateQueries({ queryKey: ['track', trackId] });
  void queryClient.invalidateQueries({ queryKey: queryKeys.trackReview(trackId) });
  void queryClient.invalidateQueries({ queryKey: ['tracks', 'search'], refetchType: 'none' });
  void queryClient.invalidateQueries({ queryKey: queryKeys.cases });
  void queryClient.invalidateQueries({ queryKey: ['audit'] });
}

/** The loaded search pages show the Track's status from the server's answer, without moving the operator's place in them. */
function patchSearchStatus(queryClient: QueryClient, trackId: string, reviewStatus: string): void {
  queryClient.setQueriesData<InfiniteData<TrackSearchResponse>>({ queryKey: ['tracks', 'search'] }, (old) => {
    if (!old?.pages) return old;
    let changed = false;
    const pages = old.pages.map((page) => {
      if (!page.items.some((item) => item.id.toLowerCase() === trackId)) return page;
      changed = true;
      return { ...page, items: page.items.map((item) => (item.id.toLowerCase() === trackId ? { ...item, reviewStatus } : item)) };
    });
    return changed ? { ...old, pages } : old;
  });
}

function refreshAfterConflict(queryClient: QueryClient, trackId: string, error: unknown): void {
  // A conflict names the status the server holds: the search list shows it now, as the inspector and Review will after their refetch.
  const current = error instanceof ApiError ? error.extensions.currentReviewStatus : undefined;
  if (typeof current === 'string' && isReviewStatus(current)) {
    patchSearchStatus(queryClient, trackId, current);
    queryClient.setQueriesData<TrackDetail>({ queryKey: ['track', trackId] }, (old) => (old ? { ...old, reviewStatus: current } : old));
  }
  void queryClient.invalidateQueries({ queryKey: queryKeys.trackReview(trackId) });
  void queryClient.invalidateQueries({ queryKey: ['track', trackId] });
  void queryClient.invalidateQueries({ queryKey: ['tracks', 'search'], refetchType: 'none' });
}

function decisionSummary(decision: ReviewDecision, displayTimeZoneId?: string): string {
  return `${decisionLabel(decision.decision)} by ${decision.operatorDisplayName} at ${displayTimestamp(decision.decidedAtUtc, displayTimeZoneId)}`;
}

function failureMessage(error: unknown, displayTimeZoneId?: string): string {
  if (error instanceof ApiError) {
    if (error.code === TRACK_REVIEW_CONFLICT) {
      const other = conflictingDecision(error);
      return other
        ? `Another decision was recorded first: ${decisionSummary(other, displayTimeZoneId)}. The status shown is now the recorded one; decide again if you still disagree.`
        : 'The review status changed since it was read. The status shown is now the recorded one; decide again if you still disagree.';
    }
    if (error.code === TRACK_REVIEW_NOTHING_TO_CLEAR) return 'There is no decision to clear: the Track is already Unreviewed.';
    if (error.code === TRACK_REVIEW_DECISION_CONFLICT) return 'This decision could not be recorded because its identifier was already used. Decide again.';
  }
  return operatorMessage(error, 'The decision could not be recorded.');
}

/** Other completed runs of the same video whose Tracks carry review decisions (ADR-027 §5). */
function ReprocessingNotice({ runs, runCompletedAtUtc }: { runs: OtherRun[]; runCompletedAtUtc?: string }) {
  const reviewed = runs.filter((run) => run.reviewedTrackCount > 0);
  if (reviewed.length === 0) return null;
  const current = runCompletedAtUtc ? Date.parse(runCompletedAtUtc) : Number.NaN;
  return (
    <ul className="track-review__runs" aria-label="Review decisions in other runs">
      {reviewed.map((run) => {
        const at = run.completedAtUtc ? Date.parse(run.completedAtUtc) : Number.NaN;
        const later = Number.isFinite(current) && Number.isFinite(at) && at > current;
        const count = run.reviewedTrackCount;
        return (
          <li key={run.processingRunId}>
            <Alert tone="info" announce={false}>
              {later ? 'Later' : 'Earlier'} run has {count} reviewed Track{count === 1 ? '' : 's'}. Decisions belong to the run
              they were made in and are not copied to this one.{' '}
              <Link to={`/search?processingRunId=${encodeURIComponent(run.processingRunId.toLowerCase())}`}>
                Search that run
              </Link>
            </Alert>
          </li>
        );
      })}
    </ul>
  );
}

function LatestDecision({ decision, displayTimeZoneId }: { decision: ReviewDecision | null; displayTimeZoneId?: string }) {
  if (!decision) return <p className="small muted">No decision has been recorded for this Track.</p>;
  return (
    <KeyValue
      items={[
        { label: 'Latest decision', value: decisionLabel(decision.decision) },
        {
          label: 'Operator',
          value: <ActorIdentity displayName={decision.operatorDisplayName} operatorId={decision.operatorId} identitySource={decision.identitySource} />,
        },
        { label: 'Recorded', value: `${displayTimestamp(decision.decidedAtUtc, displayTimeZoneId)} (server time)` },
        ...(decision.note ? [{ label: 'Note', value: decision.note }] : []),
      ]}
    />
  );
}

function ReviewHistory({ trackId, displayTimeZoneId }: { trackId: string; displayTimeZoneId?: string }) {
  const [open, setOpen] = useState(false);
  const history = useInfiniteQuery({
    queryKey: queryKeys.trackReviewHistory(trackId),
    queryFn: ({ pageParam, signal }) => getTrackReviewHistory(trackId, pageParam, 20, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: open,
    retry: retryOnce,
  });
  const items = history.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <details className="disclosure" onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary>Decision history</summary>
      <div className="disclosure__body stack">
        {!open ? null : history.isError && items.length === 0 ? (
          <Alert tone={isOperatorRequired(history.error) ? 'info' : 'error'}>{operatorMessage(history.error, 'The decision history could not be loaded.')}</Alert>
        ) : history.isPending ? (
          <p className="small muted" role="status">Loading the decision history…</p>
        ) : items.length === 0 ? (
          <p className="small muted">No decisions have been recorded.</p>
        ) : (
          <>
            <ol className="track-review__history" aria-label="Decision history, newest first">
              {items.map((item) => (
                <li key={item.decisionId}>
                  <strong>{decisionLabel(item.decision)}</strong>{' '}
                  <span className="muted">({item.previousStatus} → {item.resultingStatus})</span>
                  <div className="small">
                    <ActorIdentity displayName={item.operatorDisplayName} operatorId={item.operatorId} identitySource={item.identitySource} />
                    {' · '}{displayTimestamp(item.decidedAtUtc, displayTimeZoneId)}
                  </div>
                  {item.note ? <p className="small">{item.note}</p> : null}
                </li>
              ))}
            </ol>
            {history.isFetchNextPageError ? (
              <Alert tone="error">{describeError(history.error, 'More history could not be loaded.')}</Alert>
            ) : null}
            {history.hasNextPage ? (
              <div className="row">
                <Button size="sm" onClick={() => void history.fetchNextPage()} disabled={history.isFetchingNextPage}>
                  {history.isFetchingNextPage ? 'Loading…' : 'Load older decisions'}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </details>
  );
}

type Props = {
  trackId: string;
  /** The status the anonymous Track detail carries: the same persisted column. */
  reviewStatus: string;
  /** The completion time of the Track's own run, to tell an earlier run from a later one. */
  runCompletedAtUtc?: string;
  displayTimeZoneId?: string;
  /** Review shows the paginated history; the inspector keeps to the latest decision. */
  showHistory?: boolean;
  compact?: boolean;
};

/**
 * The one set of review controls (PoC S11-full; ADR-027 §1): Confirm detection,
 * Reject, and Clear back to Unreviewed. Shared by the Track inspector and Review,
 * so both say the same thing about one Track. A decision is about the detection
 * only — never who or which object it is.
 */
export default function TrackReviewPanel({ trackId: rawTrackId, reviewStatus, runCompletedAtUtc, displayTimeZoneId, showHistory = false, compact = false }: Props) {
  const trackId = rawTrackId.toLowerCase();
  const headingId = useId();
  const queryClient = useQueryClient();
  const [note, setNote] = useState('');
  const [message, setMessage] = useState<{ tone: 'success' | 'warning' | 'error' | 'info'; text: string } | null>(null);
  const state = useQuery({
    queryKey: queryKeys.trackReview(trackId),
    queryFn: ({ signal }) => getTrackReview(trackId, signal),
    retry: retryOnce,
  });
  const operatorRequired = isOperatorRequired(state.error);
  const persisted = state.data?.reviewStatus ?? reviewStatus;
  // One decisionId per intended decision until the server answers it: a retry after a lost response replays the same
  // request, which the server recognises (200, replayed) instead of refusing it as a conflict with itself.
  const attempt = useRef<{ key: string; decisionId: string } | null>(null);
  const decide = useMutation({
    mutationFn: (decision: ReviewDecisionKind) => {
      if (!isReviewStatus(persisted)) throw new Error('The Track has no readable review status.');
      const trimmed = note.trim() ? note : undefined;
      const key = JSON.stringify([trackId, decision, persisted, trimmed ?? null]);
      if (attempt.current?.key !== key) attempt.current = { key, decisionId: newDecisionId() };
      return decideTrackReview(trackId, {
        decisionId: attempt.current.decisionId,
        decision,
        expectedReviewStatus: persisted,
        note: trimmed,
      });
    },
    onMutate: () => setMessage(null),
    onSuccess: (result) => {
      attempt.current = null;
      applyReviewDecision(queryClient, result);
      setNote('');
      setMessage({
        tone: 'success',
        text: result.replayed
          ? `Already recorded: ${decisionLabel(result.decision.decision)}. Status: ${result.reviewStatus}.`
          : `Recorded: ${decisionLabel(result.latestDecision.decision)}. Status: ${result.reviewStatus}.`,
      });
    },
    onError: (error) => {
      // A refusal is a definitive answer: the next attempt is a new decision. A lost response or a server failure is not.
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) attempt.current = null;
      if (error instanceof ApiError && error.status === 409) refreshAfterConflict(queryClient, trackId, error);
      setMessage({
        tone: error instanceof ApiError && error.code === TRACK_REVIEW_CONFLICT ? 'warning' : isOperatorRequired(error) ? 'info' : 'error',
        text: failureMessage(error, displayTimeZoneId),
      });
    },
  });

  const pending = decide.isPending;
  // The controls decide against the operator route's status once it is read; until
  // then the anonymous detail's value (the same column) is what they would expect.
  const ready = !state.isPending || state.isError;
  const canDecide = ready && !pending && isReviewStatus(persisted);
  const noteTooLong = note.length > REVIEW_NOTE_MAXIMUM;

  const title = compact ? <h3 id={headingId}>Review decision</h3> : <h2 id={headingId}>Review decision</h2>;

  return (
    <section className="stack track-review" aria-labelledby={headingId}>
      {title}
      <div className="row">
        <span className="small muted">Status</span>
        <StatusBadge status={persisted} />
      </div>
      {operatorRequired ? (
        <OperatorRequiredNotice />
      ) : (
        <>
          <StateRegion
            kind="panel"
            state={fromQuery(state)}
            label="review decision"
            loadingLabel="Loading the review decision…"
            unavailableMessage={(error) => operatorMessage(error, 'The review decision could not be loaded.')}
            retryable={(error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500)}
            degradedMessage="Showing the last known review decision; refreshing failed."
            onRetry={() => void state.refetch()}
          >
            {(data) => (
              <div className="stack">
                <LatestDecision decision={data.latestDecision} displayTimeZoneId={displayTimeZoneId} />
                <ReprocessingNotice runs={data.otherRuns} runCompletedAtUtc={runCompletedAtUtc} />
              </div>
            )}
          </StateRegion>
          <div className="row" role="group" aria-label="Review decision controls">
            <Button
              size="sm"
              icon="check"
              onClick={() => decide.mutate('Confirmed')}
              disabled={!canDecide || noteTooLong || persisted === 'Confirmed'}
            >
              Confirm detection
            </Button>
            <Button size="sm" icon="x" onClick={() => decide.mutate('Rejected')} disabled={!canDecide || noteTooLong || persisted === 'Rejected'}>
              Reject
            </Button>
            {persisted !== 'Unreviewed' ? (
              <Button size="sm" variant="ghost" onClick={() => decide.mutate('Cleared')} disabled={!canDecide || noteTooLong}>
                Clear
              </Button>
            ) : null}
            {pending ? <span className="small muted" role="status">Recording the decision…</span> : null}
          </div>
          <Field
            label="Note"
            optional
            error={noteTooLong ? `A note is at most ${REVIEW_NOTE_MAXIMUM} characters.` : null}
            help={`${note.length} / ${REVIEW_NOTE_MAXIMUM}. Stored with the decision and shown only to operators.`}
          >
            {(control) => (
              <textarea {...control} rows={2} value={note} disabled={pending} onChange={(event) => setNote(event.target.value)} />
            )}
          </Field>
          {message ? (
            message.tone === 'error' ? <Alert tone="error">{message.text}</Alert>
              : <Alert tone={message.tone}>{message.text}</Alert>
          ) : null}
          {showHistory ? <ReviewHistory trackId={trackId} displayTimeZoneId={displayTimeZoneId} /> : null}
          <div className="row">
            <ButtonLink size="sm" variant="ghost" to={auditPath(`track:${trackId}`)}>Audit trail</ButtonLink>
          </div>
        </>
      )}
      <p className="small muted">
        {state.data?.statement
          ?? 'A review decision says whether the detection is correct. It never says who or which object the Track shows.'}
      </p>
    </section>
  );
}
