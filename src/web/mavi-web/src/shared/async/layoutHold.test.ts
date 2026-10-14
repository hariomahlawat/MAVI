import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AsyncState } from './asyncState';
import { settled, useHeldState, useLayoutHold } from './layoutHold';

const loading: AsyncState<never> = { kind: 'loading' };
const ready = <T,>(data: T): AsyncState<T> => ({ kind: 'ready', data });
const unavailable: AsyncState<never> = { kind: 'unavailable', error: new Error('down') };

/** Every surface keeps its initial-layout hold in the shared primitive, not a page-local latch. */
const features = import.meta.glob('../../features/**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('the shared layout hold (§38)', () => {
  it('reads settledness from the normalised AsyncState: a supporting state settles when it is not loading', () => {
    expect(settled([])).toBe(true);
    expect(settled([ready(1), unavailable])).toBe(true);
    expect(settled([ready(1), loading])).toBe(false);
  });

  it('holds until every supporting state settles, then stays drawn through a later loading', () => {
    const { result, rerender } = renderHook(({ id, s }) => useLayoutHold(id, s), {
      initialProps: { id: 'a', s: [loading, ready(1)] as AsyncState<unknown>[] },
    });
    expect(result.current).toBe(true);
    rerender({ id: 'a', s: [unavailable, ready(1)] });
    expect(result.current).toBe(false);
    rerender({ id: 'a', s: [loading, loading] });
    expect(result.current).toBe(false);
  });

  it('resets on the identity: another identity is held until its own supporting states settle', () => {
    const { result, rerender } = renderHook(({ id, s }) => useLayoutHold(id, s), {
      initialProps: { id: 'a', s: [ready(1)] as AsyncState<unknown>[] },
    });
    expect(result.current).toBe(false);
    rerender({ id: 'b', s: [loading] });
    expect(result.current).toBe(true);
    rerender({ id: 'b', s: [ready(2)] });
    expect(result.current).toBe(false);
    // An identity whose answers are already settled (cached) is drawn at once.
    rerender({ id: 'c', s: [ready(3)] });
    expect(result.current).toBe(false);
  });

  it('holds a region\'s own ready state for its supporting states, never its failure, and draws it once per identity', () => {
    const { result, rerender } = renderHook(({ id, own, s }) => useHeldState(id, own, s), {
      initialProps: { id: 'v', own: ready(['row']) as AsyncState<string[]>, s: [loading] as AsyncState<unknown>[] },
    });
    expect(result.current).toEqual(loading);
    rerender({ id: 'v', own: unavailable, s: [loading] });
    expect(result.current).toEqual(unavailable);
    rerender({ id: 'v', own: ready(['row']), s: [ready('zone')] });
    expect(result.current).toEqual(ready(['row']));
    // Drawn: a supporting refetch with no data does not blank it.
    rerender({ id: 'v', own: ready(['row', 'row 2']), s: [loading] });
    expect(result.current).toEqual(ready(['row', 'row 2']));
    rerender({ id: 'w', own: ready(['other']), s: [loading] });
    expect(result.current).toEqual(loading);
  });

  it('is the only initial-layout latch: no surface keeps its own', () => {
    const offenders = Object.entries(features)
      .filter(([path]) => !path.includes('.test.'))
      .filter(([, source]) => /\bdrawn(?:Ref)?\s*=\s*useRef\(|\bdrawn\.current\b/.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
