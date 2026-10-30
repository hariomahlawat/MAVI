import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { auditPath } from '../../api/audit';
import {
  CASE_ITEM_NOTE_MAXIMUM,
  CASE_NOTE_MAXIMUM,
  CASE_STATEMENT,
  addCaseNote,
  caseItemKindLabel,
  getCase,
  removeCaseItem,
  type CaseItem,
} from '../../api/cases';
import { ApiError, isGuid } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { queryKeys } from '../../app/queryClient';
import { fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button, { ButtonLink } from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { displayTimestamp } from '../../shared/format/format';
import { ContextBar } from '../../shared/workspace';
import { ActorIdentity, OperatorRequiredNotice, isOperatorRequired, operatorMessage, retryOnce } from '../review/operator';

/** What the case knows about an item's subject, in one line. */
function subjectLine(item: CaseItem, displayTimeZoneId?: string): string {
  const subject = item.subject;
  const parts: string[] = [];
  if (item.kind === 'AnalyticEvent' && subject.ruleId) parts.push(subject.ruleId);
  if (item.kind === 'Entity' && subject.entityDisplayCode) parts.push(subject.entityDisplayCode);
  if (subject.objectClass) parts.push(subject.objectClass);
  if (subject.cameraName) parts.push(subject.cameraName);
  if (subject.startUtc) parts.push(displayTimestamp(subject.startUtc, displayTimeZoneId));
  return parts.join(' · ');
}

/** Where an item's subject can be seen again, when it still resolves. */
function SubjectLinks({ item }: { item: CaseItem }) {
  const { subject } = item;
  if (!subject.available) return null;
  const id = item.subjectId.toLowerCase();
  if (item.kind === 'Track') {
    return (
      <span className="row">
        {subject.videoAssetId ? (
          <Link to={`/review/video/${subject.videoAssetId.toLowerCase()}?trackId=${encodeURIComponent(id)}`}>Open in Review</Link>
        ) : null}
        {subject.processingRunId ? (
          <Link to={`/search?processingRunId=${encodeURIComponent(subject.processingRunId.toLowerCase())}&track=${encodeURIComponent(id)}`}>
            Inspect in search
          </Link>
        ) : null}
      </span>
    );
  }
  if (item.kind === 'AnalyticEvent' && subject.cameraId) {
    return <Link to={`/cameras/${subject.cameraId.toLowerCase()}/events?event=${encodeURIComponent(id)}`}>Open the event</Link>;
  }
  return null;
}

function RemoveItem({ caseId, item }: { caseId: string; item: CaseItem }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const remove = useMutation({
    mutationFn: () => removeCaseItem(caseId, item.itemId, note.trim() ? note : null),
    onSuccess: () => {
      setOpen(false);
      setNote('');
      void queryClient.invalidateQueries({ queryKey: queryKeys.cases });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
  if (!open) {
    return <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>Remove from case</Button>;
  }
  const tooLong = note.length > CASE_ITEM_NOTE_MAXIMUM;
  return (
    <form className="stack" aria-label="Remove from case" onSubmit={(event) => { event.preventDefault(); remove.mutate(); }} noValidate>
      <p className="small">
        The item stays in the case&apos;s record, marked removed with who removed it, when and why. It is never deleted.
      </p>
      <Field label="Removal note" optional error={tooLong ? `A note is at most ${CASE_ITEM_NOTE_MAXIMUM} characters.` : null}
        help={`${note.length} / ${CASE_ITEM_NOTE_MAXIMUM}`}>
        {(control) => <textarea {...control} rows={2} value={note} disabled={remove.isPending} onChange={(event) => setNote(event.target.value)} />}
      </Field>
      {remove.isError ? (
        <Alert tone={isOperatorRequired(remove.error) ? 'info' : 'error'}>{operatorMessage(remove.error, 'The removal could not be recorded.')}</Alert>
      ) : null}
      <div className="row">
        <Button type="submit" size="sm" variant="danger" disabled={remove.isPending || tooLong}>
          {remove.isPending ? 'Recording…' : 'Record removal'}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={remove.isPending}>Cancel</Button>
      </div>
    </form>
  );
}

function ItemRow({ caseId, item, displayTimeZoneId }: { caseId: string; item: CaseItem; displayTimeZoneId?: string }) {
  const removed = item.removedBy !== null;
  const line = subjectLine(item, displayTimeZoneId);
  return (
    <li className={removed ? 'case-item case-item--removed' : 'case-item'}>
      <div className="row">
        <strong className="case-item__subject">
          {caseItemKindLabel(item.kind)}{line ? ` · ${line}` : ''}
        </strong>
        {removed ? <StatusBadge tone="neutral">Removed</StatusBadge> : null}
        {item.subject.earlierRun ? <StatusBadge tone="stale" title="This Track or event belongs to an earlier processing run of its video.">Earlier run</StatusBadge> : null}
        {!item.subject.available ? <StatusBadge tone="unavailable" title="The subject no longer resolves; the item is kept.">Unavailable</StatusBadge> : null}
        {item.kind === 'Track' && item.subject.reviewStatus ? <StatusBadge status={item.subject.reviewStatus} /> : null}
      </div>
      <p className="small muted">
        <code>{item.subjectId}</code>
      </p>
      <p className="small">
        Added {displayTimestamp(item.addedBy.atUtc, displayTimeZoneId)} by{' '}
        <ActorIdentity displayName={item.addedBy.displayName} operatorId={item.addedBy.operatorId} identitySource={item.addedBy.identitySource} />
      </p>
      {item.note ? <p className="small case-item__note">{item.note}</p> : null}
      {item.removedBy ? (
        <p className="small case-item__removal">
          Removed {displayTimestamp(item.removedBy.atUtc, displayTimeZoneId)} by{' '}
          <ActorIdentity displayName={item.removedBy.displayName} operatorId={item.removedBy.operatorId} identitySource={item.removedBy.identitySource} />
          {item.removalNote ? <>: {item.removalNote}</> : ' (no removal note)'}
        </p>
      ) : null}
      <div className="row">
        <SubjectLinks item={item} />
        {!removed ? <RemoveItem caseId={caseId} item={item} /> : null}
      </div>
    </li>
  );
}

function AddNote({ caseId }: { caseId: string }) {
  const queryClient = useQueryClient();
  const [body, setBody] = useState('');
  const [error, setError] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: () => addCaseNote(caseId, body),
    onSuccess: () => {
      setBody('');
      void queryClient.invalidateQueries({ queryKey: queryKeys.cases });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!body.trim()) { setError('Write the note first.'); return; }
    if (body.length > CASE_NOTE_MAXIMUM) { setError(`A note is at most ${CASE_NOTE_MAXIMUM} characters.`); return; }
    setError(null);
    add.mutate();
  };
  return (
    <form className="stack" aria-label="Add a note" onSubmit={submit} noValidate>
      <Field label="New note" error={error} help={`${body.length} / ${CASE_NOTE_MAXIMUM}. Notes are kept as written; they cannot be edited or deleted.`}>
        {(control) => <textarea {...control} rows={3} value={body} disabled={add.isPending} onChange={(event) => setBody(event.target.value)} />}
      </Field>
      {add.isError ? (
        <Alert tone={isOperatorRequired(add.error) ? 'info' : 'error'}>{operatorMessage(add.error, 'The note could not be added.')}</Alert>
      ) : null}
      <div className="row">
        <Button type="submit" size="sm" disabled={add.isPending}>{add.isPending ? 'Adding…' : 'Add note'}</Button>
      </div>
    </form>
  );
}

/** One case (PoC S11-full; ADR-027 §2): its items — removed ones kept and marked — and its notes. */
export default function CaseDetailPage() {
  const { caseId: rawCaseId = '' } = useParams();
  const valid = isGuid(rawCaseId);
  const caseId = valid ? rawCaseId.toLowerCase() : '';
  const systemConfig = useQuery({ queryKey: queryKeys.systemConfig, queryFn: ({ signal }) => getSystemConfig(signal), staleTime: 60_000 });
  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId;
  const detail = useQuery({
    queryKey: queryKeys.caseDetail(caseId),
    queryFn: ({ signal }) => getCase(caseId, signal),
    enabled: valid,
    retry: retryOnce,
  });
  const label = detail.data?.case.title ?? (valid ? `Case ${caseId.slice(0, 8)}…` : 'Case');

  if (!valid) {
    return (
      <section className="page">
        <ContextBar surface="case-detail" object={{ label }} />
        <Alert tone="error">The case identifier in this route is invalid.</Alert>
      </section>
    );
  }

  return (
    <section className="page">
      <ContextBar
        surface="case-detail"
        object={{ label }}
        actions={<ButtonLink size="sm" variant="ghost" to={auditPath(`case:${caseId}`)}>Audit trail</ButtonLink>}
      />
      <div className="stack">
        <p className="small muted">{detail.data?.statement ?? CASE_STATEMENT}</p>
        {isOperatorRequired(detail.error) ? (
          <OperatorRequiredNotice />
        ) : (
          <StateRegion
            kind="page"
            state={fromQuery(detail)}
            label="case"
            loadingLabel="Loading the case…"
            unavailableMessage={(error) => error instanceof ApiError && error.status === 404
              ? 'The case does not exist.'
              : operatorMessage(error, 'The case could not be loaded.')}
            retryable={(error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500)}
            degradedMessage="Showing the last known case; refreshing failed."
            onRetry={() => void detail.refetch()}
          >
            {(data) => {
              const active = data.items.filter((item) => item.removedBy === null);
              const removed = data.items.filter((item) => item.removedBy !== null);
              return (
                <>
                  <Panel title={data.case.title}>
                    <div className="stack">
                      {data.case.purpose ? <p>{data.case.purpose}</p> : <p className="small muted">No purpose was recorded.</p>}
                      <p className="small">
                        Created {displayTimestamp(data.case.createdBy.atUtc, displayTimeZoneId)} by{' '}
                        <ActorIdentity displayName={data.case.createdBy.displayName} operatorId={data.case.createdBy.operatorId}
                          identitySource={data.case.createdBy.identitySource} />
                      </p>
                    </div>
                  </Panel>
                  <Panel title={`Items (${active.length})`}>
                    {active.length === 0 ? (
                      <p className="small muted">No active items. Add a Track or an event from where you found it.</p>
                    ) : (
                      <ul className="case-items" aria-label="Items">
                        {active.map((item) => <ItemRow key={item.itemId} caseId={caseId} item={item} displayTimeZoneId={displayTimeZoneId} />)}
                      </ul>
                    )}
                    {removed.length > 0 ? (
                      <>
                        <h3>Removed items ({removed.length})</h3>
                        <ul className="case-items" aria-label="Removed items">
                          {removed.map((item) => <ItemRow key={item.itemId} caseId={caseId} item={item} displayTimeZoneId={displayTimeZoneId} />)}
                        </ul>
                      </>
                    ) : null}
                  </Panel>
                  <Panel title={`Notes (${data.notes.length})`}>
                    <div className="stack">
                      {data.notes.length === 0 ? <p className="small muted">No notes yet.</p> : (
                        <ol className="case-notes" aria-label="Notes">
                          {data.notes.map((note) => (
                            <li key={note.noteId}>
                              <p className="case-notes__body">{note.body}</p>
                              <p className="small muted">
                                {displayTimestamp(note.author.atUtc, displayTimeZoneId)} by{' '}
                                <ActorIdentity displayName={note.author.displayName} operatorId={note.author.operatorId} identitySource={note.author.identitySource} />
                              </p>
                            </li>
                          ))}
                        </ol>
                      )}
                      <AddNote caseId={caseId} />
                    </div>
                  </Panel>
                </>
              );
            }}
          </StateRegion>
        )}
      </div>
    </section>
  );
}
