import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readAudit, type AuditEntry } from '../../api/audit';
import { ApiError } from '../../api/client';
import { getSystemConfig } from '../../api/system';
import { renderWithApp } from '../../test/renderWithApp';
import { OPERATOR_REQUIRED } from '../review/operator';
import AuditPage from './AuditPage';

vi.mock('../../api/audit', async () => {
  const actual = await vi.importActual<typeof import('../../api/audit')>('../../api/audit');
  return { ...actual, readAudit: vi.fn() };
});
vi.mock('../../api/system', () => ({ getSystemConfig: vi.fn() }));

const trackId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21450';
const caseId = '018f3f5a-2f70-7a2b-8a12-2d02f4c21499';
const hash = 'ab'.repeat(32);

function entry(overrides: Partial<AuditEntry>): AuditEntry {
  return {
    entryId: 'e', operatorId: 'SITE\\asha', operatorDisplayName: 'Asha', identitySource: 'windows-negotiate', action: 'tracks.review-decided',
    subjectType: 'track', subjectId: trackId, recordedAtUtc: '2026-10-31T08:00:00Z', payloadSha256: hash, correlationId: 'corr-1', ...overrides,
  };
}

const statement = 'Append-only audit of operator actions.';

describe('PoC S11-full audit trail', () => {
  beforeEach(() => {
    vi.mocked(getSystemConfig).mockResolvedValue({ displayTimeZoneId: 'UTC' });
    vi.mocked(readAudit).mockReset();
  });

  it('reads an Entity scope from the URL, asks the server for it alone, and pages it with the server cursor', async () => {
    const user = userEvent.setup();
    const entityId = '018f3f5a-2f70-7a2b-8a12-2d02f4c214e1';
    vi.mocked(readAudit)
      .mockResolvedValueOnce({ statement, items: [entry({ entryId: 'e2', subjectType: 'entity', subjectId: entityId, action: 'entities.merged' })],
        nextCursor: 'c1', entityScope: { entityId, entityCount: 2, candidateCount: 61 } })
      .mockResolvedValueOnce({ statement, items: [entry({ entryId: 'e1', subjectType: 'entity-candidate', subjectId: 'cand-0', action: 'entities.candidate-reopened' })],
        nextCursor: null, entityScope: { entityId, entityCount: 2, candidateCount: 61 } });
    renderWithApp(<AuditPage />, { route: `/audit?entityId=${entityId.toUpperCase()}` });

    expect(await screen.findByText('entities.merged')).toBeInTheDocument();
    expect(vi.mocked(readAudit).mock.calls[0][0]).toEqual(expect.objectContaining({ entityId, subjects: [] }));
    expect(screen.getByText(/every candidate ever linked to them, resolved by the server/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Load more/ }));
    expect(await screen.findByText('entities.candidate-reopened')).toBeInTheDocument();
    expect(vi.mocked(readAudit).mock.calls[1][1]).toBe('c1');
    expect(vi.mocked(readAudit).mock.calls[1][0]).toEqual(expect.objectContaining({ entityId }));
  });

  it('reads the subjects in the URL, newest first, and labels the unattributed fallback', async () => {
    vi.mocked(readAudit).mockResolvedValueOnce({
      statement,
      items: [
        entry({ entryId: 'e2', action: 'cases.item-added', subjectType: 'case', subjectId: caseId, operatorId: 'development-unattributed',
          operatorDisplayName: 'development-unattributed', identitySource: 'development-unattributed', correlationId: 'corr-2' }),
        entry({ entryId: 'e1' }),
      ],
      nextCursor: null, entityScope: null,
    });
    renderWithApp(<AuditPage />, { route: `/audit?subject=track%3A${trackId}&subject=case%3A${caseId}&action=x` });

    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('cases.item-added');
    expect(within(rows[0]).getByText('Not attributable to a person')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('link', { name: `case:${caseId}` })).toHaveAttribute('href', `/cases/${caseId}`);
    expect(rows[1]).toHaveTextContent('Asha');
    expect(rows[1]).toHaveTextContent('SITE\\asha');
    expect(within(rows[1]).queryByText('Not attributable to a person')).not.toBeInTheDocument();
    // The hash is shortened, its whole value on hover and to assistive technology.
    const shortHash = within(rows[1]).getByText(`${hash.slice(0, 12)}…`);
    expect(shortHash).toHaveAttribute('title', hash);
    expect(rows[1]).toHaveTextContent('corr-1');

    expect(readAudit).toHaveBeenCalledWith({ subjects: [`track:${trackId}`, `case:${caseId}`], action: 'x', operatorId: undefined },
      null, 50, expect.any(AbortSignal));
    expect(screen.getByText(statement)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('pages with the cursor the server returned', async () => {
    const user = userEvent.setup();
    vi.mocked(readAudit)
      .mockResolvedValueOnce({ statement, items: [entry({ entryId: 'e2' })], nextCursor: '638000000000000000.abc', entityScope: null, })
      .mockResolvedValueOnce({ statement, items: [entry({ entryId: 'e1', correlationId: 'corr-older' })], nextCursor: null, entityScope: null, });
    renderWithApp(<AuditPage />, { route: '/audit' });

    await user.click(await screen.findByRole('button', { name: 'Load more' }));
    await waitFor(() => expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3));
    expect(vi.mocked(readAudit).mock.calls[1][1]).toBe('638000000000000000.abc');
    expect(screen.getByText('corr-older')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('applies an action filter through the URL', async () => {
    const user = userEvent.setup();
    vi.mocked(readAudit).mockResolvedValue({ statement, items: [], nextCursor: null, entityScope: null, });
    renderWithApp(<AuditPage />, { route: '/audit' });
    expect(await screen.findByText('No audit entries')).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: /Action/ }), 'cases.note-added');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(readAudit).toHaveBeenLastCalledWith({ subjects: [], action: 'cases.note-added', operatorId: undefined },
      null, 50, expect.any(AbortSignal)));
  });

  it('states that operator identity is required when the audit answers 401', async () => {
    vi.mocked(readAudit).mockRejectedValue(new ApiError({ status: 401, code: 'api_error', detail: 'Unauthorized' }));
    renderWithApp(<AuditPage />, { route: '/audit' });
    expect(await screen.findByText(new RegExp(OPERATOR_REQUIRED))).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
