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
