import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, RouterProvider, Routes, createMemoryRouter } from 'react-router-dom';
import { createMaviQueryClient } from '../app/queryClient';

type RenderOptions = {
  route?: string;
  routePath?: string;
  /**
   * Renders through a data router, as the application itself does.
   *
   * Needed by pages that use the data-router APIs, such as `useBlocker` for
   * unsaved-changes protection; those hooks refuse to run under the plain
   * `MemoryRouter` the other pages are rendered with.
   */
  dataRouter?: boolean;
};

export function renderWithApp(element: ReactElement, options: RenderOptions = {}) {
  const queryClient = createMaviQueryClient();
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
    mutations: { retry: false },
  });

  const route = options.route ?? '/';

  if (options.dataRouter) {
    const router = createMemoryRouter(
      [{ path: options.routePath ?? '*', element }],
      { initialEntries: [route] },
    );
    return {
      queryClient,
      router,
      ...render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>,
      ),
    };
  }

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
