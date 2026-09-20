import { render, screen } from '@testing-library/react';
import type { UseQueryResult } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import AsyncBoundary from './AsyncBoundary';
import type { AsyncState } from './asyncState';
import { fromQuery } from './fromQuery';

/**
 * Section 14.1 makes this a correctness boundary, not a styling one: a failed
 * request must never reach the operator as an empty result. Each test below
 * fails if that guarantee is broken in one specific way.
 */

const EMPTY = <p>No videos imported yet</p>;
const content = (rows: string[]) => <ul>{rows.map((r) => <li key={r}>{r}</li>)}</ul>;

function renderBoundary(state: AsyncState<string[]>, extra: Record<string, unknown> = {}) {
  return render(
    <AsyncBoundary
      state={state}
      isEmpty={(rows) => rows.length === 0}
      empty={EMPTY}
      loadingLabel="Loading videos…"
      unavailableLabel="The video list is unavailable."
      {...extra}
    >
      {content}
    </AsyncBoundary>,
  );
}

describe('AsyncBoundary selects exactly one state', () => {
  it('shows loading, and neither empty nor content', () => {
    renderBoundary({ kind: 'loading' });
    expect(screen.getByText('Loading videos…')).toBeInTheDocument();
    expect(screen.queryByText('No videos imported yet')).not.toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('shows the empty block only for a successful empty result', () => {
    renderBoundary({ kind: 'ready', data: [] });
    expect(screen.getByText('No videos imported yet')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows content for a successful populated result', () => {
    renderBoundary({ kind: 'ready', data: ['CAM-01.mp4'] });
    expect(screen.getByText('CAM-01.mp4')).toBeInTheDocument();
    expect(screen.queryByText('No videos imported yet')).not.toBeInTheDocument();
  });

  it('never renders the empty block for a failure', () => {
    // The defect this whole boundary exists to prevent.
    renderBoundary({ kind: 'unavailable', error: new Error('network') });
    expect(screen.getByRole('alert')).toHaveTextContent('The video list is unavailable.');
    expect(screen.queryByText('No videos imported yet')).not.toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('never leaves a spinner running after a terminal failure', () => {
    renderBoundary({ kind: 'unavailable', error: new Error('network') });
    expect(screen.queryByText('Loading videos…')).not.toBeInTheDocument();
  });

  it('offers a retry on an unavailable state when the caller supplies one', async () => {
    const onRetry = vi.fn();
    renderBoundary({ kind: 'unavailable', error: new Error('network') }, { onRetry });
    screen.getByRole('button', { name: 'Retry' }).click();
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('keeps data on screen when a later refetch fails, and says so', () => {
    renderBoundary({ kind: 'ready', data: ['CAM-01.mp4'], degraded: { error: new Error('network') } });
    expect(screen.getByText('CAM-01.mp4')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Showing the last known values');
  });
});

describe('fromQuery', () => {
  const query = (over: Partial<UseQueryResult<string[]>>) => over as UseQueryResult<string[]>;

  it('maps a first load to loading', () => {
    expect(fromQuery(query({ data: undefined, isError: false }))).toEqual({ kind: 'loading' });
  });

  it('maps a failed first load to unavailable, never to empty data', () => {
    const error = new Error('boom');
    const state = fromQuery(query({ data: undefined, isError: true, error }));
    expect(state).toEqual({ kind: 'unavailable', error });
    // There is no `data` to misread: the union does not carry one here.
    expect('data' in state).toBe(false);
  });

  it('maps a successful empty response to ready with an empty payload', () => {
    expect(fromQuery(query({ data: [], isError: false }))).toEqual({ kind: 'ready', data: [] });
  });

  it('keeps the last good data when a refetch fails, and marks it degraded', () => {
    const error = new Error('later');
    const state = fromQuery(query({ data: ['a'], isError: true, error }));
    expect(state).toEqual({ kind: 'ready', data: ['a'], degraded: { error } });
  });
});
