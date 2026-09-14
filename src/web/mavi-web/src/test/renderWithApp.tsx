import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { createMaviQueryClient } from '../app/queryClient';

type RenderOptions = {
  route?: string;
  routePath?: string;
};

export function renderWithApp(element: ReactElement, options: RenderOptions = {}) {
  const queryClient = createMaviQueryClient();
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
    mutations: { retry: false },
  });

  const route = options.route ?? '/';
  const content = options.routePath
    ? <Routes><Route path={options.routePath} element={element} /></Routes>
    : element;

  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{content}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}
