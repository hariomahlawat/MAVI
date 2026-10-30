import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError } from '../../api/client';
import {
  ENTITY_CANDIDATES_LABEL,
  ENTITY_LABEL,
  compareCandidateFaces,
  confirmEntityCandidate,
  decisionRefusalText,
  describeGap,
  dismissEntityCandidate,
  getEntity,
  getEntityCandidateSummary,
  listEntityCandidates,
  type EntityCandidate,
  type EntityCandidateStatus,
  type EntityTrack,
  type FaceFactorResponse,
} from '../../api/entities';
import { formatFaceScore, thresholdContext, unknownFaceSentence } from '../../api/faces';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import Panel from '../../shared/components/Panel';
import StatusBadge from '../../shared/components/StatusBadge';
import EvidencePlaceholder from '../../shared/evidence/EvidencePlaceholder';
import Dialog from '../../shared/overlay/Dialog';
import { formatDateTime } from '../../shared/time/time';
import { ContextBar } from '../../shared/workspace';
import FaceCrop from '../faces/FaceCrop';

const PAGE_SIZE = 25;
const NOTE_LIMIT = 500;

function operatorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    return 'Entity candidates are available to operators only (ADR-010).';
  }
  return describeError(error, fallback);
}

function utc(value: string): string {
  return `${formatDateTime(value, 'UTC')} UTC`;
}

/** The source frame: Review of the Track's video, seeked to the Track's start. */
function sourcePath(track: EntityTrack): string {
  const params = new URLSearchParams({ trackId: track.trackId.toLowerCase(), seekMs: String(Math.max(0, Math.trunc(track.startOffsetMs))) });
  return `/review/video/${track.videoAssetId.toLowerCase()}?${params.toString()}`;
}

function TrackEvidence({ track, side }: { track: EntityTrack; side: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <figure className="stack entity-track" aria-label={`${side} Track`}>
      <span className="thumb-frame" style={{ width: 160, height: 160, display: 'inline-block' }}>
        {track.thumbnailUrl && !failed ? (
          <img className="thumb" src={track.thumbnailUrl} alt={`Evidence crop of the ${side.toLowerCase()} Track`} width={160} height={160}
            onError={() => setFailed(true)} />
        ) : (
          <EvidencePlaceholder dense />
        )}
      </span>
      <figcaption className="small">
        <strong>{track.cameraCode}</strong> · {track.cameraName}
        <br />
        {utc(track.startTimestampUtc)} → {utc(track.endTimestampUtc)}
        <br />
        <Link to={sourcePath(track)}>Open source frames</Link>
        {track.entityId ? <><br />In Entity <Link to={`/entities?entity=${track.entityId}`}>{track.entityId.slice(-12)}</Link></> : null}
        {!track.visible ? <><br /><StatusBadge tone="stale">Earlier run</StatusBadge></> : null}
      </figcaption>
    </figure>
  );
}

function FaceFactor({ candidate }: { candidate: EntityCandidate }) {
  const compare = useMutation({ mutationFn: () => compareCandidateFaces(candidate.candidateId) });
  const face = candidate.factors.face;
  if (!face) return <p className="small muted">Face: not applicable to vehicles.</p>;
  const result: FaceFactorResponse | undefined = compare.data;
  return (
    <div className="stack" aria-label="Face factor">
      <p className="small">
        <strong>Face (separate factor)</strong> — {face.available ? 'both Tracks have a usable face.' : face.note}
      </p>
      {face.available && !result ? (
        <Button size="sm" disabled={compare.isPending} onClick={() => compare.mutate()}>Compare faces (audited)</Button>
      ) : null}
      {compare.isError ? <Alert tone="error">{operatorMessage(compare.error, 'The faces could not be compared.')}</Alert> : null}
      {result ? (
        result.pair ? (
          <div className="row">
            <FaceCrop src={result.pair.lowerEvidenceCropUrl} box={result.pair.lowerBox} label="Face of the first Track" />
            <FaceCrop src={result.pair.higherEvidenceCropUrl} box={result.pair.higherBox} label="Face of the second Track" />
            <p className="small">
              Face score {formatFaceScore(result.pair.score)} — {result.pair.aboveThreshold ? 'above' : 'below'} the{' '}
              {thresholdContext(result.referenceThreshold)}. {result.note}
            </p>
          </div>
        ) : (
          <p className="small">
            {[result.lower, result.higher].filter((side) => side.state !== 'observed')
              .map((side) => unknownFaceSentence(side.reason ?? side.state)).join('; ')}
          </p>
        )
      ) : null}
    </div>
  );
}

function CandidateDetail({ candidate, onDecided }: { candidate: EntityCandidate; onDecided: (message: string) => void }) {
  const [note, setNote] = useState('');
  const [pending, setPending] = useState<'confirm' | 'dismiss' | null>(null);
  const decide = useMutation({
    mutationFn: (decision: 'confirm' | 'dismiss') =>
      decision === 'confirm' ? confirmEntityCandidate(candidate.candidateId, note.trim() || null) : dismissEntityCandidate(candidate.candidateId, note.trim() || null),
    onSuccess: (response, decision) => {
      onDecided(decision === 'confirm'
        ? `Confirmed by ${response.candidate.decision?.displayName ?? 'the operator'}: ${response.entityCreated ? 'a new Entity was created' : 'the Track joined the Entity'}.`
        : 'Dismissed. The candidate will not be proposed again.');
    },
    onSettled: () => setPending(null),
  });
  const { appearance, plausibility } = candidate.factors;
  return (
    <Panel title="Candidate">
      <div className="row entity-pair">
        <TrackEvidence track={candidate.lower} side="First" />
        <TrackEvidence track={candidate.higher} side="Second" />
      </div>
      <dl className="stack small" aria-label="Factors">
        <div>
          <dt><strong>Appearance</strong></dt>
          <dd>Score {appearance.score.toFixed(3)} (floor {appearance.floor.toFixed(2)}) — {appearance.source}.</dd>
        </div>
        <div>
          <dt><strong>Time and camera</strong></dt>
          <dd>
            Plausible: {plausibility.sameCamera ? 'same camera, not at the same time' : 'different cameras'}, {describeGap(plausibility.gapMs)}
            {' '}(tolerance {(plausibility.concurrencyToleranceMs / 1000).toFixed(0)} s). {plausibility.disclosure}
          </dd>
        </div>
      </dl>
      <FaceFactor key={candidate.candidateId} candidate={candidate} />
      {candidate.status === 'open' ? (
        <div className="stack">
          <Field label="Note (optional)" help={`At most ${NOTE_LIMIT} characters; kept with the decision.`}
            error={note.trim().length > NOTE_LIMIT ? `At most ${NOTE_LIMIT} characters.` : null} optional>
            {(control) => <textarea {...control} rows={2} value={note} onChange={(event) => setNote(event.target.value)} />}
          </Field>
          <div className="row">
            <Button variant="primary" disabled={decide.isPending || note.trim().length > NOTE_LIMIT} onClick={() => setPending('confirm')}>
              Confirm same {candidate.objectClass === 'Person' ? 'person' : 'vehicle'}
            </Button>
            <Button variant="ghost" disabled={decide.isPending || note.trim().length > NOTE_LIMIT} onClick={() => setPending('dismiss')}>
              Dismiss
            </Button>
          </div>
          {decide.isError ? (
            <Alert tone="error">
              {decide.error instanceof ApiError && decide.error.status === 409
                ? decisionRefusalText(decide.error.code)
                : operatorMessage(decide.error, 'The decision failed.')}
            </Alert>
          ) : null}
        </div>
      ) : candidate.decision ? (
        <p className="small" role="status">
          {candidate.status === 'confirmed' ? 'Confirmed' : 'Dismissed'} by {candidate.decision.displayName} ({candidate.decision.identitySource}) at{' '}
          {utc(candidate.decision.decidedAtUtc)}{candidate.decision.note ? ` — “${candidate.decision.note}”` : ''}.
        </p>
      ) : null}
      <Dialog
        open={pending !== null}
        title={pending === 'confirm' ? 'Record that these two Tracks show the same object?' : 'Dismiss this candidate?'}
        confirmLabel={pending === 'confirm' ? 'Confirm' : 'Dismiss'}
        onConfirm={() => { if (pending) decide.mutate(pending); }}
        onCancel={() => setPending(null)}
      >
        {pending === 'confirm'
          ? 'Your decision links the two Tracks in an Entity, attributed to you and audited. It records an operator judgement, not an identification, and cannot be undone in this version.'
          : 'Your decision is attributed to you and audited; this pair will not be proposed again.'}
      </Dialog>
    </Panel>
  );
}

function EntityPanel({ entityId }: { entityId: string }) {
  const entity = useQuery({ queryKey: queryKeys.entity(entityId), queryFn: ({ signal }) => getEntity(entityId, signal) });
  return (
    <Panel title="Entity">
      <StateRegion
        kind="panel"
        state={fromQuery(entity)}
        label="Entity"
        loadingLabel="Loading the Entity…"
        unavailableMessage={(error) => operatorMessage(error, 'The Entity could not be loaded.')}
        onRetry={() => void entity.refetch()}
      >
        {(data) => (
          <div className="stack">
            <Alert tone="info">{data.label}</Alert>
            <p className="small">
              {data.displayCode} · {data.entityType} · identity {data.identityStatus} · {data.members.length} Tracks, {data.confirmations.length} confirmations
            </p>
            <div className="row">
              {data.members.map((track) => <TrackEvidence key={track.trackId} track={track} side="Member" />)}
            </div>
            <ul className="stack small" aria-label="Confirmations">
              {data.confirmations.map((item) => (
                <li key={item.candidateId}>
                  {item.lower.cameraCode} ↔ {item.higher.cameraCode}: confirmed by {item.decision?.displayName} at{' '}
                  {item.decision ? utc(item.decision.decidedAtUtc) : '—'}
                </li>
              ))}
            </ul>
          </div>
        )}
      </StateRegion>
    </Panel>
  );
}

/**
 * Entities (PoC S7; ADR-023): Entity candidates with their evidence and factors
 * side by side, and the operator's confirm or dismiss. Nothing on this page
 * states who a person is; an Entity is an operator's recorded judgement.
 */
export default function EntitiesPage() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const status = (params.get('status') as EntityCandidateStatus | null) ?? 'open';
  const objectClass = params.get('objectClass') === 'Person' || params.get('objectClass') === 'Vehicle'
    ? (params.get('objectClass') as 'Person' | 'Vehicle') : undefined;
  const pair = params.get('pair');
  const [cameraId, otherCameraId] = pair ? pair.split(':') : [undefined, undefined];
  const offset = Math.max(0, Number(params.get('offset') ?? '0') || 0);
  const entityId = params.get('entity');
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const filter = { status, objectClass, cameraId, otherCameraId, limit: PAGE_SIZE, offset };
  const summary = useQuery({ queryKey: queryKeys.entityCandidateSummary, queryFn: ({ signal }) => getEntityCandidateSummary(signal) });
  const list = useQuery({ queryKey: queryKeys.entityCandidates(filter), queryFn: ({ signal }) => listEntityCandidates(filter, signal) });
  const active = list.data?.candidates.find((item) => item.candidateId === selected) ?? null;

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    if (!('offset' in changes)) next.delete('offset');
    setParams(next);
    setSelected(null);
  };

  return (
    <section className="page">
      <ContextBar surface="entities" />
      <div className="stack">
        <Alert tone="info">{list.data?.label ?? ENTITY_CANDIDATES_LABEL}</Alert>
        <p className="small muted">
          A candidate is a pair of Tracks MAVI proposes might show the same person or vehicle: appearance similarity at or above the floor, and
          plausible in time and camera. Each factor is shown separately; the face factor is computed only when you ask. Nothing is linked until an
          operator confirms. {summary.data?.catalogue.plausibilityDisclosure}
        </p>
        {message ? <p className="small" role="status">{message}</p> : null}
        {entityId ? <EntityPanel entityId={entityId} /> : null}
        <Panel title="Camera pairs">
          <StateRegion
            kind="panel"
            state={fromQuery(summary)}
            label="camera pairs"
            loadingLabel="Loading camera pairs…"
            isEmpty={(data) => data.pairs.length === 0}
            empty={{ title: 'No candidates yet', body: 'Candidates appear once Tracks have appearance vectors.' }}
            unavailableMessage={(error) => operatorMessage(error, 'The candidate summary could not be loaded.')}
            onRetry={() => void summary.refetch()}
          >
            {(data) => (
              <div className="stack">
                <p className="small muted">
                  Catalogue {data.catalogue.version} · {data.derivations} analyses derived{data.pendingDerivations > 0 ? `, ${data.pendingDerivations} pending` : ''}
                </p>
                <table className="table small" aria-label="Candidates per camera pair">
                  <thead><tr><th>Cameras</th><th>Class</th><th>Open</th><th>Confirmed</th><th>Dismissed</th><th /></tr></thead>
                  <tbody>
                    {data.pairs.map((row) => (
                      <tr key={`${row.cameraId}:${row.otherCameraId}:${row.objectClass}`}>
                        <td>{row.cameraCode === row.otherCameraCode ? `${row.cameraCode} (same camera)` : `${row.cameraCode} ↔ ${row.otherCameraCode}`}</td>
                        <td>{row.objectClass}</td>
                        <td>{row.open}</td>
                        <td>{row.confirmed}</td>
                        <td>{row.dismissed}</td>
                        <td>
                          <Button size="sm" variant="ghost" onClick={() => update({ pair: `${row.cameraId}:${row.otherCameraId}`, objectClass: row.objectClass })}>
                            Show
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </StateRegion>
        </Panel>
        <Panel title="Candidates">
          <div className="row" role="group" aria-label="Candidate status">
            {(['open', 'confirmed', 'dismissed'] as const).map((value) => (
              <Button key={value} size="sm" variant={value === status ? 'primary' : 'ghost'} aria-pressed={value === status}
                onClick={() => update({ status: value })}>
                {value === 'open' ? 'Open' : value === 'confirmed' ? 'Confirmed' : 'Dismissed'}
              </Button>
            ))}
            {pair || objectClass ? <Button size="sm" variant="ghost" onClick={() => update({ pair: null, objectClass: null })}>All cameras</Button> : null}
          </div>
          <StateRegion
            kind="panel"
            state={fromQuery(list)}
            label="candidates"
            loadingLabel="Loading candidates…"
            isEmpty={(data) => data.candidates.length === 0}
            empty={{ title: status === 'open' ? 'No open candidates' : `No ${status} candidates` }}
            unavailableMessage={(error) => operatorMessage(error, 'Candidates could not be loaded.')}
            onRetry={() => void list.refetch()}
          >
            {(data) => (
              <div className="stack">
                <ul className="stack" aria-label="Entity candidates">
                  {data.candidates.map((item) => (
                    <li key={item.candidateId} className="row">
                      <Button size="sm" variant={item.candidateId === selected ? 'primary' : 'ghost'} aria-pressed={item.candidateId === selected}
                        onClick={() => setSelected(item.candidateId)}>
                        {item.objectClass} · {item.lower.cameraCode} ↔ {item.higher.cameraCode}
                      </Button>
                      <span className="small">
                        appearance {item.factors.appearance.score.toFixed(3)} · {describeGap(item.factors.plausibility.gapMs)}
                        {item.factors.face ? ` · face ${item.factors.face.available ? 'available' : 'Unknown'}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="row small">
                  <span>{data.offset + 1}–{data.offset + data.candidates.length} of {data.total}</span>
                  <Button size="sm" variant="ghost" disabled={data.offset === 0}
                    onClick={() => update({ offset: String(Math.max(0, data.offset - PAGE_SIZE)) })}>Previous</Button>
                  <Button size="sm" variant="ghost" disabled={data.offset + data.candidates.length >= data.total}
                    onClick={() => update({ offset: String(data.offset + PAGE_SIZE) })}>Next</Button>
                </div>
              </div>
            )}
          </StateRegion>
        </Panel>
        {active ? (
          <CandidateDetail
            key={active.candidateId}
            candidate={active}
            onDecided={(text) => {
              setMessage(text);
              setSelected(null);
              void queryClient.invalidateQueries({ queryKey: ['entity-candidates'] });
              void queryClient.invalidateQueries({ queryKey: queryKeys.entityCandidateSummary });
              void queryClient.invalidateQueries({ queryKey: ['entity'] });
            }}
          />
        ) : null}
        <p className="small muted">{ENTITY_LABEL}: an Entity groups Tracks an operator confirmed; it never names anyone.</p>
      </div>
    </section>
  );
}
