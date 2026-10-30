import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  FACE_CANDIDATES_LABEL,
  compareWithGallery,
  enrolInGallery,
  getTrackFaces,
  searchFace,
  type TrackFacesResponse,
} from '../../api/faces';
import type { TrackDetail } from '../../api/tracks';
import { renderWithApp } from '../../test/renderWithApp';
import TrackFaces from './TrackFaces';

vi.mock('../../api/faces', async () => {
  const actual = await vi.importActual<typeof import('../../api/faces')>('../../api/faces');
  return { ...actual, getTrackFaces: vi.fn(), searchFace: vi.fn(), compareWithGallery: vi.fn(), enrolInGallery: vi.fn() };
});

const detail = { id: '018F3F5A-2F70-7A2B-8A12-2D02F4C21450', objectClass: 'Person' } as unknown as TrackDetail;
const threshold = { cosine: 0.2121, provenance: 's6-embedder-spike-v1: LFW 6,000 pairs, faces downscaled to 32 px', calibratedOnCctv: false };
const identity = { fingerprint: 'f'.repeat(64), modelId: 'faces-yunet-adaface-ir50-webface4m', modelVersion: '60a65bef-dev.1' };

function faces(overrides: Partial<TrackFacesResponse> = {}): TrackFacesResponse {
  return {
    label: FACE_CANDIDATES_LABEL,
    state: 'observed',
    reason: null,
    identity,
    referenceThreshold: threshold,
    faces: [
      { faceId: 'face-1', observationId: 'obs-1', evidenceCropUrl: '/api/artifacts/a1/content', box: { x: 10, y: 8, width: 48, height: 52 }, landmarks: [], score: 0.95, usable: true },
      { faceId: 'face-2', observationId: 'obs-2', evidenceCropUrl: '/api/artifacts/a2/content', box: { x: 2, y: 2, width: 20, height: 22 }, landmarks: [], score: 0.91, usable: false },
    ],
    ...overrides,
  };
}

/** Renders the panel and asks for the Track's faces, as the operator does. */
async function showFaces() {
  renderWithApp(<TrackFaces detail={detail} />);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Show faces' }));
}

/** The words a face surface must never use: a candidate is not an identification. */
const FORBIDDEN = /identified|match found|\bis the same\b|confirmed/i;

describe('PoC S6 TrackFaces', () => {
  beforeEach(() => {
    vi.mocked(getTrackFaces).mockReset();
    vi.mocked(searchFace).mockReset();
    vi.mocked(compareWithGallery).mockReset();
    vi.mocked(enrolInGallery).mockReset();
  });

  it('loads nothing biometric until the operator asks, and says faces are candidates', () => {
    renderWithApp(<TrackFaces detail={detail} />);
    expect(screen.getByText(FACE_CANDIDATES_LABEL)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show faces' })).toBeInTheDocument();
    expect(screen.queryByText('Loading faces…')).not.toBeInTheDocument();
    expect(getTrackFaces).not.toHaveBeenCalled();
  });

  it('carries the candidate label and threshold context, frames each face and asks nothing until the operator does', async () => {
    vi.mocked(getTrackFaces).mockResolvedValue(faces());
    await showFaces();

    expect(await screen.findByText(FACE_CANDIDATES_LABEL)).toBeInTheDocument();
    expect(screen.getByText('reference threshold 0.2121 (LFW, not calibrated on CCTV)')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Detected faces' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(list).toHaveTextContent('Usable · 0.950');
    expect(list).toHaveTextContent('Too small · 0.910');
    expect(getTrackFaces).toHaveBeenCalledWith('018f3f5a-2f70-7a2b-8a12-2d02f4c21450', expect.any(AbortSignal));
    expect(searchFace).not.toHaveBeenCalled();
    expect(compareWithGallery).not.toHaveBeenCalled();
  });

  it.each([
    ['face_too_small', 'Unknown — no usable face (every detected face is smaller than 32 px)'],
    ['no_face_detected', 'Unknown — no usable face (no face detected in the evidence crops)'],
    ['no_evidence', 'Unknown — no usable face (the Track has no accepted evidence crops)'],
  ])('states Unknown (%s) as not analysable, never as no match', async (reason, sentence) => {
    vi.mocked(getTrackFaces).mockResolvedValue(faces({ state: 'unknown', reason, faces: [] }));
    await showFaces();
    expect(await screen.findByText(sentence)).toBeInTheDocument();
    expect(screen.queryByText(/no match/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Find this face' })).not.toBeInTheDocument();
  });

  it('says a camera that has not opted in is off, not empty', async () => {
    vi.mocked(getTrackFaces).mockResolvedValue(faces({ state: 'notEnabled', faces: [], identity: null }));
    await showFaces();
    expect(await screen.findByText(/Face analysis is off for this camera/)).toBeInTheDocument();
  });

  it('lists candidate appearances with score, threshold marker and camera, in rank order', async () => {
    const user = userEvent.setup();
    vi.mocked(getTrackFaces).mockResolvedValue(faces());
    vi.mocked(searchFace).mockResolvedValue({
      label: FACE_CANDIDATES_LABEL, identity, referenceThreshold: threshold, snapshot: 's', snapshotUtc: '2026-10-29T10:00:00Z',
      candidates: [
        { rank: 2, trackId: 't2', processingRunId: 'r', cameraId: 'c', cameraName: 'Stairwell', startTimestampUtc: '2026-10-29T09:00:00Z', score: 0.1, aboveThreshold: false, faceId: 'f9', observationId: 'o9', evidenceCropUrl: null, box: { x: 0, y: 0, width: 40, height: 40 } },
        { rank: 1, trackId: 't1', processingRunId: 'r', cameraId: 'c', cameraName: 'Lobby', startTimestampUtc: '2026-10-29T08:00:00Z', score: 0.72, aboveThreshold: true, faceId: 'f8', observationId: 'o8', evidenceCropUrl: null, box: { x: 0, y: 0, width: 40, height: 40 } },
      ],
    });
    await showFaces();

    await user.click(await screen.findByRole('button', { name: 'Find this face' }));
    const list = await screen.findByRole('list', { name: 'Candidate appearances' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('Rank 1 · Score 0.720 Above threshold');
    expect(rows[0]).toHaveTextContent('Lobby');
    expect(rows[1]).toHaveTextContent('Rank 2 · Score 0.100 Below threshold');
    expect(searchFace).toHaveBeenCalledWith({ faceId: 'face-1' });
    expect(list).not.toHaveTextContent('%');
    expect(document.body.textContent).not.toMatch(FORBIDDEN);
  });

  it('shows candidate gallery matches with label and score, or says none is above the threshold', async () => {
    const user = userEvent.setup();
    vi.mocked(getTrackFaces).mockResolvedValue(faces());
    vi.mocked(compareWithGallery)
      .mockResolvedValueOnce({ label: FACE_CANDIDATES_LABEL, identity, referenceThreshold: threshold, candidates: [{ enrolledPersonId: 'e1', label: 'Visitor A', score: 0.5, aboveThreshold: true }], message: null })
      .mockResolvedValueOnce({ label: FACE_CANDIDATES_LABEL, identity, referenceThreshold: threshold, candidates: [], message: 'No gallery candidate above the threshold' });
    await showFaces();

    await user.click(await screen.findByRole('button', { name: 'Compare with gallery' }));
    const list = await screen.findByRole('list', { name: 'Candidate gallery matches' });
    expect(list).toHaveTextContent('Candidate gallery match: Visitor A · Score 0.500 Above threshold');
    expect(document.body.textContent).not.toMatch(FORBIDDEN);

    await user.click(screen.getByRole('button', { name: 'Compare with gallery' }));
    expect(await screen.findByText('No gallery candidate above the threshold')).toBeInTheDocument();
  });

  it('enrols the face with a label and refuses an empty label', async () => {
    const user = userEvent.setup();
    vi.mocked(getTrackFaces).mockResolvedValue(faces());
    vi.mocked(enrolInGallery).mockResolvedValue({ enrolledPersonId: 'e1' });
    await showFaces();

    await user.click(await screen.findByRole('button', { name: 'Enrol in gallery…' }));
    await user.click(screen.getByRole('button', { name: 'Enrol' }));
    expect(await screen.findByText('Enter a gallery label.')).toBeInTheDocument();
    expect(enrolInGallery).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText('Gallery label'), 'Visitor A');
    await user.click(screen.getByRole('button', { name: 'Enrol' }));
    await waitFor(() => expect(enrolInGallery).toHaveBeenCalledWith('Visitor A', null, { faceId: 'face-1' }));
    expect(await screen.findByText('Enrolled in the gallery.')).toBeInTheDocument();
  });
});
