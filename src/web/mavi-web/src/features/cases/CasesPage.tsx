import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CASE_LIST_PAGE_SIZE, CASE_PURPOSE_MAXIMUM, CASE_STATEMENT, CASE_TITLE_MAXIMUM, createCase, listCases } from '../../api/cases';
import { getSystemConfig } from '../../api/system';
import { queryKeys } from '../../app/queryClient';
import { fromInfiniteQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import Panel from '../../shared/components/Panel';
import { displayTimestamp } from '../../shared/format/format';
import { ContextBar } from '../../shared/workspace';
import { ActorIdentity, OperatorRequiredNotice, isOperatorRequired, operatorMessage, retryOnce, retryable } from '../review/operator';

function CreateCase({ onCreated }: { onCreated: (caseId: string) => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [purpose, setPurpose] = useState('');
  const [titleError, setTitleError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => createCase(title.trim(), purpose.trim() ? purpose : null),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cases });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
      setTitle('');
      setPurpose('');
      onCreated(created.caseId);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) { setTitleError('Enter a title.'); return; }
    if (trimmed.length > CASE_TITLE_MAXIMUM) { setTitleError(`A title is at most ${CASE_TITLE_MAXIMUM} characters.`); return; }
    setTitleError(null);
    create.mutate();
  };
  return (
    <Panel title="New case">
      <form className="stack" aria-label="New case" onSubmit={submit} noValidate>
        <Field label="Title" error={titleError}>
          {(control) => <input {...control} type="text" value={title} maxLength={CASE_TITLE_MAXIMUM} onChange={(event) => setTitle(event.target.value)} />}
        </Field>
        <Field label="Purpose" optional help={`${purpose.length} / ${CASE_PURPOSE_MAXIMUM}`}>
          {(control) => <textarea {...control} rows={2} value={purpose} maxLength={CASE_PURPOSE_MAXIMUM} onChange={(event) => setPurpose(event.target.value)} />}
        </Field>
        {create.isError ? (
          <Alert tone={isOperatorRequired(create.error) ? 'info' : 'error'}>{operatorMessage(create.error, 'The case could not be created.')}</Alert>
        ) : null}
        <div className="row">
          <Button type="submit" variant="primary" disabled={create.isPending}>{create.isPending ? 'Creating…' : 'Create case'}</Button>
        </div>
      </form>
    </Panel>
  );
}

/**
 * Cases (PoC S11-full; ADR-027 §2): the operator's investigation containers.
 * Operator-only; an installation without operator identity says so once.
 */
export default function CasesPage() {
  const navigate = useNavigate();
  const systemConfig = useQuery({ queryKey: queryKeys.systemConfig, queryFn: ({ signal }) => getSystemConfig(signal), staleTime: 60_000 });
  const displayTimeZoneId = systemConfig.data?.displayTimeZoneId;
  // Every case is reachable: pages follow the server's cursor, and a title search narrows them on the server.
  const [search, setSearch] = useState('');
  const [title, setTitle] = useState('');
  const cases = useInfiniteQuery({
    queryKey: queryKeys.caseList(`all|${title}`),
    queryFn: ({ pageParam, signal }) => listCases({ title }, pageParam, CASE_LIST_PAGE_SIZE, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    retry: retryOnce,
  });
  const operatorRequired = isOperatorRequired(cases.error);

  return (
    <section className="page">
      <ContextBar surface="cases" />
      <div className="stack">
        <p className="small muted">{cases.data?.pages[0]?.statement ?? CASE_STATEMENT}</p>
        {operatorRequired ? (
          <OperatorRequiredNotice />
        ) : (
          <>
            <CreateCase onCreated={(caseId) => navigate(`/cases/${caseId}`)} />
            <Panel title="Cases">
              <form className="row" role="search" aria-label="Find cases" onSubmit={(event) => { event.preventDefault(); setTitle(search.trim()); }}>
                <Field label="Title contains" optional>
                  {(control) => <input {...control} type="search" value={search} maxLength={CASE_TITLE_MAXIMUM} onChange={(event) => setSearch(event.target.value)} />}
                </Field>
                <Button type="submit" size="sm">Find</Button>
                {title ? <Button size="sm" variant="ghost" onClick={() => { setSearch(''); setTitle(''); }}>Show all</Button> : null}
              </form>
              <StateRegion
                kind="panel"
                state={fromInfiniteQuery(cases, (pages) => pages.flatMap((page) => page.cases))}
                label="cases"
                loadingLabel="Loading cases…"
                isEmpty={(items) => items.length === 0}
                empty={title
                  ? { title: 'No case matches', body: `No case title contains "${title}".` }
                  : { title: 'No cases yet', body: 'Create a case here, or add a Track or an event to a new case from where you found it.' }}
                unavailableMessage={(error) => operatorMessage(error, 'Cases could not be loaded.')}
                retryable={retryable}
                onRetry={() => void cases.refetch()}
              >
                {(items) => (
                  <>
                  <ul className="case-list" aria-label="Cases">
                    {items.map((item) => (
                      <li key={item.caseId} className="case-list__item">
                        <Link to={`/cases/${item.caseId}`} className="case-list__title">{item.title}</Link>
                        {item.purpose ? <p className="small">{item.purpose}</p> : null}
                        <p className="small muted">
                          {item.activeItemCount} item{item.activeItemCount === 1 ? '' : 's'}
                          {item.removedItemCount > 0 ? ` · ${item.removedItemCount} removed` : ''}
                          {` · ${item.noteCount} note${item.noteCount === 1 ? '' : 's'}`}
                          {' · created '}{displayTimestamp(item.createdBy.atUtc, displayTimeZoneId)}{' by '}
                          <ActorIdentity displayName={item.createdBy.displayName} operatorId={item.createdBy.operatorId} identitySource={item.createdBy.identitySource} />
                        </p>
                      </li>
                    ))}
                  </ul>
                  {cases.hasNextPage ? (
                    <div className="row">
                      <Button size="sm" variant="ghost" disabled={cases.isFetchingNextPage} onClick={() => void cases.fetchNextPage()}>
                        {cases.isFetchingNextPage ? 'Loading more cases…' : 'Load more cases'}
                      </Button>
                    </div>
                  ) : null}
                  </>
                )}
              </StateRegion>
            </Panel>
          </>
        )}
      </div>
    </section>
  );
}
