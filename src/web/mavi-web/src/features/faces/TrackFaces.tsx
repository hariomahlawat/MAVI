import { useQuery } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { ApiError } from '../../api/client';
import {
  FACE_CANDIDATES_LABEL,
  formatFaceScore,
  getTrackFaces,
  thresholdContext,
  unknownFaceSentence,
  type TrackFacesResponse,
} from '../../api/faces';
import type { TrackDetail } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import { describeError, fromQuery } from '../../shared/async/fromQuery';
import StateRegion from '../../shared/async/StateRegion';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Panel from '../../shared/components/Panel';
import FaceActions from './FaceActions';
import FaceCrop from './FaceCrop';

function retryable(error: unknown): boolean {
  return !(error instanceof ApiError && error.status >= 400 && error.status < 500);
}

function StateText({ data, onCheckAgain }: { data: TrackFacesResponse; onCheckAgain: () => void }) {
  switch (data.state) {
    case 'unknown':
      return <Alert tone="info">{unknownFaceSentence(data.reason)}</Alert>;
    case 'pending':
      return (
        <Alert tone="info" actions={<Button size="sm" onClick={onCheckAgain}>Check again</Button>}>
          Face analysis pending: this Track&apos;s face analysis has not completed yet.
        </Alert>
      );
    case 'failed':
      return <Alert tone="warning">Face analysis failed for this Track{data.reason ? ` (${data.reason})` : ''}.</Alert>;
    case 'notAnalysed':
      return <Alert tone="info">Face analysis has not run for this Track&apos;s processing run yet.</Alert>;
    case 'notEnabled':
      return <Alert tone="info">Face analysis is off for this camera. It is opt-in per camera, on the Faces page.</Alert>;
    case 'notPerson':
      return <p className="small muted">Face analysis applies to Person Tracks only.</p>;
    case 'notConfigured':
      return <Alert tone="info">Face analysis is not configured in this installation.</Alert>;
    default:
      return null;
  }
}

/**
 * Faces on Track detail (PoC S6; ADR-022). The Track's face state, every face
 * the detector reported framed from its evidence crop, and — for each usable
 * face — Find this face, Compare with gallery and Enrol. A Track without a
 * usable face is Unknown: not analysable, never "no match".
 *
 * Loaded on request, as similarity candidates are: opening a Track shows no
 * biometric data until the operator asks (ADR-022 §1), and Review gains no
 * loading-to-content transition of its own (Stage 3.5 §38).
 */
export default function TrackFaces({ detail, displayTimeZoneId }: { detail: TrackDetail; displayTimeZoneId?: string }) {
  const headingId = useId();
  const trackId = detail.id.toLowerCase();
  const [selected, setSelected] = useState<string | null>(null);
  const [requested, setRequested] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.trackFaces(trackId),
    queryFn: ({ signal }) => getTrackFaces(trackId, signal),
    retry: (count, error) => retryable(error) && count < 1,
    enabled: requested,
  });

  if (!requested) {
    return (
      <Panel title="Faces" headingId={headingId}>
        <div className="stack">
          <p className="small"><strong>{FACE_CANDIDATES_LABEL}</strong></p>
          <p className="small muted">Faces load only when you ask: a face is a candidate, never an identification.</p>
          <div className="row">
            <Button size="sm" onClick={() => setRequested(true)}>Show faces</Button>
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="Faces" headingId={headingId}>
      <StateRegion
        kind="panel"
        state={fromQuery(query)}
        label="faces"
        loadingLabel="Loading faces…"
        unavailableMessage={(error) => error instanceof ApiError && (error.status === 401 || error.status === 403)
          ? 'Faces are available to operators only (ADR-010).'
          : describeError(error, 'Faces could not be loaded.')}
        retryable={retryable}
        onRetry={() => void query.refetch()}
      >
        {(data) => {
          const usable = data.faces.filter((face) => face.usable);
          const active = usable.find((face) => face.faceId === selected) ?? usable[0] ?? null;
          return (
            <div className="stack">
              <p className="small"><strong>{data.label || FACE_CANDIDATES_LABEL}</strong></p>
              {data.referenceThreshold ? <p className="small muted">{thresholdContext(data.referenceThreshold)}</p> : null}
              <StateText data={data} onCheckAgain={() => void query.refetch()} />
              {data.faces.length > 0 ? (
                <ul className="row" aria-label="Detected faces">
                  {data.faces.map((face) => (
                    <li key={face.faceId} className="stack">
                      <FaceCrop src={face.evidenceCropUrl} box={face.box} label={`Face, detector score ${formatFaceScore(face.score)}`} />
                      <span className="small">
                        {face.usable ? 'Usable' : 'Too small'} · {formatFaceScore(face.score)}
                      </span>
                      {face.usable && usable.length > 1 ? (
                        <Button size="sm" variant="ghost" aria-pressed={active?.faceId === face.faceId} onClick={() => setSelected(face.faceId)}>
                          Use this face
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {active ? <FaceActions key={active.faceId} source={{ faceId: active.faceId }} displayTimeZoneId={displayTimeZoneId} /> : null}
            </div>
          );
        }}
      </StateRegion>
    </Panel>
  );
}
