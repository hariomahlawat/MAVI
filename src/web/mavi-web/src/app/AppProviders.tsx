import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createMaviQueryClient } from './queryClient';

const queryClient = createMaviQueryClient();

/**
 * The visual-QA harness (tools/web-visual-qa, settle.mjs) installs `window.__vqa`
 * before the application boots. Only then is the query client's own activity
 * registered on it, read-only: a query waiting out a retry's backoff has no
 * request in flight, so without it the harness would read that backoff as a
 * settled page (owner ruling 4). Nothing is registered in ordinary use.
 */
type HarnessHandle = { queryActivity?: () => { fetching: number; mutating: number } };
const harness = typeof window === 'undefined' ? undefined : (window as unknown as { __vqa?: HarnessHandle }).__vqa;
if (harness) harness.queryActivity = () => ({ fetching: queryClient.isFetching(), mutating: queryClient.isMutating() });

export default function AppProviders({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
