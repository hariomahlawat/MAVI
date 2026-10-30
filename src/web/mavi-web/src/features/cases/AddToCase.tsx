import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../../api/client';
import {
  CASE_ITEM_ALREADY_PRESENT,
  CASE_ITEM_NOTE_MAXIMUM,
  CASE_STATEMENT,
  CASE_TITLE_MAXIMUM,
  addCaseItem,
  caseItemKindLabel,
  createCase,
  listCases,
  type CaseItemKind,
} from '../../api/cases';
import { queryKeys } from '../../app/queryClient';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import { OperatorRequiredNotice, isOperatorRequired, operatorMessage, retryOnce } from '../review/operator';

const NEW_CASE = '__new__';

type Props = {
  /** What is added: a Track, an analytic event, or (from the Entities view) an Entity. */
  kind: CaseItemKind;
  subjectId: string;
};

type Added = { caseId: string; title: string };

/**
 * Add one subject to a case (PoC S11-full; ADR-027 §2). One component for every
 * surface that offers it — the Track inspector, Review, each event, and the
 * Entities view — so the words, the checks and the refusals are the same
 * everywhere. Cases are read only when the operator opens it, so an
 * installation without operator identity sends nothing until asked.
 */
export default function AddToCase({ kind, subjectId: rawSubjectId }: Props) {
  const subjectId = rawSubjectId.toLowerCase();
  const formId = useId();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState('');
  const [title, setTitle] = useState('');
  const [note, setNote] = useState('');
  const [added, setAdded] = useState<Added | null>(null);
  const [titleError, setTitleError] = useState<string | null>(null);
  const noun = caseItemKindLabel(kind);

  const cases = useQuery({
    queryKey: queryKeys.caseList('all'),
    queryFn: ({ signal }) => listCases(null, 200, signal),
    enabled: open,
    retry: retryOnce,
  });
  const holding = useQuery({
    queryKey: queryKeys.caseList(`${kind}:${subjectId}`),
    queryFn: ({ signal }) => listCases({ kind, subjectId }, 200, signal),
    enabled: open,
    retry: retryOnce,
  });
  const holdingIds = new Set((holding.data?.cases ?? []).map((item) => item.caseId));

  const add = useMutation({
    mutationFn: async (): Promise<Added> => {
      let target = selected;
      let targetTitle = cases.data?.cases.find((item) => item.caseId === selected)?.title ?? '';
      if (selected === NEW_CASE) {
        const created = await createCase(title.trim());
        // The case exists from here on, whatever happens to the item: it is
        // selected so a retry adds to it rather than creating a second one.
        setSelected(created.caseId);
        setTitle('');
        target = created.caseId;
        targetTitle = created.title;
      }
      await addCaseItem(target, { kind, subjectId, note: note.trim() ? note : null });
      return { caseId: target, title: targetTitle };
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: queryKeys.cases }),
    onSuccess: (result) => {
      setAdded(result);
      setOpen(false);
      setSelected('');
      setNote('');
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (selected === NEW_CASE) {
      const trimmed = title.trim();
      if (!trimmed) { setTitleError('Enter a title for the new case.'); return; }
      if (trimmed.length > CASE_TITLE_MAXIMUM) { setTitleError(`A title is at most ${CASE_TITLE_MAXIMUM} characters.`); return; }
    }
    setTitleError(null);
    add.mutate();
  };

  const failure = add.error;
  const failureText = failure instanceof ApiError && failure.code === CASE_ITEM_ALREADY_PRESENT
    ? `This ${noun} is already an item of that case.`
    : failure instanceof ApiError && failure.code === 'case_subject_not_found'
      ? `This ${noun} no longer exists, so it cannot be added.`
      : operatorMessage(failure, 'The item could not be added to the case.');
  const listFailure = cases.error ?? holding.error;
  const noteTooLong = note.length > CASE_ITEM_NOTE_MAXIMUM;

  if (!open) {
    return (
      <div className="stack add-to-case">
        <div className="row">
          <Button size="sm" icon="box" aria-expanded={false} onClick={() => { setOpen(true); setAdded(null); add.reset(); }}>
            Add to case
          </Button>
        </div>
        {added ? (
          <Alert tone="success">
            Added to <Link to={`/cases/${added.caseId}`}>{added.title || 'the case'}</Link>.
          </Alert>
        ) : null}
      </div>
    );
  }

  return (
    <form className="stack add-to-case add-to-case--open" aria-label="Add to case" id={formId} onSubmit={submit} noValidate>
      <p className="small muted">{CASE_STATEMENT}</p>
      {isOperatorRequired(listFailure) ? (
        <>
          <OperatorRequiredNotice />
          <div className="row"><Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Close</Button></div>
        </>
      ) : (
        <>
          {listFailure ? (
            <Alert tone="error" actions={<Button size="sm" onClick={() => { void cases.refetch(); void holding.refetch(); }}>Retry</Button>}>
              {operatorMessage(listFailure, 'Cases could not be loaded.')}
            </Alert>
          ) : null}
          <Field label="Case">
            {(control) => (
              <select {...control} value={selected} onChange={(event) => setSelected(event.target.value)} disabled={add.isPending}>
                <option value="">{cases.isPending ? 'Loading cases…' : 'Choose a case'}</option>
                {(cases.data?.cases ?? []).map((item) => (
                  <option key={item.caseId} value={item.caseId} disabled={holdingIds.has(item.caseId)}>
                    {item.title}{holdingIds.has(item.caseId) ? ` (already holds this ${noun})` : ''}
                  </option>
                ))}
                <option value={NEW_CASE}>New case…</option>
              </select>
            )}
          </Field>
          {selected === NEW_CASE ? (
            <Field label="New case title" error={titleError}>
              {(control) => (
                <input {...control} type="text" value={title} maxLength={CASE_TITLE_MAXIMUM} disabled={add.isPending}
                  onChange={(event) => setTitle(event.target.value)} />
              )}
            </Field>
          ) : null}
          <Field
            label="Note"
            optional
            error={noteTooLong ? `A note is at most ${CASE_ITEM_NOTE_MAXIMUM} characters.` : null}
            help={`Why this ${noun} is in the case. ${note.length} / ${CASE_ITEM_NOTE_MAXIMUM}.`}
          >
            {(control) => <textarea {...control} rows={2} value={note} disabled={add.isPending} onChange={(event) => setNote(event.target.value)} />}
          </Field>
          {add.isError ? (
            <Alert tone={isOperatorRequired(failure) ? 'info' : 'error'}>{failureText}</Alert>
          ) : null}
          <div className="row">
            <Button type="submit" size="sm" disabled={!selected || add.isPending || noteTooLong}>
              {add.isPending ? 'Adding…' : 'Add to case'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={add.isPending}>Cancel</Button>
          </div>
        </>
      )}
    </form>
  );
}
