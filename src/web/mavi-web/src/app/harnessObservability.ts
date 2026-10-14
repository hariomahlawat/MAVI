import type { QueryClient } from '@tanstack/react-query';

/**
 * Harness-only passive observability (UI spec §26, amended 2026-10-14).
 *
 * The visual-QA harness (tools/web-visual-qa, settle.mjs) installs
 * `window.__vqa` before the application's first script runs. Only when that
 * handle already exists is anything registered on it: one read-only function
 * that answers how many queries are fetching (a query waiting out a retry's
 * backoff counts: it has no request in flight, so the harness's network view
 * alone reads that backoff as a settled page) and how many mutations are
 * running. Its restrictions are the spec's, and harnessObservability.test.ts
 * binds them:
 * - dormant in normal operation: with no preinstalled handle, nothing is
 *   created, registered or subscribed;
 * - counts only: two integers, never a query key, a payload or a client;
 * - no write path: it reads `isFetching()`/`isMutating()` and nothing else, so
 *   it cannot alter rendering, query configuration or scheduling;
 * - activated only by the harness's own handle, never by the application.
 * It is not a test API and is not to be generalised into one.
 */
export type QueryActivity = Readonly<{ fetching: number; mutating: number }>;
type HarnessHandle = { queryActivity?: () => QueryActivity };

export function registerHarnessObservability(queryClient: QueryClient, win: unknown = typeof window === 'undefined' ? undefined : window): void {
  const handle = (win as { __vqa?: unknown } | undefined)?.__vqa;
  if (!handle || typeof handle !== 'object') return;
  (handle as HarnessHandle).queryActivity = () =>
    Object.freeze({ fetching: queryClient.isFetching(), mutating: queryClient.isMutating() });
}
