import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createMaviQueryClient } from './queryClient';

const queryClient = createMaviQueryClient();

export default function AppProviders({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
