import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import {
  ENTITY_CANDIDATES_LABEL,
  compareCandidateFaces,
  confirmEntityCandidate,
  dismissEntityCandidate,
  getEntityCandidateSummary,
  listEntityCandidates,
  type EntityCandidate,
  type EntityCandidateList,
  type EntityCandidateSummary,
} from '../../api/entities';
import { renderWithApp } from '../../test/renderWithApp';
import EntitiesPage from './EntitiesPage';

vi.mock('../../api/entities', async () => {
  const actual = await vi.importActual<typeof import('../../api/entities')>('../../api/entities');
  return {
    ...actual,
    listEntityCandidates: vi.fn(), getEntityCandidateSummary: vi.fn(), confirmEntityCandidate: vi.fn(), dismissEntityCandidate: vi.fn(),
    compareCandidateFaces: vi.fn(), getEntity: vi.fn(),
  };
});

const catalogue = {
  version: 'mavi-entity-candidates-v1', sha256: 'a'.repeat(64), appearanceFloor: 0.85, concurrencyToleranceMs: 2000, parameters: [],
  plausibilityDisclosure: 'Time and camera only: MAVI knows no camera locations, distances, view overlap, travel times or clock errors.',
};

function track(id: string, camera: string): EntityCandidate['lower'] {
  return {
    trackId: id, processingRunId: 'r-' + id, videoAssetId: 'v-' + id, cameraId: 'c-' + camera, cameraCode: camera, cameraName: camera + ' view',
    objectClass: 'Person', startTimestampUtc: '2026-10-01T04:10:00Z', endTimestampUtc: '2026-10-01T04:10:04Z', startOffsetMs: 12_000,
    endOffsetMs: 16_000, thumbnailUrl: '/api/artifacts/' + id + '/content', entityId: null, visible: true,
  };
}

function candidate(overrides: Partial<EntityCandidate> = {}): EntityCandidate {
  return {
    candidateId: 'cand-1', label: ENTITY_CANDIDATES_LABEL, objectClass: 'Person', status: 'open', catalogueVersion: catalogue.version,
    identityFingerprint: 'b'.repeat(64),
    factors: {
      appearance: { score: 0.912, floor: 0.85, source: 'SigLIP 2 Track vectors (ADR-021); similarity, not identity' },
      plausibility: { verdict: 'plausible', sameCamera: false, gapMs: 6000, concurrencyToleranceMs: 2000, disclosure: catalogue.plausibilityDisclosure },
      face: { available: true, note: 'Both Tracks have a usable face; the face factor is computed on request and audited.' },
    },
    decision: null, entityId: null, lower: track('t1', 'POC-S2-11'), higher: track('t2', 'POC-S2-13'),
    ...overrides,
  };
}

function list(items: EntityCandidate[]): EntityCandidateList {
  return { label: ENTITY_CANDIDATES_LABEL, catalogue, identity: { fingerprint: 'b'.repeat(64), modelId: 'siglip2', modelVersion: '1' }, total: items.length, limit: 25, offset: 0, candidates: items };
}

const summary: EntityCandidateSummary = {
  label: ENTITY_CANDIDATES_LABEL, catalogue, identity: null, derivations: 13, pendingDerivations: 0,
  pairs: [{ cameraId: 'c-POC-S2-11', cameraCode: 'POC-S2-11', otherCameraId: 'c-POC-S2-13', otherCameraCode: 'POC-S2-13', objectClass: 'Person', open: 1, confirmed: 0, dismissed: 0 }],
};

describe('PoC S7 Entities page', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(getEntityCandidateSummary).mockResolvedValue(summary);
    vi.mocked(listEntityCandidates).mockResolvedValue(list([candidate()]));
  });

  it('carries the candidate label, the plausibility disclosure and the per-camera-pair counts', async () => {
    renderWithApp(<EntitiesPage />, { route: '/entities' });
    expect(await screen.findByText(ENTITY_CANDIDATES_LABEL)).toBeInTheDocument();
    expect(await screen.findByText(/MAVI knows no camera locations/)).toBeInTheDocument();
    const pairs = await screen.findByRole('table', { name: 'Candidates per camera pair' });
    expect(within(pairs).getByText('POC-S2-11 ↔ POC-S2-13')).toBeInTheDocument();
  });

  it('shows both Tracks side by side with each factor separately and the face factor only on request', async () => {
    const user = userEvent.setup();
    vi.mocked(compareCandidateFaces).mockResolvedValue({
      label: 'Face candidates — not identification — Development', state: 'observed',
      identity: { fingerprint: 'c'.repeat(64), modelId: 'adaface', modelVersion: '1' },
      referenceThreshold: { cosine: 0.2121, provenance: 'LFW 32-px FAR 0.1%', calibratedOnCctv: false },
      lower: { trackId: 't1', state: 'observed', reason: null }, higher: { trackId: 't2', state: 'observed', reason: null },
      pair: {
        score: 0.41, aboveThreshold: true, lowerFaceId: 'f1', lowerObservationId: 'o1', lowerEvidenceCropUrl: '/a', lowerBox: { x: 1, y: 1, width: 40, height: 40 },
        higherFaceId: 'f2', higherObservationId: 'o2', higherEvidenceCropUrl: '/b', higherBox: { x: 1, y: 1, width: 40, height: 40 },
      },
      note: 'A separate factor: it takes no part in generating or ordering candidates, and is not stored.',
    });
    renderWithApp(<EntitiesPage />, { route: '/entities' });
    await user.click(await screen.findByRole('button', { name: 'Person · POC-S2-11 ↔ POC-S2-13' }));
    expect(screen.getByRole('figure', { name: 'First Track' })).toBeInTheDocument();
    expect(screen.getByRole('figure', { name: 'Second Track' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Open source frames' })[0]).toHaveAttribute('href', '/review/video/v-t1?trackId=t1&seekMs=12000');
    const factors = screen.getByLabelText('Factors');
    expect(within(factors).getByText(/Score 0\.912 \(floor 0\.85\)/)).toBeInTheDocument();
    expect(within(factors).getByText(/different cameras, 6\.0 s apart/)).toBeInTheDocument();
    // The face is not compared until asked: that request is the audited one.
    expect(compareCandidateFaces).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Compare faces (audited)' }));
    expect(await screen.findByText(/Face score 0\.410 — above the reference threshold 0\.2121 \(LFW, not calibrated on CCTV\)/)).toBeInTheDocument();
    expect(compareCandidateFaces).toHaveBeenCalledWith('cand-1');
  });

  it('confirms only through the dialog and reports the operator decision, not an identity', async () => {
    const user = userEvent.setup();
    vi.mocked(confirmEntityCandidate).mockResolvedValue({
      label: 'Operator-confirmed Entity — not identification — Development', entityId: 'e1', entityCreated: true,
      candidate: candidate({ status: 'confirmed', entityId: 'e1', decision: { decidedAtUtc: '2026-10-30T10:00:00Z', operatorId: 'S-1', displayName: 'HOST\\op', identitySource: 'windows-negotiate', note: 'same coat', auditEntryId: 'a1' } }),
    });
    renderWithApp(<EntitiesPage />, { route: '/entities' });
    await user.click(await screen.findByRole('button', { name: 'Person · POC-S2-11 ↔ POC-S2-13' }));
    await user.type(screen.getByRole('textbox', { name: /Note/ }), 'same coat');
    await user.click(screen.getByRole('button', { name: 'Confirm same person' }));
    expect(confirmEntityCandidate).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/not an identification/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(confirmEntityCandidate).toHaveBeenCalledWith('cand-1', 'same coat'));
    expect(await screen.findByText('Confirmed by HOST\\op: a new Entity was created.')).toBeInTheDocument();
  });

  it('dismisses through the dialog and explains a refused confirmation in plain words', async () => {
    const user = userEvent.setup();
    vi.mocked(dismissEntityCandidate).mockResolvedValue({ label: '', entityId: null, entityCreated: false, candidate: candidate({ status: 'dismissed' }) });
    vi.mocked(confirmEntityCandidate).mockRejectedValue(new ApiError({ status: 409, code: 'entity_extension_implausible', detail: 'x' }));
    renderWithApp(<EntitiesPage />, { route: '/entities' });
    await user.click(await screen.findByRole('button', { name: 'Person · POC-S2-11 ↔ POC-S2-13' }));
    await user.click(screen.getByRole('button', { name: 'Confirm same person' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByText(/cannot be in two places at once/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(dismissEntityCandidate).toHaveBeenCalledWith('cand-1', null));
    expect(await screen.findByText(/will not be proposed again/)).toBeInTheDocument();
  });

  it('moves back to the last page with candidates when a decision empties the page', async () => {
    vi.mocked(listEntityCandidates).mockImplementation(async (filter) => (filter.offset ?? 0) >= 25
      ? { ...list([]), offset: filter.offset ?? 0, total: 25 }
      : { ...list(Array.from({ length: 25 }, (_, index) => candidate({ candidateId: `c${index}` }))), total: 25 });
    renderWithApp(<EntitiesPage />, { route: '/entities?offset=25' });
    expect(await screen.findByText('1–25 of 25')).toBeInTheDocument();
    expect(screen.queryByText('No open candidates')).not.toBeInTheDocument();
  });

  it('tells a non-operator that candidates are for operators only', async () => {
    vi.mocked(listEntityCandidates).mockRejectedValue(new ApiError({ status: 401, code: 'unauthorized', detail: 'x' }));
    renderWithApp(<EntitiesPage />, { route: '/entities' });
    expect(await screen.findByText('Entity candidates are available to operators only (ADR-010).')).toBeInTheDocument();
  });
});
