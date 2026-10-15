import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { registerHarnessObservability } from './harnessObservability';
import { createMaviQueryClient } from './queryClient';

const queryClient = createMaviQueryClient();

// Dormant unless the visual-QA harness preinstalled its handle (§26, amended).
registerHarnessObservability(queryClient);

export default function AppProviders({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
