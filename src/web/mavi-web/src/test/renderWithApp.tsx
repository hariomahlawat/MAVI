import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, RouterProvider, Routes, createMemoryRouter } from 'react-router-dom';
import AppShell from '../app/AppShell';
import { createMaviQueryClient, queryKeys } from '../app/queryClient';
import type { SurfaceId } from '../shared/workspace';

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
  /**
   * Renders the page inside the real shell, as the route naming this surface,
   * so what the shell derives from the page's Context Bar — the document title,
   * the rail highlight — can be asserted. Implies a data router.
   */
  shell?: SurfaceId;
};

type Rendered = ReturnType<typeof render> & { queryClient: ReturnType<typeof createMaviQueryClient> };
type DataRendered = Rendered & { router: ReturnType<typeof createMemoryRouter> };

export function renderWithApp(
  element: ReactElement,
  options: RenderOptions & ({ dataRouter: true } | { shell: SurfaceId }),
): DataRendered;
export function renderWithApp(element: ReactElement, options?: RenderOptions): Rendered;
export function renderWithApp(element: ReactElement, options: RenderOptions = {}): Rendered | DataRendered {
  const queryClient = createMaviQueryClient();
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
    mutations: { retry: false },
  });

  const route = options.route ?? '/';

  if (options.dataRouter || options.shell) {
    const page = { path: options.routePath ?? '*', element };
    if (options.shell) {
      // The shell's health probe is answered up front, so it issues no request.
      queryClient.setQueryDefaults(queryKeys.platformHealth, { staleTime: Infinity });
      queryClient.setQueryData(queryKeys.platformHealth, { status: 'Healthy', component: 'api', version: 'test' });
    }
    const router = createMemoryRouter(
      options.shell
        ? [{ path: '/', element: <AppShell />, children: [{ ...page, handle: { surface: options.shell } }] }]
        : [page],
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
