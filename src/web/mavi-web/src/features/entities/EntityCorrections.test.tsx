import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import {
  ENTITY_CANDIDATES_LABEL,
  ENTITY_LABEL,
  confirmEntityCandidate,
  getEntity,
  getEntityCandidateHistory,
  getEntityCandidateSummary,
  listEntityCandidates,
  mergeEntity,
  reopenEntityCandidate,
  unlinkEntityTrack,
  type EntityCandidate,
  type EntityMembershipChange,
  type EntityResponse,
} from '../../api/entities';
import { renderWithApp } from '../../test/renderWithApp';
import EntitiesPage from './EntitiesPage';

vi.mock('../../api/entities', async () => {
  const actual = await vi.importActual<typeof import('../../api/entities')>('../../api/entities');
  return {
    ...actual,
    listEntityCandidates: vi.fn(), getEntityCandidateSummary: vi.fn(), confirmEntityCandidate: vi.fn(), dismissEntityCandidate: vi.fn(),
    compareCandidateFaces: vi.fn(), getEntity: vi.fn(), unlinkEntityTrack: vi.fn(), mergeEntity: vi.fn(), reopenEntityCandidate: vi.fn(),
    getEntityCandidateHistory: vi.fn(),
  };
});
// Cases are read only when Add to case is opened; nothing here opens it.
vi.mock('../../api/cases', async () => {
  const actual = await vi.importActual<typeof import('../../api/cases')>('../../api/cases');
  return { ...actual, listCases: vi.fn() };
});

const E1 = '00000000-0000-4000-8000-0000000000e1';
const E2 = '00000000-0000-4000-8000-0000000000e2';

const catalogue = {
  version: 'mavi-entity-candidates-v1', sha256: 'a'.repeat(64), appearanceFloor: 0.85, concurrencyToleranceMs: 2000, parameters: [],
  plausibilityDisclosure: 'Time and camera only.',
};

function track(id: string, camera: string, entityId: string | null = null): EntityCandidate['lower'] {
  return {
    trackId: id, processingRunId: 'r', videoAssetId: 'v-' + id, cameraId: 'c-' + camera, cameraCode: camera, cameraName: camera + ' view',
    objectClass: 'Person', startTimestampUtc: '2026-10-01T04:10:00Z', endTimestampUtc: '2026-10-01T04:10:04Z', startOffsetMs: 0,
    endOffsetMs: 4000, thumbnailUrl: null, entityId, visible: true,
  };
}

const decision = { decidedAtUtc: '2026-10-30T10:00:00Z', operatorId: 'S-1', displayName: 'Asha', identitySource: 'windows-negotiate', note: null, auditEntryId: 'a1' };

function candidate(overrides: Partial<EntityCandidate> = {}): EntityCandidate {
  return {
    candidateId: 'cand-1', label: ENTITY_CANDIDATES_LABEL, objectClass: 'Person', status: 'open', catalogueVersion: catalogue.version,
    identityFingerprint: 'b'.repeat(64),
    factors: {
      appearance: { score: 0.912, floor: 0.85, source: 'SigLIP 2' },
      plausibility: { verdict: 'plausible', sameCamera: false, gapMs: 6000, concurrencyToleranceMs: 2000, disclosure: catalogue.plausibilityDisclosure },
      face: null,
    },
    decision: null, entityId: null, lower: track('t1', 'POC-S2-11'), higher: track('t2', 'POC-S2-13'),
    ...overrides,
  };
}

function change(overrides: Partial<EntityMembershipChange>): EntityMembershipChange {
  return {
    sequence: 1, trackId: 't1', entityId: E1, change: 'Joined', cause: 'CandidateConfirmed', candidateId: 'cand-1', note: null,
    operatorId: 'S-1', operatorDisplayName: 'Asha', identitySource: 'windows-negotiate', atUtc: '2026-10-30T10:00:00Z', auditEntryId: 'a1',
    ...overrides,
  };
}

function entity(overrides: Partial<EntityResponse> = {}): EntityResponse {
  return {
    label: ENTITY_LABEL, entityId: E1, displayCode: 'P-0001', entityType: 'Person', identityStatus: 'Unknown',
    createdAtUtc: '2026-10-30T10:00:00Z', updatedAtUtc: '2026-10-30T10:00:00Z',
    members: [track('t1', 'POC-S2-11', E1), track('t2', 'POC-S2-13', E1)],
    confirmations: [candidate({ status: 'confirmed', entityId: E1, decision })],
    state: 'Active', mergedIntoEntityId: null, mergedFromEntityIds: [], relatedCandidateIds: ['cand-1'],
    history: [change({ sequence: 1 }), change({ sequence: 2, trackId: 't2' })],
    ...overrides,
  };
}

function list(items: EntityCandidate[]) {
  return { label: ENTITY_CANDIDATES_LABEL, catalogue, identity: { fingerprint: 'b', modelId: 'm', modelVersion: '1' }, total: items.length, limit: 25, offset: 0, candidates: items };
}

/** No correction surface may claim identity. */
const IDENTITY_WORDS = /same (person|vehicle)|\bmatched\b|\bidentified\b/i;

describe('PoC S11-full Entity corrections', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(getEntityCandidateSummary).mockResolvedValue({ label: ENTITY_CANDIDATES_LABEL, catalogue, identity: null, derivations: 1, pendingDerivations: 0, pairs: [] });
    vi.mocked(listEntityCandidates).mockResolvedValue(list([]));
  });

  it('renders the membership history with the unattributed label, and links the audit trail of the Entity and its confirmations', async () => {
    const user = userEvent.setup();
    vi.mocked(getEntity).mockResolvedValue(entity({
      history: [
        change({ sequence: 1 }),
        change({ sequence: 2, trackId: 't2' }),
        change({ sequence: 3, trackId: 't2', change: 'Left', cause: 'Unlinked', candidateId: null, note: 'different coat',
          operatorId: 'development-unattributed', operatorDisplayName: 'development-unattributed', identitySource: 'development-unattributed' }),
      ],
      members: [track('t1', 'POC-S2-11', E1)],
      mergedFromEntityIds: [E2],
      // cand-0 was confirmed into this Entity, then its Track was unlinked and the candidate reopened: no longer a
      // confirmation, still part of the Entity's trail.
      relatedCandidateIds: ['cand-0', 'cand-1'],
    }));
    renderWithApp(<EntitiesPage />, { route: `/entities?entity=${E1}` });

    expect(await screen.findByText('P-0001')).toBeInTheDocument();
    expect(screen.getByText(ENTITY_LABEL)).toBeInTheDocument();
    // The server resolves the Entity's whole scope (merged Entities, every candidate ever linked): the link names only the Entity.
    expect(screen.getByRole('link', { name: 'Audit trail' })).toHaveAttribute('href', `/audit?entityId=${E1.toLowerCase()}`);
    await user.click(screen.getByText('Membership history'));
    const history = screen.getByRole('list', { name: 'Membership history' });
    const rows = within(history).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent(/Joined Person Track on POC-S2-11.*candidate confirmed/);
    expect(rows[2]).toHaveTextContent(/Left Person Track on POC-S2-13.*unlinked/);
    expect(rows[2]).toHaveTextContent('different coat');
    expect(within(rows[2]).getByText('Not attributable to a person')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add to case' })).toBeInTheDocument();
    // The Entity view itself (S7's page introduction describes candidates separately).
    expect(screen.getByText('P-0001').closest('section')?.textContent).not.toMatch(IDENTITY_WORDS);
  });

  it('unlinks the last member through a confirm step, and keeps the Entity with no members', async () => {
    const user = userEvent.setup();
    const before = entity({ members: [track('t1', 'POC-S2-11', E1)] });
    const after = entity({ members: [], history: [...before.history, change({ sequence: 3, change: 'Left', cause: 'Unlinked', note: 'wrong person crop' })] });
    vi.mocked(getEntity).mockResolvedValueOnce(before).mockResolvedValue(after);
    vi.mocked(unlinkEntityTrack).mockResolvedValue(after);
    renderWithApp(<EntitiesPage />, { route: `/entities?entity=${E1}` });

    const members = await screen.findByRole('list', { name: 'Members' });
    await user.click(within(members).getByRole('button', { name: 'Unlink' }));
    await user.type(within(members).getByRole('textbox', { name: /Unlink note/ }), 'wrong person crop');
    await user.click(within(members).getByRole('button', { name: 'Unlink this Track' }));
    expect(unlinkEntityTrack).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('an Entity is kept even with one or no member');
    await user.click(within(dialog).getByRole('button', { name: 'Unlink' }));

    await waitFor(() => expect(unlinkEntityTrack).toHaveBeenCalledWith(E1, 't1', 'wrong person crop'));
    expect(await screen.findByText(/No members now\. The Entity is kept/)).toBeInTheDocument();
    expect(screen.getByText('P-0001')).toBeInTheDocument();
    expect(screen.queryByText(/dissolve[sd]? /i)).not.toBeInTheDocument();
  });

  it('shows a merged Entity as merged into its target, with a link and no corrections', async () => {
    vi.mocked(getEntity).mockImplementation(async (id) => id === E1
      ? entity({ state: 'Merged', mergedIntoEntityId: E2, members: [] })
      : entity({ entityId: E2, displayCode: 'P-0002' }));
    renderWithApp(<EntitiesPage />, { route: `/entities?entity=${E1}` });
    expect(await screen.findByRole('link', { name: 'P-0002' })).toHaveAttribute('href', `/entities?entity=${E2}`);
    expect(screen.getByText(/keeps its history and no longer changes/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Merge with another Entity/ })).not.toBeInTheDocument();
  });

  it('offers a merge when confirmation meets two Entities, lets the operator choose which is kept, and names the two Tracks of an implausible refusal', async () => {
    const user = userEvent.setup();
    const pair = candidate({ lower: track('t1', 'POC-S2-11', E1), higher: track('t2', 'POC-S2-13', E2) });
    vi.mocked(listEntityCandidates).mockResolvedValue(list([pair]));
    vi.mocked(confirmEntityCandidate).mockRejectedValue(new ApiError({ status: 409, code: 'entity_merge_unsupported', detail: 'merge explicitly' }));
    vi.mocked(getEntity).mockImplementation(async (id) => id === E1
      ? entity()
      : entity({ entityId: E2, displayCode: 'P-0002', members: [track('t2', 'POC-S2-13', E2), track('t9', 'POC-S2-17', E2)] }));
    vi.mocked(mergeEntity).mockRejectedValue(new ApiError({
      status: 409, code: 'entity_merge_implausible', detail: 'x', extensions: { conflictingTrackId: 't1', otherConflictingTrackId: 't9' },
    }));
    renderWithApp(<EntitiesPage />, { route: '/entities' });

    await user.click(await screen.findByRole('button', { name: 'Person · POC-S2-11 ↔ POC-S2-13' }));
    await user.click(screen.getByRole('button', { name: /^Confirm same/ }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByText(/Merge the Entities explicitly/)).toBeInTheDocument();

    const merge = await screen.findByRole('region', { name: 'Merge Entities' });
    await waitFor(() => expect(within(merge).getByRole('radio', { name: /Keep P-0002/ })).toBeInTheDocument());
    await user.click(within(merge).getByRole('radio', { name: /Keep P-0002/ }));
    await user.click(within(merge).getByRole('button', { name: 'Merge P-0001 into P-0002' }));
    expect(mergeEntity).not.toHaveBeenCalled();
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Merge' }));

    await waitFor(() => expect(mergeEntity).toHaveBeenCalledWith(E1, E2, null));
    const refusal = await within(merge).findByText(/Not merged: a member of one Entity/);
    expect(refusal).toHaveTextContent('Person Track on POC-S2-11');
    expect(refusal).toHaveTextContent('Person Track on POC-S2-17');
    expect(document.body.textContent).not.toMatch(/\bmatched\b|\bidentified\b/i);
  });

  it('reopens a dismissed candidate with a note through a confirm step', async () => {
    const user = userEvent.setup();
    const dismissed = candidate({ status: 'dismissed', decision });
    vi.mocked(listEntityCandidates).mockResolvedValue(list([dismissed]));
    vi.mocked(reopenEntityCandidate).mockResolvedValue({ label: '', entityId: null, entityCreated: false, candidate: candidate() });
    renderWithApp(<EntitiesPage />, { route: '/entities?status=dismissed' });

    await user.click(await screen.findByRole('button', { name: 'Person · POC-S2-11 ↔ POC-S2-13' }));
    const group = screen.getByRole('group', { name: 'Reopen candidate' });
    await user.type(within(group).getByRole('textbox', { name: /Reopen note/ }), 'dismissed by mistake');
    await user.click(within(group).getByRole('button', { name: 'Reopen' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Reopen' }));
    await waitFor(() => expect(reopenEntityCandidate).toHaveBeenCalledWith('cand-1', 'dismissed by mistake'));
    expect(await screen.findByText(/Reopened: the candidate is open again/)).toBeInTheDocument();
  });

  it('explains a still-linked refusal and points to the Entity to unlink a Track first', async () => {
    const user = userEvent.setup();
    vi.mocked(listEntityCandidates).mockResolvedValue(list([candidate({ status: 'confirmed', entityId: E1, decision })]));
    vi.mocked(reopenEntityCandidate).mockRejectedValue(new ApiError({
      status: 409, code: 'entity_candidate_still_linked', detail: 'unlink first', extensions: { entityId: E1 },
    }));
    renderWithApp(<EntitiesPage />, { route: '/entities?status=confirmed' });

    await user.click(await screen.findByRole('button', { name: 'Person · POC-S2-11 ↔ POC-S2-13' }));
    await user.click(screen.getByRole('button', { name: 'Reopen' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Reopen' }));
    expect(await screen.findByText(/both Tracks are still in one Entity\. Unlink one of the two Tracks first\./)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the Entity' })).toHaveAttribute('href', `/entities?entity=${E1}`);
  });

  it('shows the candidate decision history on request', async () => {
    const user = userEvent.setup();
    vi.mocked(listEntityCandidates).mockResolvedValue(list([candidate()]));
    vi.mocked(getEntityCandidateHistory).mockResolvedValue({
      candidateId: 'cand-1',
      decisions: [
        { sequence: 1, decision: 'Dismissed', entityId: null, note: 'unsure', operatorId: 'S-1', operatorDisplayName: 'Asha', identitySource: 'windows-negotiate', atUtc: '2026-10-29T10:00:00Z', auditEntryId: 'a' },
        { sequence: 2, decision: 'Reopened', entityId: null, note: null, operatorId: 'S-2', operatorDisplayName: 'Ravi', identitySource: 'windows-negotiate', atUtc: '2026-10-30T10:00:00Z', auditEntryId: 'b' },
      ],
    });
    renderWithApp(<EntitiesPage />, { route: '/entities' });
    await user.click(await screen.findByRole('button', { name: 'Person · POC-S2-11 ↔ POC-S2-13' }));
    expect(getEntityCandidateHistory).not.toHaveBeenCalled();
    await user.click(screen.getByText('Decision history'));
    const history = await screen.findByRole('list', { name: 'Candidate decision history' });
    const rows = within(history).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent(/Dismissed.*Asha/);
    expect(rows[0]).toHaveTextContent('unsure');
    expect(rows[1]).toHaveTextContent(/Reopened.*Ravi/);
  });
});
