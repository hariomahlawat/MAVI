import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AUDIT_MAXIMUM_SUBJECTS, auditQueryString, isUnattributed, readAudit, type AuditEntry, type AuditFilter } from '../../api/audit';
import { getSystemConfig } from '../../api/system';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromInfiniteQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import { displayTimestamp } from '../../shared/format/format';
import { ContextBar } from '../../shared/workspace';
import { OperatorRequiredNotice, isOperatorRequired, operatorMessage, retryOnce, retryable } from '../review/operator';

const PAGE_SIZE = 50;
const SUBJECT_PATTERN = /^[^:\s]+:[^\s]+$/;

export function readAuditFilter(params: URLSearchParams): AuditFilter {
  return {
    subjects: params.getAll('subject').filter((subject) => SUBJECT_PATTERN.test(subject)).slice(0, AUDIT_MAXIMUM_SUBJECTS),
    action: params.get('action') ?? undefined,
    operatorId: params.get('operatorId') ?? undefined,
  };
}

function writeAuditFilter(filter: AuditFilter): URLSearchParams {
  const params = new URLSearchParams();
  for (const subject of filter.subjects) params.append('subject', subject);
  if (filter.action?.trim()) params.set('action', filter.action.trim());
  if (filter.operatorId?.trim()) params.set('operatorId', filter.operatorId.trim());
  return params;
}

function SubjectCell({ entry }: { entry: AuditEntry }) {
  const label = `${entry.subjectType}:${entry.subjectId}`;
  if (entry.subjectType === 'case') return <Link to={`/cases/${entry.subjectId}`}><code>{label}</code></Link>;
  return <code>{label}</code>;
}

function HashCell({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(value).then(() => setCopied(true), () => setCopied(false));
  };
  return (
    <span className="audit-hash">
      <code title={value} aria-label={`Payload SHA-256 ${value}`}>{value.slice(0, 12)}…</code>
      <Button size="sm" variant="ghost" onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>
    </span>
  );
}

function FilterForm({ filter, onApply }: { filter: AuditFilter; onApply: (filter: AuditFilter) => void }) {
  const [action, setAction] = useState(filter.action ?? '');
  const [operatorId, setOperatorId] = useState(filter.operatorId ?? '');
  const [subject, setSubject] = useState('');
  const [subjectError, setSubjectError] = useState<string | null>(null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const subjects = [...filter.subjects];
    const added = subject.trim();
    if (added) {
      if (!SUBJECT_PATTERN.test(added)) { setSubjectError('A subject is type:id, for example track:… or case:….'); return; }
      if (subjects.length >= AUDIT_MAXIMUM_SUBJECTS) { setSubjectError(`At most ${AUDIT_MAXIMUM_SUBJECTS} subjects.`); return; }
      if (!subjects.includes(added)) subjects.push(added);
    }
    setSubjectError(null);
    setSubject('');
    onApply({ subjects, action, operatorId });
  };
  return (
    <form className="stack" aria-label="Audit filters" onSubmit={submit} noValidate>
      {filter.subjects.length > 0 ? (
        <ul className="row audit-subjects" aria-label="Subjects">
          {filter.subjects.map((item) => (
            <li key={item} className="row">
              <code>{item}</code>
              <Button size="sm" variant="ghost" iconOnly icon="x"
                onClick={() => onApply({ ...filter, subjects: filter.subjects.filter((other) => other !== item) })}>
                {`Remove subject ${item}`}
              </Button>
            </li>
          ))}
        </ul>
      ) : <p className="small muted">All subjects.</p>}
      <div className="audit-filters">
        <Field label="Add subject" optional error={subjectError} help="type:id, for example track:… or case:…">
          {(control) => <input {...control} type="text" value={subject} onChange={(event) => setSubject(event.target.value)} />}
        </Field>
        <Field label="Action" optional help="For example tracks.review-decided or cases.item-added">
          {(control) => <input {...control} type="text" value={action} onChange={(event) => setAction(event.target.value)} />}
        </Field>
        <Field label="Operator id" optional>
          {(control) => <input {...control} type="text" value={operatorId} onChange={(event) => setOperatorId(event.target.value)} />}
        </Field>
      </div>
      <div className="row">
        <Button type="submit" size="sm">Apply filters</Button>
        <Button size="sm" variant="ghost" onClick={() => { setAction(''); setOperatorId(''); setSubject(''); onApply({ subjects: [] }); }}>
          Clear filters
        </Button>
      </div>
    </form>
  );
}

/**
 * The audit trail (PoC S11-full; ADR-027 §3): read-only, operator-only, newest
 * first. Who acted and how they were identified, what, on which subject, when by
 * the server's clock, and the hash of what was submitted — never the payload.
 */
export default function AuditPage() {
  const [params, setParams] = useSearchParams();
  const filter = readAuditFilter(params);
  const filterKey = auditQueryString(filter, null, PAGE_SIZE);
  const systemConfig = useQuery({ queryKey: queryKeys.systemConfig, queryFn: ({ signal }) => getSystemConfig(signal), staleTime: 60_000 });
  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId;
  const audit = useInfiniteQuery({
    queryKey: queryKeys.audit(filterKey),
    queryFn: ({ pageParam, signal }) => readAudit(filter, pageParam, PAGE_SIZE, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    retry: retryOnce,
  });
  const statement = audit.data?.pages[0]?.statement;

  return (
    <section className="page">
      <ContextBar surface="audit" />
      <div className="stack">
        <p className="small muted">
          {statement || 'Append-only audit of operator actions. The submitted payload is not stored, only its SHA-256.'}
        </p>
        {isOperatorRequired(audit.error) ? (
          <OperatorRequiredNotice />
        ) : (
          <>
            <Panel title="Filters">
              <FilterForm key={filterKey} filter={filter} onApply={(next) => setParams(writeAuditFilter(next))} />
            </Panel>
            <Panel title="Entries" body="flush">
              <StateRegion
                kind="column"
                state={fromInfiniteQuery(audit, (pages) => pages.flatMap((page) => page.items))}
                label="audit entries"
                loadingLabel="Loading the audit trail…"
                isEmpty={(items) => items.length === 0}
                empty={{ title: 'No audit entries', body: 'No operator action matches these filters.' }}
                unavailableMessage={(error) => operatorMessage(error, 'The audit trail could not be loaded.')}
                retryable={retryable}
                degradedMessage="Showing the last known entries; refreshing failed."
                onRetry={() => void audit.refetch()}
              >
                {(items) => (
                  <div className="audit-table-wrap">
                    <table className="audit-table">
                      <caption className="visually-hidden">Audit entries, newest first</caption>
                      <thead>
                        <tr>
                          <th scope="col">Server time</th>
                          <th scope="col">Operator</th>
                          <th scope="col">Identity source</th>
                          <th scope="col">Action</th>
                          <th scope="col">Subject</th>
                          <th scope="col">Payload SHA-256</th>
                          <th scope="col">Correlation id</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((entry) => (
                          <tr key={entry.entryId}>
                            <td>{displayTimestamp(entry.recordedAtUtc, displayTimeZoneId)}</td>
                            <td>
                              {entry.operatorDisplayName}
                              <div className="small muted"><code>{entry.operatorId}</code></div>
                            </td>
                            <td>
                              {isUnattributed(entry.identitySource) ? (
                                <StatusBadge tone="warn" title={entry.identitySource}>Not attributable to a person</StatusBadge>
                              ) : null}
                              <div className="small"><code>{entry.identitySource}</code></div>
                            </td>
                            <td><code>{entry.action}</code></td>
                            <td><SubjectCell entry={entry} /></td>
                            <td><HashCell value={entry.payloadSha256} /></td>
                            <td><code className="small">{entry.correlationId}</code></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </StateRegion>
              {audit.isFetchNextPageError ? (
                <Alert tone="error">{describeError(audit.error, 'More entries could not be loaded.')}</Alert>
              ) : null}
              {audit.hasNextPage ? (
                <div className="row audit-more">
                  <Button size="sm" onClick={() => void audit.fetchNextPage()} disabled={audit.isFetchingNextPage}>
                    {audit.isFetchingNextPage ? 'Loading…' : 'Load more'}
                  </Button>
                </div>
              ) : null}
            </Panel>
          </>
        )}
      </div>
    </section>
  );
}
