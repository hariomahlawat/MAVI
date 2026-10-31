import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { addCaseNote, getCase, listCases, removeCaseItem, type CaseDetail, type CaseItem } from '../../api/cases';
import { getSystemConfig } from '../../api/system';
import { renderWithApp } from '../../test/renderWithApp';
import { OPERATOR_REQUIRED } from '../review/operator';
import CaseDetailPage from './CaseDetailPage';
import CasesPage from './CasesPage';

vi.mock('../../api/cases', async () => {
  const actual = await vi.importActual<typeof import('../../api/cases')>('../../api/cases');
  return { ...actual, getCase: vi.fn(), listCases: vi.fn(), removeCaseItem: vi.fn(), addCaseNote: vi.fn(), createCase: vi.fn() };
});
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));

const caseId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21499';
const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21450';
const eventId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21451';
const videoId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21452';
const cameraId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21453';
const statement = 'A case collects evidence for investigation. Items in one case are not asserted to show the same person or vehicle.';
const asha = { operatorId: 'SITE\\asha', displayName: 'Asha', identitySource: 'windows-negotiate', atUtc: '2026-10-31T08:00:00Z', auditEntryId: 'a1' };
const fallback = { operatorId: 'development-unattributed', displayName: 'development-unattributed', identitySource: 'development-unattributed', atUtc: '2026-10-31T09:00:00Z', auditEntryId: 'a2' };

const emptySubject = {
  available: true, earlierRun: false, objectClass: null, cameraId: null, cameraName: null, startUtc: null, endUtc: null, reviewStatus: null,
  ruleId: null, entityDisplayCode: null, processingRunId: null, videoAssetId: null, startOffsetMs: null,
};

function item(overrides: Partial<CaseItem>): CaseItem {
  return { itemId: 'i', kind: 'Track', subjectId: trackId, note: null, addedBy: asha, removedBy: null, removalNote: null, subject: emptySubject, ...overrides };
}

function detail(): CaseDetail {
  return {
    statement,
    case: { caseId, title: 'Gate incident', purpose: 'Vehicle at the north gate after hours', createdBy: asha, activeItemCount: 2, removedItemCount: 1, noteCount: 1,
      holdsSubject: null },
    items: [
      item({ itemId: 'i1', note: 'first sighting', subject: { ...emptySubject, objectClass: 'Vehicle', cameraName: 'North gate', reviewStatus: 'Confirmed', earlierRun: true, videoAssetId: videoId, processingRunId: 'r1' } }),
      item({ itemId: 'i2', kind: 'AnalyticEvent', subjectId: eventId, subject: { ...emptySubject, ruleId: 'zone-dwell', cameraId } }),
      item({ itemId: 'i3', subjectId: '018f3f5a-2f70-7a2b-8a12-2d02f4c21454', note: 'wrong vehicle', removedBy: fallback, removalNote: 'different plate',
        subject: { ...emptySubject, available: false } }),
    ],
    notes: [{ noteId: 'n1', body: 'Check the loading bay camera too.', author: asha }],
  };
}

const IDENTITY_WORDS = /same person(?! or vehicle\.)|\bmatched\b|linked identity/i;

describe('PoC S11-full case detail', () => {
  beforeEach(() => {
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'UTC' });
    vi.mocked(getCase).mockReset();
    vi.mocked(removeCaseItem).mockReset();
    vi.mocked(addCaseNote).mockReset();
  });

  it('keeps a removed item, struck through, with who removed it, when and why', async () => {
    vi.mocked(getCase).mockResolvedValue(detail());
    renderWithApp(<CaseDetailPage />, { route: `/cases/${caseId}`, routePath: '/cases/:caseId' });

    const removed = await screen.findByRole('list', { name: 'Removed items' });
    const row = within(removed).getByRole('listitem');
    expect(row).toHaveClass('case-item--removed');
    expect(row).toHaveTextContent('Removed');
    expect(row).toHaveTextContent(/Removed .* by development-unattributed/);
    expect(row).toHaveTextContent('different plate');
    expect(within(row).getByText('Not attributable to a person')).toBeInTheDocument();
    expect(within(row).getByText('Unavailable')).toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'Remove from case' })).not.toBeInTheDocument();

    const active = screen.getByRole('list', { name: 'Items' });
    const [track, event] = within(active).getAllByRole('listitem');
    expect(within(track).getByText('Earlier run')).toBeInTheDocument();
    expect(within(track).getByRole('link', { name: 'Open in Review' })).toHaveAttribute('href', `/review/video/${videoId}?trackId=${trackId}`);
    expect(within(event).getByRole('link', { name: 'Open the event' })).toHaveAttribute('href', `/cameras/${cameraId}/events?event=${eventId}`);

    expect(screen.getByText(statement)).toBeInTheDocument();
    expect(screen.getByText('Check the loading bay camera too.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Audit trail' })).toHaveAttribute('href', `/audit?subject=case%3A${caseId}`);
    expect(document.body.textContent).not.toMatch(IDENTITY_WORDS);
  });

  it('links an Entity item to its Entity view while the Entity still resolves', async () => {
    const entityId = '018F3F5A-2F70-7A2B-8A12-2D02F4C214E1';
    const goneId = '018f3f5a-2f70-7a2b-8a12-2d02f4c214e2';
    vi.mocked(getCase).mockResolvedValue({
      ...detail(),
      items: [
        item({ itemId: 'e1', kind: 'Entity', subjectId: entityId, subject: { ...emptySubject, objectClass: 'Person', entityDisplayCode: 'P-0001' } }),
        item({ itemId: 'e2', kind: 'Entity', subjectId: goneId, subject: { ...emptySubject, available: false } }),
      ],
    });
    renderWithApp(<CaseDetailPage />, { route: `/cases/${caseId}`, routePath: '/cases/:caseId' });

    const [present, gone] = within(await screen.findByRole('list', { name: 'Items' })).getAllByRole('listitem');
    expect(within(present).getByRole('link', { name: 'Open the Entity' })).toHaveAttribute('href', `/entities?entity=${entityId.toLowerCase()}`);
    expect(within(gone).queryByRole('link', { name: 'Open the Entity' })).not.toBeInTheDocument();
  });

  it('records a removal with its note, never a delete', async () => {
    const user = userEvent.setup();
    vi.mocked(getCase).mockResolvedValue(detail());
    vi.mocked(removeCaseItem).mockResolvedValue(item({ itemId: 'i1', removedBy: asha }));
    renderWithApp(<CaseDetailPage />, { route: `/cases/${caseId}`, routePath: '/cases/:caseId' });
    const active = await screen.findByRole('list', { name: 'Items' });
    await user.click(within(active).getAllByRole('button', { name: 'Remove from case' })[0]);
    const form = screen.getByRole('form', { name: 'Remove from case' });
    expect(form).toHaveTextContent('It is never deleted.');
    await user.type(within(form).getByRole('textbox', { name: /Removal note/ }), 'not relevant');
    await user.click(within(form).getByRole('button', { name: 'Record removal' }));
    await waitFor(() => expect(removeCaseItem).toHaveBeenCalledWith(caseId, 'i1', 'not relevant'));
    await waitFor(() => expect(getCase).toHaveBeenCalledTimes(2));
  });

  it('appends a note', async () => {
    const user = userEvent.setup();
    vi.mocked(getCase).mockResolvedValue(detail());
    vi.mocked(addCaseNote).mockResolvedValue({ noteId: 'n2', body: 'b', author: asha });
    renderWithApp(<CaseDetailPage />, { route: `/cases/${caseId}`, routePath: '/cases/:caseId' });
    await user.type(await screen.findByRole('textbox', { name: 'New note' }), 'Plate partially read.');
    await user.click(screen.getByRole('button', { name: 'Add note' }));
    await waitFor(() => expect(addCaseNote).toHaveBeenCalledWith(caseId, 'Plate partially read.'));
  });

  it('states that operator identity is required when the case answers 401', async () => {
    vi.mocked(getCase).mockRejectedValue(new ApiError({ status: 401, code: 'api_error', detail: 'Unauthorized' }));
    renderWithApp(<CaseDetailPage />, { route: `/cases/${caseId}`, routePath: '/cases/:caseId' });
    expect(await screen.findByText(new RegExp(OPERATOR_REQUIRED))).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('PoC S11-full cases list', () => {
  beforeEach(() => {
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'UTC' });
    vi.mocked(listCases).mockReset();
  });

  it('reaches every case through the server cursor', async () => {
    const user = userEvent.setup();
    const older = { ...detail().case, caseId: '018f3f5a-2f70-7a2b-8a12-2d02f4c214aa', title: 'Older case' };
    vi.mocked(listCases).mockImplementation(async (_options, cursor) => (cursor === 'p2'
      ? { statement, cases: [older], nextCursor: null }
      : { statement, cases: [detail().case], nextCursor: 'p2' }));
    renderWithApp(<CasesPage />, { route: '/cases' });

    const list = await screen.findByRole('list', { name: 'Cases' });
    expect(within(list).queryByRole('link', { name: 'Older case' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Load more cases' }));
    expect(await within(list).findByRole('link', { name: 'Older case' })).toHaveAttribute('href', `/cases/${older.caseId}`);
    expect(screen.queryByRole('button', { name: 'Load more cases' })).not.toBeInTheDocument();
  });

  it('lists cases with their counts and creator', async () => {
    vi.mocked(listCases).mockResolvedValue({ statement, cases: [detail().case], nextCursor: null });
    renderWithApp(<CasesPage />, { route: '/cases' });
    const list = await screen.findByRole('list', { name: 'Cases' });
    expect(within(list).getByRole('link', { name: 'Gate incident' })).toHaveAttribute('href', `/cases/${caseId}`);
    expect(list).toHaveTextContent('2 items · 1 removed · 1 note');
    expect(screen.getByText(statement)).toBeInTheDocument();
    expect(screen.getByRole('form', { name: 'New case' })).toBeInTheDocument();
  });

  it('shows the operator-required state instead of the list and the form when identity is disabled', async () => {
    vi.mocked(listCases).mockRejectedValue(new ApiError({ status: 401, code: 'api_error', detail: 'Unauthorized' }));
    renderWithApp(<CasesPage />, { route: '/cases' });
    expect(await screen.findByText(new RegExp(OPERATOR_REQUIRED))).toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'New case' })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
