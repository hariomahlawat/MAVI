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

export const loading = (): AsyncState<never> => ({ kind: 'loading' });

export const unavailable = (error: unknown): AsyncState<never> => ({ kind: 'unavailable', error });

export function ready<T>(data: T, degradedError?: unknown): AsyncState<T> {
  return degradedError === undefined
    ? { kind: 'ready', data }
    : { kind: 'ready', data, degraded: { error: degradedError } };
}

/** Map the payload of a ready state, leaving loading and unavailable untouched. */
export function mapAsync<T, U>(state: AsyncState<T>, project: (data: T) => U): AsyncState<U> {
  if (state.kind !== 'ready') return state;
  return state.degraded === undefined
    ? { kind: 'ready', data: project(state.data) }
    : { kind: 'ready', data: project(state.data), degraded: state.degraded };
}

/**
 * Combine two states for a surface that cannot render until both have arrived.
 * Unavailable wins over loading: a surface that is partly broken is not still
 * loading, and pretending otherwise is how a failure becomes a spinner forever.
 */
export function combineAsync<A, B>(a: AsyncState<A>, b: AsyncState<B>): AsyncState<[A, B]> {
  if (a.kind === 'unavailable') return a;
  if (b.kind === 'unavailable') return b;
  if (a.kind === 'loading' || b.kind === 'loading') return { kind: 'loading' };
  const degraded = a.degraded ?? b.degraded;
  return degraded === undefined
    ? { kind: 'ready', data: [a.data, b.data] }
    : { kind: 'ready', data: [a.data, b.data], degraded };
}
