/**
 * The normalized async state every surface renders through.
 *
 * Section 14.1 of the UI/UX specification states the intent absolutely:
 * unavailable must never silently become empty. The union below is how that is
 * enforced rather than merely intended — `data` exists only on the `ready`
 * variant, so a call site cannot reach for it after a failure and read
 * "undefined" as "the server has nothing". There is no state in which a caller
 * holds both a failure and an apparently empty result.
 *
 * Nothing here knows about TanStack Query, or about any other data source.
 * The adapters live beside this file; presentational code imports only this.
 */

export type AsyncState<T> =
  | { readonly kind: 'loading' }
  | { readonly kind: 'unavailable'; readonly error: unknown }
  /**
   * The request succeeded. `degraded` is present when a later refetch failed
   * while this data was already on screen: the data is real but no longer known
   * to be current, which is a different thing from having no data at all.
   */
  | { readonly kind: 'ready'; readonly data: T; readonly degraded?: { readonly error: unknown } };

/**
 * One region that depends on two requests is one region, not two: it loads
 * until both have answered, it is unavailable if either failed before
 * answering, and it is degraded if either failed after answering. The first
 * failure wins, so the region reports one cause and offers one retry.
 */
export function combineStates<A, B>(a: AsyncState<A>, b: AsyncState<B>): AsyncState<readonly [A, B]> {
  if (a.kind === 'unavailable') return a;
  if (b.kind === 'unavailable') return b;
  if (a.kind === 'loading' || b.kind === 'loading') return { kind: 'loading' };
  const degraded = a.degraded ?? b.degraded;
  return degraded
    ? { kind: 'ready', data: [a.data, b.data] as const, degraded }
    : { kind: 'ready', data: [a.data, b.data] as const };
}

/** Whether a request has anything to report: a first-load failure, or a failed refresh of data on screen. */
export function hasFailure<T>(state: AsyncState<T>): boolean {
  return state.kind === 'unavailable' || (state.kind === 'ready' && state.degraded !== undefined);
}

/**
 * A region is content only once every answer that decides its final layout
 * has arrived (§38, X3 determinism review 2026-10-13). A Ledger's rows are
 * laid out by more than their own request: the display timezone formats their
 * timestamps, camera metadata names their cameras, a row's run lookup adds its
 * progress or failure detail. Drawn before those answers, the rows are drawn
 * twice — first in a provisional layout (an explicit-UTC timestamp, a camera
 * identifier, a status line without its run) and then in the final one — and
 * the second drawing moves every row beneath. Held in its loading presentation
 * until the supporting answers have *settled* (answered or failed), the region
 * goes from loading to its final layout once, whatever order the answers
 * arrive in. A supporting failure is not the region's: it settles the hold
 * and is reported by its own notice, as before.
 */
export function holdUntilSettled<T>(state: AsyncState<T>, supportingSettled: boolean): AsyncState<T> {
  return state.kind === 'ready' && !supportingSettled ? { kind: 'loading' } : state;
}
