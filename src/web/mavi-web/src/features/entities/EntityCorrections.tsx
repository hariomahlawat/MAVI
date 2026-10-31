import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { entityAuditPath } from '../../api/audit';
import { ApiError, problemText } from '../../api/client';
import {
  ENTITY_NOTE_MAXIMUM,
  correctionRefusalText,
  getEntity,
  getEntityCandidateHistory,
  mergeEntity,
  reopenEntityCandidate,
  unlinkEntityTrack,
  type EntityCandidate,
  type EntityMembershipChange,
  type EntityResponse,
  type EntityTrack,
} from '../../api/entities';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import Dialog from '../../shared/overlay/Dialog';
import { formatDateTime } from '../../shared/time/time';
import AddToCase from '../cases/AddToCase';
import { ActorIdentity, isOperatorRequired } from '../review/operator';

const RECORDED_NOT_EDITED = 'Corrections are recorded as new entries, attributed and audited; nothing earlier is edited or deleted.';

function utc(value: string): string {
  return `${formatDateTime(value, 'UTC')} UTC`;
}

function refusal(error: unknown, fallback: string): string {
  if (isOperatorRequired(error)) return 'Entity corrections are available to operators only (ADR-010).';
  if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.code !== 'api_error') return correctionRefusalText(error.code);
  return describeError(error, fallback);
}

/** After any correction every view of Entities, candidates, cases and the audit trail is read again. */
export function invalidateCorrections(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: ['entity'] });
  void queryClient.invalidateQueries({ queryKey: ['entity-candidates'] });
  void queryClient.invalidateQueries({ queryKey: ['entity-candidate-history'] });
  void queryClient.invalidateQueries({ queryKey: queryKeys.cases });
  void queryClient.invalidateQueries({ queryKey: ['audit'] });
}

function NoteField({ label, value, onChange, disabled }: { label: string; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  const tooLong = value.trim().length > ENTITY_NOTE_MAXIMUM;
  return (
    <Field label={label} optional error={tooLong ? `At most ${ENTITY_NOTE_MAXIMUM} characters.` : null}
      help={`${value.length} / ${ENTITY_NOTE_MAXIMUM}; kept with the correction.`}>
      {(control) => <textarea {...control} rows={2} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />}
    </Field>
  );
}

function trackWords(track: EntityTrack | undefined, trackId: string): string {
  return track ? `${track.objectClass} Track on ${track.cameraCode}, ${utc(track.startTimestampUtc)}` : `Track …${trackId.slice(-12)}`;
}

// --- Merge ----------------------------------------------------------------------------------

/**
 * Merge two Entities (ADR-027 §4). The operator chooses which one is kept: every
 * member of the other joins it, and the other is kept as Merged with its history.
 * The server refuses a merge any cross pair of members makes physically impossible.
 */
export function MergeEntities({ entityIds, onMerged }: { entityIds: [string, string]; onMerged: (kept: EntityResponse) => void }) {
  const queryClient = useQueryClient();
  const [a, b] = entityIds.map((id) => id.toLowerCase());
  const first = useQuery({ queryKey: queryKeys.entity(a), queryFn: ({ signal }) => getEntity(a, signal) });
  const second = useQuery({ queryKey: queryKeys.entity(b), queryFn: ({ signal }) => getEntity(b, signal) });
  const [keep, setKeep] = useState<string>(a);
  const [note, setNote] = useState('');
  const [confirming, setConfirming] = useState(false);
  const code = (id: string) => (id === a ? first.data?.displayCode : second.data?.displayCode) ?? `Entity …${id.slice(-12)}`;
  const source = keep === a ? b : a;
  const merge = useMutation({
    mutationFn: () => mergeEntity(source, keep, note.trim() || null),
    onSuccess: (kept) => {
      invalidateCorrections(queryClient);
      onMerged(kept);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) invalidateCorrections(queryClient);
    },
    onSettled: () => setConfirming(false),
  });
  const members = [...(first.data?.members ?? []), ...(second.data?.members ?? [])];
  const implausible = merge.error instanceof ApiError && merge.error.code === 'entity_merge_implausible';
  const conflicting = [problemText(merge.error, 'conflictingTrackId'), problemText(merge.error, 'otherConflictingTrackId')]
    .filter((id): id is string => Boolean(id));

  return (
    <section className="stack entity-merge" aria-label="Merge Entities">
      <h3>Merge Entities</h3>
      <p className="small">
        {code(a)} and {code(b)} are separate Entities. Merging moves every member of one into the other; the one not kept is marked
        merged and keeps its history. {RECORDED_NOT_EDITED}
      </p>
      <fieldset className="stack">
        <legend className="small">Which Entity is kept?</legend>
        {[a, b].map((id) => (
          <label key={id} className="row small">
            <input type="radio" name={`keep-${a}-${b}`} value={id} checked={keep === id} onChange={() => setKeep(id)} disabled={merge.isPending} />
            Keep {code(id)} (merge {code(id === a ? b : a)} into it)
          </label>
        ))}
      </fieldset>
      <NoteField label="Merge note" value={note} onChange={setNote} disabled={merge.isPending} />
      {merge.isError ? (
        <Alert tone={isOperatorRequired(merge.error) ? 'info' : 'error'}>
          {refusal(merge.error, 'The Entities could not be merged.')}
          {implausible && conflicting.length === 2 ? (
            <> The two Tracks: {trackWords(members.find((t) => t.trackId.toLowerCase() === conflicting[0].toLowerCase()), conflicting[0])} and{' '}
              {trackWords(members.find((t) => t.trackId.toLowerCase() === conflicting[1].toLowerCase()), conflicting[1])}.</>
          ) : null}
        </Alert>
      ) : null}
      <div className="row">
        <Button disabled={merge.isPending || note.trim().length > ENTITY_NOTE_MAXIMUM} onClick={() => setConfirming(true)}>
          {merge.isPending ? 'Merging…' : `Merge ${code(source)} into ${code(keep)}`}
        </Button>
      </div>
      <Dialog
        open={confirming}
        title={`Merge ${code(source)} into ${code(keep)}?`}
        confirmLabel="Merge"
        onConfirm={() => merge.mutate()}
        onCancel={() => setConfirming(false)}
      >
        {`Every member of ${code(source)} joins ${code(keep)}; ${code(source)} is kept as merged, with its history. The merge is attributed to you and audited. It is an operator's grouping, not an identification, and is not undone as a unit: Tracks are unlinked one by one.`}
      </Dialog>
    </section>
  );
}

/** Merge from the Entity view: the other Entity is named by its identifier. */
function MergeFromEntity({ entity, onMerged }: { entity: EntityResponse; onMerged: (kept: EntityResponse) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [other, setOther] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!open) return <div className="row"><Button size="sm" variant="ghost" onClick={() => setOpen(true)}>Merge with another Entity…</Button></div>;
  if (other) return <MergeEntities key={other} entityIds={[entity.entityId, other]} onMerged={onMerged} />;
  return (
    <form className="stack" aria-label="Choose the other Entity" noValidate onSubmit={(event) => {
      event.preventDefault();
      const value = draft.trim().toLowerCase();
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value)) { setError('Enter the other Entity\'s identifier.'); return; }
      if (value === entity.entityId.toLowerCase()) { setError('Choose a different Entity.'); return; }
      setError(null);
      setOther(value);
    }}>
      <Field label="Other Entity identifier" error={error}>
        {(control) => <input {...control} type="text" value={draft} onChange={(event) => setDraft(event.target.value)} />}
      </Field>
      <div className="row">
        <Button type="submit" size="sm">Continue</Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </form>
  );
}

// --- Unlink ---------------------------------------------------------------------------------

function UnlinkMember({ entity, track }: { entity: EntityResponse; track: EntityTrack }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const [confirming, setConfirming] = useState(false);
  const unlink = useMutation({
    mutationFn: () => unlinkEntityTrack(entity.entityId, track.trackId, note.trim() || null),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.entity(entity.entityId.toLowerCase()), updated);
      invalidateCorrections(queryClient);
      setOpen(false);
      setNote('');
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) invalidateCorrections(queryClient);
    },
    onSettled: () => setConfirming(false),
  });
  const remaining = entity.members.length - 1;
  if (!open) {
    return <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>Unlink</Button>;
  }
  return (
    <div className="stack" role="group" aria-label={`Unlink ${track.cameraCode} Track`}>
      <NoteField label="Unlink note" value={note} onChange={setNote} disabled={unlink.isPending} />
      {unlink.isError ? (
        <Alert tone={isOperatorRequired(unlink.error) ? 'info' : 'error'}>{refusal(unlink.error, 'The Track could not be unlinked.')}</Alert>
      ) : null}
      <div className="row">
        <Button size="sm" variant="danger" disabled={unlink.isPending || note.trim().length > ENTITY_NOTE_MAXIMUM} onClick={() => setConfirming(true)}>
          {unlink.isPending ? 'Unlinking…' : 'Unlink this Track'}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={unlink.isPending}>Cancel</Button>
      </div>
      <Dialog
        open={confirming}
        title={`Unlink this Track from ${entity.displayCode}?`}
        confirmLabel="Unlink"
        destructive
        onConfirm={() => unlink.mutate()}
        onCancel={() => setConfirming(false)}
      >
        {`The Track leaves ${entity.displayCode}. The Entity is kept with its ${remaining} remaining member${remaining === 1 ? '' : 's'}${remaining < 2 ? ' — an Entity is kept even with one or no member' : ''}. The candidates that confirmed the Track stay in its history. The change is attributed to you and audited.`}
      </Dialog>
    </div>
  );
}

// --- History --------------------------------------------------------------------------------

const CAUSE_TEXT: Record<EntityMembershipChange['cause'], string> = {
  CandidateConfirmed: 'candidate confirmed',
  Unlinked: 'unlinked',
  Merged: 'merge',
};

function MembershipHistory({ entity, tracks }: { entity: EntityResponse; tracks: EntityTrack[] }) {
  if (entity.history.length === 0) return <p className="small muted">No membership changes are recorded.</p>;
  const byId = new Map(tracks.map((track) => [track.trackId.toLowerCase(), track]));
  return (
    <ol className="stack small entity-history" aria-label="Membership history">
      {entity.history.map((change) => (
        <li key={change.sequence}>
          <strong>{change.change === 'Joined' ? 'Joined' : 'Left'}</strong>{' '}
          {trackWords(byId.get(change.trackId.toLowerCase()), change.trackId)} — {CAUSE_TEXT[change.cause] ?? change.cause}
          {change.entityId.toLowerCase() !== entity.entityId.toLowerCase() ? ` (in Entity …${change.entityId.slice(-12)})` : ''}
          <div>
            <ActorIdentity displayName={change.operatorDisplayName} operatorId={change.operatorId} identitySource={change.identitySource} />
            {' · '}{utc(change.atUtc)}
          </div>
          {change.note ? <p className="small">{change.note}</p> : null}
        </li>
      ))}
    </ol>
  );
}

// --- The Entity view ------------------------------------------------------------------------

function MergedInto({ entityId }: { entityId: string }) {
  const target = useQuery({ queryKey: queryKeys.entity(entityId.toLowerCase()), queryFn: ({ signal }) => getEntity(entityId, signal) });
  const label = target.data?.displayCode ?? `Entity …${entityId.slice(-12)}`;
  return (
    <p className="small">
      <StatusBadge tone="neutral">Merged</StatusBadge>{' '}Merged into{' '}
      <Link to={`/entities?entity=${entityId.toLowerCase()}`}>{label}</Link>.
      {' '}This Entity keeps its history and no longer changes.
    </p>
  );
}

/**
 * One Entity (PoC S7, corrections PoC S11-full; ADR-023, ADR-027 §4): its state,
 * its members with Unlink, merge with another Entity, the membership history,
 * the audit trail and cases. An Entity is an operator's grouping, never an
 * identification.
 */
export function EntityView({ entityId, renderMember, onShowEntity }: {
  entityId: string;
  /** How a member's evidence is drawn (S7's Track evidence). */
  renderMember: (track: EntityTrack) => ReactNode;
  onShowEntity: (id: string) => void;
}) {
  const id = entityId.toLowerCase();
  const entity = useQuery({ queryKey: queryKeys.entity(id), queryFn: ({ signal }) => getEntity(id, signal) });
  return (
    <Panel title="Entity">
      <StateRegion
        kind="panel"
        state={fromQuery(entity)}
        label="Entity"
        loadingLabel="Loading the Entity…"
        unavailableMessage={(error) => refusal(error, 'The Entity could not be loaded.')}
        retryable={(error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500)}
        onRetry={() => void entity.refetch()}
      >
        {(data) => {
          const active = data.state === 'Active';
          const tracks = [...data.members, ...data.confirmations.flatMap((item) => [item.lower, item.higher])];
          return (
            <div className="stack">
              <Alert tone="info">{data.label}</Alert>
              <div className="row">
                <strong>{data.displayCode}</strong>
                <StatusBadge tone={active ? 'ok' : 'neutral'}>{active ? 'Active' : 'Merged'}</StatusBadge>
                <span className="small">
                  {data.entityType} · identity {data.identityStatus} · {data.members.length} member{data.members.length === 1 ? '' : 's'},
                  {' '}{data.confirmations.length} confirmation{data.confirmations.length === 1 ? '' : 's'}
                </span>
              </div>
              {!active && data.mergedIntoEntityId ? <MergedInto entityId={data.mergedIntoEntityId} /> : null}
              {data.members.length === 0 ? (
                <p className="small" role="status">
                  No members now. The Entity is kept as the record of the decisions that formed it and of the corrections since.
                </p>
              ) : data.members.length === 1 ? (
                <p className="small muted">One member now. The Entity is kept; nothing is dissolved automatically.</p>
              ) : null}
              <ul className="row entity-members" aria-label="Members">
                {data.members.map((track) => (
                  <li key={track.trackId} className="stack">
                    {renderMember(track)}
                    {active ? <UnlinkMember entity={data} track={track} /> : null}
                  </li>
                ))}
              </ul>
              {active ? <MergeFromEntity entity={data} onMerged={(kept) => onShowEntity(kept.entityId)} /> : null}
              <ul className="stack small" aria-label="Confirmations">
                {data.confirmations.map((item) => (
                  <li key={item.candidateId}>
                    {item.lower.cameraCode} ↔ {item.higher.cameraCode}: confirmed by {item.decision?.displayName} at{' '}
                    {item.decision ? utc(item.decision.decidedAtUtc) : '—'}
                    {item.entityId && item.entityId.toLowerCase() !== data.entityId.toLowerCase() ? ' (from a merged Entity)' : ''}
                  </li>
                ))}
              </ul>
              <details className="disclosure">
                <summary>Membership history</summary>
                <div className="disclosure__body stack">
                  <p className="small muted">{RECORDED_NOT_EDITED}</p>
                  <MembershipHistory entity={data} tracks={tracks} />
                </div>
              </details>
              <div className="row">
                <Link className="btn btn--sm btn--ghost" to={entityAuditPath(data.entityId)}>Audit trail</Link>
              </div>
              <AddToCase key={data.entityId} kind="Entity" subjectId={data.entityId} />
            </div>
          );
        }}
      </StateRegion>
    </Panel>
  );
}

// --- Candidate corrections ------------------------------------------------------------------

/** Reopen a dismissed candidate, or a confirmed one whose Tracks are no longer together (the server decides). */
export function ReopenCandidate({ candidate, onReopened }: { candidate: EntityCandidate; onReopened: (message: string) => void }) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState('');
  const [confirming, setConfirming] = useState(false);
  const reopen = useMutation({
    mutationFn: () => reopenEntityCandidate(candidate.candidateId, note.trim() || null),
    onSuccess: () => {
      invalidateCorrections(queryClient);
      onReopened('Reopened: the candidate is open again and can be confirmed or dismissed afresh. The earlier decision stays in its history.');
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) invalidateCorrections(queryClient);
    },
    onSettled: () => setConfirming(false),
  });
  const linkedEntity = reopen.error instanceof ApiError && reopen.error.code === 'entity_candidate_still_linked'
    ? problemText(reopen.error, 'entityId') : undefined;
  return (
    <div className="stack" role="group" aria-label="Reopen candidate">
      <NoteField label="Reopen note" value={note} onChange={setNote} disabled={reopen.isPending} />
      {reopen.isError ? (
        <Alert tone={isOperatorRequired(reopen.error) ? 'info' : 'error'}>
          {refusal(reopen.error, 'The candidate could not be reopened.')}
          {linkedEntity ? <> <Link to={`/entities?entity=${linkedEntity.toLowerCase()}`}>Open the Entity</Link> to unlink a Track.</> : null}
        </Alert>
      ) : null}
      <div className="row">
        <Button size="sm" disabled={reopen.isPending || note.trim().length > ENTITY_NOTE_MAXIMUM} onClick={() => setConfirming(true)}>
          {reopen.isPending ? 'Reopening…' : 'Reopen'}
        </Button>
      </div>
      <Dialog
        open={confirming}
        title="Reopen this candidate?"
        confirmLabel="Reopen"
        onConfirm={() => reopen.mutate()}
        onCancel={() => setConfirming(false)}
      >
        The candidate returns to the open list to be decided afresh. The earlier decision is kept in its history; the reopening is
        attributed to you and audited.
      </Dialog>
    </div>
  );
}

const DECISION_TEXT = { Confirmed: 'Confirmed', Dismissed: 'Dismissed', Reopened: 'Reopened' } as const;

export function CandidateHistory({ candidateId }: { candidateId: string }) {
  const [open, setOpen] = useState(false);
  const history = useQuery({
    queryKey: ['entity-candidate-history', candidateId.toLowerCase()],
    queryFn: ({ signal }) => getEntityCandidateHistory(candidateId, signal),
    enabled: open,
  });
  return (
    <details className="disclosure" onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary>Decision history</summary>
      <div className="disclosure__body">
        {!open ? null : history.isError ? (
          <Alert tone={isOperatorRequired(history.error) ? 'info' : 'error'}>{refusal(history.error, 'The decision history could not be loaded.')}</Alert>
        ) : !history.data ? (
          <p className="small muted" role="status">Loading the decision history…</p>
        ) : history.data.decisions.length === 0 ? (
          <p className="small muted">No decisions have been recorded.</p>
        ) : (
          <ol className="stack small" aria-label="Candidate decision history">
            {history.data.decisions.map((item) => (
              <li key={item.sequence}>
                <strong>{DECISION_TEXT[item.decision] ?? item.decision}</strong>
                {item.entityId ? ` (Entity …${item.entityId.slice(-12)})` : ''} ·{' '}
                <ActorIdentity displayName={item.operatorDisplayName} operatorId={item.operatorId} identitySource={item.identitySource} />
                {' · '}{utc(item.atUtc)}
                {item.note ? <p className="small">{item.note}</p> : null}
              </li>
            ))}
          </ol>
        )}
      </div>
    </details>
  );
}
