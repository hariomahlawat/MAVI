import { useMutation, useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ask, getAskStatus, stageText, type AskResponse } from '../../api/ask';
import { runQuery, type QueryEnvelope, type StructuredQuery } from '../../api/query';
import EmptyState from '../../shared/components/EmptyState';
import Panel from '../../shared/components/Panel';
import { CoverageStatus, Refusal, Result } from '../advanced-search/AdvancedSearchPage';
import { stateFromQuery } from '../advanced-search/queryBuilder';
import { answerSentence, describeQuery } from './interpretation';

const MAXIMUM_QUESTION_LENGTH = 500;

/** The measured accuracy (register C9.2, D-S10-10): stated wherever a proposal is shown. */
export const ACCURACY =
  'On 40 independently written questions, MAVI interpreted 20 exactly with the larger language model and 19 with the laptop model.';

/**
 * Ask MAVI (Stage 9; ADR-026; register C9.3; UI specification §17.1).
 *
 * Ask proposes, the operator confirms (D-S10-10). The server's language role translates
 * the question into a structured query or refuses; the page shows the proposal ("Interpreted
 * as") and runs it only when the operator presses Run, through the same contract and service
 * as Advanced Search, or opens it in Advanced Search to change it. No answer is computed or
 * shown before Run. This surface renders only platform data: the "Interpreted as" lines come
 * from the server's canonical query and catalogue names, the answer from the S9 envelope, a
 * refusal from its typed stage and code. A refusal is shown plainly and never retried.
 */
export default function AskMaviPage() {
  const status = useQuery({ queryKey: ['ask-status'], queryFn: ({ signal }) => getAskStatus(signal), staleTime: 30_000 });
  const [question, setQuestion] = useState('');
  const [referenceDate, setReferenceDate] = useState('');
  const run = useMutation({ mutationFn: (input: { question: string; referenceDate: string }) => ask(input.question, input.referenceDate || null) });

  const unavailable = status.data !== undefined && !status.data.answering;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (trimmed.length === 0 || run.isPending) return;
    run.mutate({ question: trimmed, referenceDate });
  };

  return (
    <div className="query-page ask-page">
      <header className="query-page__header">
        <h1>Ask MAVI</h1>
        <p className="query-page__disclosure">
          Ask about recorded Tracks and Events in plain language. MAVI proposes a structured query and shows how it read the
          question; nothing runs until you press Run, and the answer comes only from that query&apos;s result. Questions
          outside the query contract are refused. {ACCURACY}
        </p>
      </header>

      {unavailable ? (
        <div className="query-page__refusal" role="status">
          <strong>Ask MAVI is not available on this installation.</strong>
          <p>No language pack is bound, or it is not answering. <Link to="/query">Advanced Search</Link> asks the same questions by hand.</p>
        </div>
      ) : null}

      <form className="ask-page__form" onSubmit={submit} aria-label="Ask MAVI">
        <label className="ask-page__question">
          <span>Question</span>
          <textarea
            value={question}
            maxLength={MAXIMUM_QUESTION_LENGTH}
            rows={2}
            placeholder="For example: how many Person Tracks were there today, by hour?"
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) submit(event);
            }}
          />
        </label>
        <label className="ask-page__date">
          <span>&ldquo;Today&rdquo; is</span>
          <input type="date" value={referenceDate} onChange={(event) => setReferenceDate(event.target.value)} aria-describedby="ask-date-hint" />
          <small id="ask-date-hint">{status.data?.siteTimeZoneId ? `site date, ${status.data.siteTimeZoneId}; empty means the current date` : 'empty means the current site date'}</small>
        </label>
        <button type="submit" className="button button--primary" disabled={run.isPending || unavailable || question.trim().length === 0}>
          {run.isPending ? 'Asking…' : 'Ask'}
        </button>
      </form>

      {run.isError ? <EmptyState title="The question could not be asked">The server could not be reached or failed. Try again.</EmptyState> : null}
      {/* One proposal per question: a new question never shows the previous question's answer. */}
      {run.data ? <AskAnswer key={run.submittedAt} response={run.data} /> : null}

      <p className="query-page__muted">{status.data?.disclosure ?? 'PoC profile, Development evidence, not Production-qualified.'}</p>
    </div>
  );
}

/** One response: a refusal, plainly; or the proposed query, which runs only when the operator presses Run (D-S10-10). */
export function AskAnswer({ response }: { response: AskResponse }) {
  const navigate = useNavigate();
  const run = useMutation({ mutationFn: (query: StructuredQuery) => runQuery(query) });
  if (response.outcome === 'refused' || !response.interpretation) {
    const refusal = response.refusal;
    return (
      <div className="query-page__refusal" role="alert" aria-label="Refusal">
        <strong>{refusal ? stageText(refusal.stage) : 'Refused'}</strong>
        <p>{refusal?.message}</p>
        {refusal ? <p className="query-page__muted">Reason <code>{refusal.code}</code>{refusal.path ? <> at <code>{refusal.path}</code></> : null}.</p> : null}
        <p className="query-page__muted">Nothing was answered. Rephrase within what MAVI can query, or use <Link to="/query">Advanced Search</Link>.</p>
      </div>
    );
  }

  const interpretation = response.interpretation;
  const timeZoneId = response.siteTimeZoneId;
  const loadable = stateFromQuery(interpretation.resolvedQuery);
  return (
    <>
      <Panel title="Interpreted as">
        <dl className="ask-page__interpretation" aria-label="Interpreted as">
          {describeQuery(interpretation.resolvedQuery, interpretation.references, timeZoneId).map((line) => (
            <div key={line.label}>
              <dt>{line.label}</dt>
              <dd>{line.value}</dd>
            </div>
          ))}
        </dl>
        <details>
          <summary>The proposed query</summary>
          <pre className="query-page__resolved" aria-label="Resolved query">{JSON.stringify(interpretation.resolvedQuery, null, 2)}</pre>
          <p className="query-page__muted">
            Fingerprint <code title={interpretation.queryFingerprint}>{interpretation.queryFingerprint.slice(0, 16)}…</code>
          </p>
        </details>
        <p className="query-page__muted">{ACCURACY} Check that this is what you meant. Nothing has run yet.</p>
        <div className="ask-page__actions">
          <button
            type="button"
            className="button button--primary"
            disabled={run.isPending}
            onClick={() => run.mutate(interpretation.resolvedQuery)}
          >
            {run.isPending ? 'Running…' : 'Run'}
          </button>
          <button
            type="button"
            className="button"
            disabled={loadable.state === null}
            title={loadable.problem ?? undefined}
            onClick={() => navigate('/query', { state: { askQuery: interpretation.resolvedQuery } })}
          >
            Open in Advanced Search
          </button>
          {loadable.problem ? <small className="query-page__muted">{loadable.problem}</small> : null}
        </div>
      </Panel>

      {run.isError ? <Refusal error={run.error} /> : null}
      {run.data ? <AskResult envelope={run.data} timeZoneId={timeZoneId} /> : null}
    </>
  );
}

/** The answer to a query the operator ran: the S9 envelope only, as Advanced Search shows it. */
export function AskResult({ envelope, timeZoneId }: { envelope: QueryEnvelope; timeZoneId: string }) {
  const sentence = answerSentence(envelope, timeZoneId);
  return (
    <>
      <CoverageStatus envelope={envelope} />

      <Panel title="Answer">
        {sentence ? <p className="ask-page__sentence" aria-label="Answer summary">{sentence}</p> : null}
        <Result envelope={envelope} displayTimeZoneId={timeZoneId} />
      </Panel>

      {/* Outside the answer: the answer panel shows envelope values only. */}
      <details>
        <summary>The query as run</summary>
        <pre className="query-page__resolved" aria-label="Query as run">{JSON.stringify(envelope.resolvedQuery, null, 2)}</pre>
        <p className="query-page__muted">
          Fingerprint <code title={envelope.queryFingerprint}>{envelope.queryFingerprint.slice(0, 16)}…</code>
          {envelope.snapshot.visibilitySequence !== null ? `, snapshot ${envelope.snapshot.visibilitySequence}` : ''}.
        </p>
      </details>

      <p className="query-page__muted">{envelope.disclosure}</p>
    </>
  );
}
