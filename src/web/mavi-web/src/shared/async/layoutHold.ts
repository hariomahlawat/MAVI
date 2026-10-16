import { useRef } from 'react';
import { holdUntilSettled, type AsyncState } from './asyncState';

/**
 * The shared layout hold (§38, X3 determinism; owner review 2026-10-14).
 *
 * A region, or a whole surface, is drawn once its supporting answers have
 * settled (answered or failed), so it goes from its loading presentation to
 * its final layout once, whatever order the answers arrive in. Once drawn it
 * stays drawn — a later refetch updates it in place and never blanks it back
 * to loading — **for that identity only**: the surface's identity (the camera,
 * the video the route names) is part of the hold, so a same-route change to
 * another identity is held again until the new identity's own supporting
 * answers have settled, instead of inheriting the previous identity's drawing.
 *
 * Settledness is read from the normalised AsyncState boundary
 * (`fromQuery(...)`), never from a data source's own flags: a supporting state
 * has settled when it is not `loading`. A supporting answer that does not apply
 * (a disabled query) is left out of the list by the caller, since a disabled
 * query with no data reads as loading forever.
 */
export function settled(supporting: readonly AsyncState<unknown>[]): boolean {
  return supporting.every((state) => state.kind !== 'loading');
}

/**
 * Whether the surface for `identity` is still held: true until every
 * supporting state has settled for this identity, then false for as long as
 * the identity stays the same; true again when it changes, until the new
 * identity's supporting states have settled.
 */
export function useLayoutHold(identity: string, supporting: readonly AsyncState<unknown>[]): boolean {
  const drawnFor = useRef<string | null>(null);
  if (settled(supporting)) drawnFor.current = identity;
  return drawnFor.current !== identity;
}

/**
 * A region's own state, held (`holdUntilSettled`) until its supporting states
 * have settled, then drawn once for this identity: a refetch of the drawn
 * region is shown as itself, never held again. A region whose own request
 * failed is not held (its failure is its content).
 */
export function useHeldState<T>(identity: string, state: AsyncState<T>, supporting: readonly AsyncState<unknown>[]): AsyncState<T> {
  const drawnFor = useRef<string | null>(null);
  const held = holdUntilSettled(state, settled(supporting));
  if (held.kind !== 'loading') drawnFor.current = identity;
  return drawnFor.current === identity ? state : held;
}
