import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  NO_GALLERY_CANDIDATE,
  compareWithGallery,
  enrolInGallery,
  formatFaceScore,
  searchFace,
  thresholdContext,
  type FaceSearchCandidate,
  type FaceSource,
  type GalleryCompareResponse,
  type FaceSearchResponse,
} from '../../api/faces';
import { getTrack } from '../../api/tracks';
import { queryKeys } from '../../app/queryClient';
import { describeError } from '../../shared/async/fromQuery';
import Alert from '../../shared/components/Alert';
import Button from '../../shared/components/Button';
import Field from '../../shared/components/Field';
import StatusBadge from '../../shared/components/StatusBadge';
import { displayTimestamp } from '../../shared/format/format';
import { reviewPath } from '../visual-search/TrackResultList';
import FaceCrop from './FaceCrop';

/** The marker beside every score: the score's place against the reference threshold, never a verdict. */
export function ThresholdMarker({ above }: { above: boolean }) {
  return (
    <StatusBadge tone={above ? 'info' : 'neutral'}>{above ? 'Above threshold' : 'Below threshold'}</StatusBadge>
  );
}

function SearchCandidateRow({ candidate, displayTimeZoneId }: { candidate: FaceSearchCandidate; displayTimeZoneId?: string }) {
  const navigate = useNavigate();
  const open = useMutation({
    mutationFn: () => getTrack(candidate.trackId),
    onSuccess: (detail) => navigate(reviewPath({ id: detail.id, videoAssetId: detail.videoAssetId })),
  });
  const score = formatFaceScore(candidate.score);
  return (
    <li className="row row--nowrap" data-rank={candidate.rank}>
      <FaceCrop src={candidate.evidenceCropUrl} box={candidate.box} size={56} label={`Candidate face, rank ${candidate.rank}`} />
      <span className="stack">
        <span className="small">
          Rank <b className="num">{candidate.rank}</b> · Score <b className="num">{score}</b>{' '}
          <ThresholdMarker above={candidate.aboveThreshold} />
        </span>
        <span className="small">{candidate.cameraName}</span>
        <time className="small muted" dateTime={candidate.startTimestampUtc}>
          {displayTimestamp(candidate.startTimestampUtc, displayTimeZoneId)}
        </time>
        <span>
          <Button size="sm" variant="ghost" disabled={open.isPending} onClick={() => open.mutate()}
            aria-label={`Open candidate Track, rank ${candidate.rank}, score ${score}`}>
            Open Track
          </Button>
        </span>
        {open.isError ? <Alert tone="error">{describeError(open.error, 'The Track could not be opened.')}</Alert> : null}
      </span>
    </li>
  );
}

function SearchAnswer({ data, displayTimeZoneId }: { data: FaceSearchResponse; displayTimeZoneId?: string }) {
  const candidates = [...data.candidates].sort((left, right) => left.rank - right.rank);
  return (
    <div className="stack">
      <p className="small muted">
        {candidates.length} candidate Track{candidates.length === 1 ? '' : 's'} · ranked by face score · {thresholdContext(data.referenceThreshold)}
      </p>
      {candidates.length === 0 ? (
        <p className="small" role="status">No candidate Tracks with a usable face.</p>
      ) : (
        <ol className="stack" aria-label="Candidate appearances">
          {candidates.map((candidate) => (
            <SearchCandidateRow key={`${candidate.trackId}:${candidate.faceId}`} candidate={candidate} displayTimeZoneId={displayTimeZoneId} />
          ))}
        </ol>
      )}
    </div>
  );
}

function CompareAnswer({ data }: { data: GalleryCompareResponse }) {
  return (
    <div className="stack">
      <p className="small muted">{thresholdContext(data.referenceThreshold)}</p>
      {data.candidates.length === 0 ? (
        <p className="small" role="status">{data.message ?? NO_GALLERY_CANDIDATE}</p>
      ) : (
        <ol className="stack" aria-label="Candidate gallery matches">
          {data.candidates.map((candidate) => (
            <li key={candidate.enrolledPersonId} className="small">
              Candidate gallery match: <strong>{candidate.label}</strong> · Score{' '}
              <b className="num">{formatFaceScore(candidate.score)}</b> <ThresholdMarker above={candidate.aboveThreshold} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function EnrolForm({ source, onDone }: { source: FaceSource; onDone: (enrolled: boolean) => void }) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState('');
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const enrol = useMutation({
    mutationFn: () => enrolInGallery(label.trim(), note.trim() ? note.trim() : null, source),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.faceGallery });
      onDone(true);
    },
  });
  const labelError = submitted && !label.trim() ? 'Enter a gallery label.' : null;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!label.trim() || label.trim().length > 100 || note.length > 500) return;
    enrol.mutate();
  };
  return (
    <form className="stack" onSubmit={submit} aria-label="Enrol in gallery">
      <Field label="Gallery label" error={labelError} help="Up to 100 characters. Stored only in this installation.">
        {(control) => <input {...control} value={label} maxLength={100} onChange={(event) => setLabel(event.target.value)} />}
      </Field>
      <Field label="Note" optional>
        {(control) => <textarea {...control} value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} />}
      </Field>
      <div className="row">
        <Button size="sm" variant="primary" type="submit" disabled={enrol.isPending}>Enrol</Button>
        <Button size="sm" variant="ghost" type="button" onClick={() => onDone(false)}>Cancel</Button>
      </div>
      {enrol.isError ? <Alert tone="error">{describeError(enrol.error, 'The face could not be enrolled.')}</Alert> : null}
    </form>
  );
}

/**
 * The three things an operator can do with one usable face (ADR-022 §1, §6–§7):
 * find its candidate appearances, compare it with the gallery, or enrol it.
 * Each is an audited operator act, so each runs only when asked. Every answer
 * is a candidate list with scores beside the reference threshold.
 */
export default function FaceActions({ source, displayTimeZoneId }: { source: FaceSource; displayTimeZoneId?: string }) {
  const [enrolling, setEnrolling] = useState(false);
  const [enrolled, setEnrolled] = useState(false);
  const search = useMutation({ mutationFn: () => searchFace(source) });
  const compare = useMutation({ mutationFn: () => compareWithGallery(source) });
  return (
    <div className="stack">
      <div className="row">
        <Button size="sm" variant="primary" icon="search" disabled={search.isPending} onClick={() => search.mutate()}>
          Find this face
        </Button>
        <Button size="sm" disabled={compare.isPending} onClick={() => compare.mutate()}>Compare with gallery</Button>
        <Button size="sm" variant="ghost" onClick={() => { setEnrolling(true); setEnrolled(false); }}>Enrol in gallery…</Button>
      </div>
      {search.isPending ? <p className="small muted" role="status">Finding candidate appearances…</p> : null}
      {search.isError ? <Alert tone="error">{describeError(search.error, 'Candidate appearances could not be found.')}</Alert> : null}
      {search.data ? <SearchAnswer data={search.data} displayTimeZoneId={displayTimeZoneId} /> : null}
      {compare.isPending ? <p className="small muted" role="status">Comparing with the gallery…</p> : null}
      {compare.isError ? <Alert tone="error">{describeError(compare.error, 'The gallery comparison failed.')}</Alert> : null}
      {compare.data ? <CompareAnswer data={compare.data} /> : null}
      {enrolling ? <EnrolForm source={source} onDone={(done) => { setEnrolling(false); setEnrolled(done); }} /> : null}
      {enrolled && !enrolling ? <p className="small" role="status">Enrolled in the gallery.</p> : null}
    </div>
  );
}
