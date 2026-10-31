import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { addCaseItem, createCase, listCases, type CaseItem, type CaseSummary } from '../../api/cases';
import { renderWithApp } from '../../test/renderWithApp';
import { OPERATOR_REQUIRED } from '../review/operator';
import AddToCase from './AddToCase';

vi.mock('../../api/cases', async () => {
  const actual = await vi.importActual<typeof import('../../api/cases')>('../../api/cases');
  return { ...actual, listCases: vi.fn(), createCase: vi.fn(), addCaseItem: vi.fn() };
});

const eventId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21450';
const actor = { operatorId: 'SITE\\asha', displayName: 'Asha', identitySource: 'windows-negotiate', atUtc: '2026-10-31T08:00:00Z', auditEntryId: 'a' };

function summary(caseId: string, title: string, holdsSubject: boolean | null = false): CaseSummary {
  return { caseId, title, purpose: null, createdBy: actor, activeItemCount: 0, removedItemCount: 0, noteCount: 0, holdsSubject };
}

const item = { itemId: 'i1' } as CaseItem;
const statement = 'A case collects evidence for investigation. Items in one case are not asserted to show the same person or vehicle.';

describe('PoC S11-full Add to case', () => {
  beforeEach(() => {
    vi.mocked(listCases).mockReset();
    vi.mocked(createCase).mockReset();
    vi.mocked(addCaseItem).mockReset();
    // c2 already holds the subject: the server marks it, so the picker needs no second list.
    vi.mocked(listCases).mockImplementation(async () => ({
      statement,
      cases: [summary('c1', 'Gate incident'), summary('c2', 'Loading bay', true)],
      nextCursor: null,
    }));
  });

  it('reads nothing until opened, then adds the subject to an existing case with a note', async () => {
    const user = userEvent.setup();
    vi.mocked(addCaseItem).mockResolvedValue(item);
    renderWithApp(<AddToCase kind="AnalyticEvent" subjectId={eventId.toUpperCase()} />);
    expect(listCases).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Add to case' }));
    const form = screen.getByRole('form', { name: 'Add to case' });
    expect(form).toHaveTextContent(statement);
    const picker = within(form).getByRole('combobox', { name: 'Case' });
    await waitFor(() => expect(within(picker).getByRole('option', { name: 'Gate incident' })).toBeInTheDocument());
    // A case already holding this event cannot be chosen again.
    await waitFor(() => expect(within(picker).getByRole('option', { name: 'Loading bay (already holds this Event)' })).toBeDisabled());
    expect(listCases).toHaveBeenCalledWith({ title: '', holding: { kind: 'AnalyticEvent', subjectId: eventId } }, null, 50, expect.any(AbortSignal));

    await user.selectOptions(picker, 'c1');
    await user.type(within(form).getByRole('textbox', { name: /Note/ }), 'vehicle stopped here');
    await user.click(within(form).getByRole('button', { name: 'Add to case' }));

    expect(await screen.findByText(/Added to/)).toBeInTheDocument();
    expect(addCaseItem).toHaveBeenCalledWith('c1', { kind: 'AnalyticEvent', subjectId: eventId, note: 'vehicle stopped here' });
    expect(createCase).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: 'Gate incident' })).toHaveAttribute('href', '/cases/c1');
  });

  it('creates a new case inline, then adds the subject to it', async () => {
    const user = userEvent.setup();
    vi.mocked(createCase).mockResolvedValue(summary('c9', 'North gate, 31 Oct'));
    vi.mocked(addCaseItem).mockResolvedValue(item);
    renderWithApp(<AddToCase kind="Track" subjectId={eventId} />);
    await user.click(screen.getByRole('button', { name: 'Add to case' }));
    const form = screen.getByRole('form', { name: 'Add to case' });
    await user.selectOptions(within(form).getByRole('combobox', { name: 'Case' }), 'New case…');

    // A new case needs a title before anything is sent.
    await user.click(within(form).getByRole('button', { name: 'Add to case' }));
    expect(await within(form).findByText('Enter a title for the new case.')).toBeInTheDocument();
    expect(createCase).not.toHaveBeenCalled();

    await user.type(within(form).getByRole('textbox', { name: 'New case title' }), 'North gate, 31 Oct');
    await user.click(within(form).getByRole('button', { name: 'Add to case' }));

    expect(await screen.findByRole('link', { name: 'North gate, 31 Oct' })).toHaveAttribute('href', '/cases/c9');
    expect(createCase).toHaveBeenCalledWith('North gate, 31 Oct');
    expect(addCaseItem).toHaveBeenCalledWith('c9', { kind: 'Track', subjectId: eventId, note: null });
  });

  it('says a subject already in the case is already there', async () => {
    const user = userEvent.setup();
    vi.mocked(addCaseItem).mockRejectedValue(new ApiError({ status: 409, code: 'case_item_already_present', detail: 'The subject is already an item of this case.' }));
    renderWithApp(<AddToCase kind="Track" subjectId={eventId} />);
    await user.click(screen.getByRole('button', { name: 'Add to case' }));
    const form = screen.getByRole('form', { name: 'Add to case' });
    await waitFor(() => expect(within(form).getByRole('option', { name: 'Gate incident' })).toBeInTheDocument());
    await user.selectOptions(within(form).getByRole('combobox', { name: 'Case' }), 'c1');
    await user.click(within(form).getByRole('button', { name: 'Add to case' }));
    expect(await screen.findByText('This Track is already an item of that case.')).toBeInTheDocument();
  });

  it('states that operator identity is required when cases answer 401', async () => {
    const user = userEvent.setup();
    vi.mocked(listCases).mockRejectedValue(new ApiError({ status: 401, code: 'api_error', detail: 'Unauthorized' }));
    renderWithApp(<AddToCase kind="Track" subjectId={eventId} />);
    await user.click(screen.getByRole('button', { name: 'Add to case' }));
    expect(await screen.findByText(new RegExp(OPERATOR_REQUIRED))).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Case' })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reaches cases beyond the first page and finds a case by title on the server', async () => {
    const user = userEvent.setup();
    vi.mocked(listCases).mockImplementation(async (options, cursor) => {
      if (options?.title) return { statement, cases: [summary('c9', 'Gate incident 9')], nextCursor: null };
      return cursor === 'p2'
        ? { statement, cases: [summary('c2', 'Older case')], nextCursor: null }
        : { statement, cases: [summary('c1', 'Newest case')], nextCursor: 'p2' };
    });
    renderWithApp(<AddToCase kind="Track" subjectId={eventId} />);
    await user.click(screen.getByRole('button', { name: 'Add to case' }));

    expect(await screen.findByRole('option', { name: 'Newest case' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Older case' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Load more cases' }));
    expect(await screen.findByRole('option', { name: 'Older case' })).toBeInTheDocument();
    expect(vi.mocked(listCases).mock.calls.some((call) => call[1] === 'p2')).toBe(true);
    // Every page asks the server to mark the cases that already hold this subject.
    expect(vi.mocked(listCases).mock.calls.every((call) => call[0]?.holding?.subjectId === eventId)).toBe(true);

    await user.type(screen.getByRole('searchbox', { name: /Find a case by title/ }), 'gate 9');
    await user.click(screen.getByRole('button', { name: 'Find' }));
    expect(await screen.findByRole('option', { name: 'Gate incident 9' })).toBeInTheDocument();
    expect(vi.mocked(listCases).mock.calls.some((call) => call[0]?.title === 'gate 9')).toBe(true);
  });

  it('moves focus into the form when opened and back to the button when closed', async () => {
    const user = userEvent.setup();
    renderWithApp(<AddToCase kind="Track" subjectId={eventId} />);
    const button = screen.getByRole('button', { name: 'Add to case' });
    // The button is replaced by the form, so it claims no expanded state.
    expect(button).not.toHaveAttribute('aria-expanded');

    await user.click(button);
    expect(screen.getByRole('form', { name: 'Add to case' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Add to case' })).toHaveFocus();
  });
});
