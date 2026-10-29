import { useQuery } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../../api/client';
import {
  SIMILARITY_CANDIDATES_LABEL,
  SIMILAR_TRACKS_K_DEFAULT,
  getSimilarTracks,
  objectClassLabel,
  serializeSimilarTracksParams,
  type SimilarTrackCandidate,
  type SimilarTracksParams,
  type SimilarTracksResponse,
  type TrackDetail,
} from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import Panel from '../../shared/components/Panel';
import { useStatusReport } from '../../shared/components/StatusSlot';
import EvidencePlaceholder from '../../shared/evidence/EvidencePlaceholder';
import { displayTimestamp, formatSimilarityScore } from '../../shared/format/format';
import { reviewPath } from '../visual-search/TrackResultList';

/** The candidate counts offered; the API accepts 1–50. */
export const SIMILAR_K_OPTIONS = [5, 10, 20, 50] as const;

export const SIMILARITY_NOTE = 'Visual similarity only. Not identity: candidates are never grouped or confirmed automatically.';

/** One human sentence per unavailable reason (ADR-021 §4); an unknown reason degrades to a generic one. */
export function similarityUnavailableSentence(reason: string | null): string {
  switch (reason) {
    case 'evidence_too_small':
      return "Similarity unavailable: this Track's evidence crops are smaller than 80 px.";
    case 'no_evidence':
      return 'Similarity unavailable: this Track has no accepted evidence crops.';
    case 'evidence_unavailable':
      return "Similarity unavailable: this Track's evidence crops could not be read.";
    default:
      return reason ? `Similarity unavailable for this Track (${reason}).` : 'Similarity unavailable for this Track.';
  }
}

type SimilarRequest = { params: SimilarTracksParams; serial: number };

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

function isRetryable(error: unknown): boolean {
  return !(error instanceof ApiError && error.status >= 400 && error.status < 500);
}

/** A polite readout for a ready answer, said through the enclosing slot (§23). */
function ReadyStatus({ text }: { text: string }) {
  const routed = useStatusReport(text, true);
  return <p className="small muted" role={routed ? undefined : 'status'}>{text}</p>;
}

function CandidateRow({
  candidate,
  displayTimeZoneId,
  returnFrom,
}: {
  candidate: SimilarTrackCandidate;
  displayTimeZoneId?: string;
  returnFrom?: string | null;
}) {
  const { track } = candidate;
  // A thumbnail that fails to load reads as one that was never persisted (§37.1).
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  useEffect(() => { setThumbnailFailed(false); }, [track.thumbnailContentUrl]);
  const classLabel = objectClassLabel(track);
  const score = formatSimilarityScore(candidate.score);
  // Track detail of the candidate. The way back to the search this review was
  // opened from travels with it, so following candidates never strands the operator.
  const path = reviewPath(track) + (returnFrom ? '&from=' + encodeURIComponent(returnFrom) : '');

  return (
    <li className="row row--nowrap" data-rank={candidate.rank}>
      <span className="thumb-frame thumb-frame--md" aria-hidden="true">
        {track.thumbnailContentUrl && !thumbnailFailed ? (
          <img className="thumb" src={track.thumbnailContentUrl} alt="" loading="lazy" onError={() => setThumbnailFailed(true)} />
        ) : (
          <EvidencePlaceholder />
        )}
      </span>
      <span className="stack">
        <Link
          to={path}
          aria-label={`Open ${classLabel} Track on ${track.cameraCode}, rank ${candidate.rank}, similarity score ${score}`}
        >
          {classLabel} · {track.cameraCode} · {track.cameraName}
        </Link>
        <span className="small">
          Rank <b className="num">{candidate.rank}</b> · Score <b className="num">{score}</b>
        </span>
        <time className="small muted" dateTime={track.startTimestampUtc}>
          {displayTimestamp(track.startTimestampUtc, displayTimeZoneId)}
        </time>
      </span>
    </li>
  );
}

function Answer({
  data,
  displayTimeZoneId,
  returnFrom,
  onCheckAgain,
}: {
  data: SimilarTracksResponse;
  displayTimeZoneId?: string;
  returnFrom?: string | null;
  onCheckAgain: () => void;
}) {
  switch (data.state) {
    case 'pending':
      return (
        <Alert tone="info" actions={<Button size="sm" onClick={onCheckAgain}>Check again</Button>}>
          Similarity pending: this Track&apos;s appearance analysis has not completed yet.
        </Alert>
      );
    case 'notConfigured':
      return <Alert tone="info">Similarity search is not configured in this installation.</Alert>;
    case 'notAnalysed':
      return (
        <Alert tone="info">
          Similarity not analysed: this Track&apos;s run has no appearance analysis (it was processed before similarity
          was enabled). An administrator can request a re-analysis of the run.
        </Alert>
      );
    case 'failed':
      return (
        <Alert tone="warning">
          Similarity failed: this Track&apos;s appearance analysis did not complete
          {data.reason ? ` (${data.reason})` : ''}. An administrator can request a re-analysis of the run.
        </Alert>
      );
    case 'unavailable':
      return <Alert tone="info">{similarityUnavailableSentence(data.reason)}</Alert>;
    case 'ready': {
      // Shown in rank order, whatever order the wire carried them in.
      const candidates = [...data.candidates].sort((left, right) => left.rank - right.rank);
      if (candidates.length === 0) return <ReadyStatus text="No similarity candidates in this scope." />;
      return (
        <>
          <ReadyStatus text={`${candidates.length} candidate${candidates.length === 1 ? '' : 's'} · ranked by similarity score`} />
          <ol className="stack" aria-label="Similar Track candidates">
            {candidates.map((candidate) => (
              <CandidateRow
                key={candidate.track.id}
                candidate={candidate}
                displayTimeZoneId={displayTimeZoneId}
                returnFrom={returnFrom}
              />
            ))}
          </ol>
        </>
      );
    }
    default:
      return <Alert tone="info">Similarity is unavailable for this Track.</Alert>;
  }
}

/**
 * Similar Tracks on Track detail (ADR-021 §4–§5).
 *
 * Every result is a *similarity candidate*: a ranked cosine score from a
 * Development model, never identity, never grouped or confirmed, and with no
 * threshold that turns a score into a verdict. The panel says so in its heading
 * and its note, and states the model the scores came from.
 *
 * The query runs when the operator asks ("Find similar"), not on every detail
 * load: it is an exact scan over the corpus whose answer is candidate evidence
 * the operator chooses to look at, and Track detail must not pay for it — or
 * be slowed by it — when they do not.
 *
 * The snapshot token of the last answer is held here and used only for an
 * explicit "Refresh (same snapshot)", which replays the identical ranked list.
 * A new "Find similar" is a new query and drops it.
 */
export default function TrackSimilarCandidates({
  detail,
  displayTimeZoneId,
  returnFrom,
}: {
  detail: TrackDetail;
  displayTimeZoneId?: string;
  /** The Review route's `from` (the originating search), carried on candidate links. */
  returnFrom?: string | null;
}) {
  const headingId = useId();
  const trackId = detail.id.toLowerCase();
  const [sameCamera, setSameCamera] = useState(false);
  const [k, setK] = useState<number>(SIMILAR_TRACKS_K_DEFAULT);
  const [request, setRequest] = useState<SimilarRequest | null>(null);
  const serial = useRef(0);

  const query = useQuery({
    queryKey: queryKeys.similarTracks(
      trackId,
      request ? serializeSimilarTracksParams(request.params) : '',
      request?.serial ?? 0,
    ),
    queryFn: ({ signal }) => getSimilarTracks(trackId, request!.params, signal),
    enabled: request !== null,
    retry: shouldRetry,
    staleTime: Infinity,
  });

  const findSimilar = () => {
    serial.current += 1;
    setRequest({
      params: { k, ...(sameCamera ? { cameraId: detail.camera.id.toLowerCase() } : {}) },
      serial: serial.current,
    });
  };

  // The snapshot in hand: the one this request replays, or the one its answer
  // carried. Only a ready answer is worth replaying.
  const heldSnapshot = request?.params.snapshot ?? (query.data?.state === 'ready' ? query.data.snapshot : null) ?? null;
  const refreshSnapshot = () => {
    if (!request || !heldSnapshot) return;
    serial.current += 1;
    // The exact parameters the snapshot was taken under; the server refuses it otherwise.
    setRequest({ params: { ...request.params, snapshot: heldSnapshot }, serial: serial.current });
  };

  const data = query.data;
  const loading = request !== null && query.isFetching;

  return (
    <Panel title={SIMILARITY_CANDIDATES_LABEL} headingId={headingId}>
      <div className="stack">
        <p className="small muted">{SIMILARITY_NOTE}</p>
        <label className="checkbox">
          <input type="checkbox" checked={sameCamera} onChange={(event) => setSameCamera(event.target.checked)} />
          Same camera only
        </label>
        <Field label="Number of candidates">
          {(control) => (
            <select {...control} value={k} onChange={(event) => setK(Number(event.target.value))}>
              {SIMILAR_K_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          )}
        </Field>
        <div className="row">
          <Button size="sm" variant="primary" icon="search" onClick={findSimilar}>
            Find similar
          </Button>
          {heldSnapshot && !loading ? (
            <Button size="sm" icon="refresh" onClick={refreshSnapshot}>Refresh (same snapshot)</Button>
          ) : null}
        </div>

        {data?.identity ? (
          <p className="small muted">
            Model <span className="mono">{data.identity.modelId}</span> · version <span className="mono">{data.identity.modelVersion}</span>
            {data.snapshotUtc ? <> · snapshot {displayTimestamp(data.snapshotUtc, displayTimeZoneId)}</> : null}
          </p>
        ) : null}

        {/* One panel region (§14.1): it loads, fails with its retry, or holds
            the answer — whose pending, unavailable and ready readouts are said
            through the region's own slot (§23). Nothing is shown until asked. */}
        {request !== null ? (
          <StateRegion
            kind="panel"
            state={fromQuery(query)}
            label="similar Tracks"
            loadingLabel="Finding similar Tracks…"
            unavailableMessage={(error) => describeError(error, 'Similar Tracks could not be loaded.')}
            retryable={isRetryable}
            onRetry={() => void query.refetch()}
          >
            {(answer) => (
              <Answer
                data={answer}
                displayTimeZoneId={displayTimeZoneId}
                returnFrom={returnFrom}
                onCheckAgain={() => void query.refetch()}
              />
            )}
          </StateRegion>
        ) : null}
      </div>
    </Panel>
  );
}
