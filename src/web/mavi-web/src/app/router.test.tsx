import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getPlatformHealth } from '../api/platform';
import { createMaviQueryClient } from './queryClient';
import { appRoutes } from './router';

vi.mock('../api/platform', () => ({
  getPlatformHealth: vi.fn(),
}));

vi.mock('../features/overview/OverviewPage', () => ({
  default: () => <h1>Overview route</h1>,
}));
vi.mock('../features/cameras/CamerasPage', () => ({
  default: () => <h1>Cameras route</h1>,
}));
vi.mock('../features/videos/VideosPage', () => ({
  default: () => <h1>Videos route</h1>,
}));
vi.mock('../features/processing/ProcessingQueuePage', () => ({
  default: () => <h1>Processing queue route</h1>,
}));
vi.mock('../features/video-import/VideoImportPage', () => ({
  default: () => <h1>Import route</h1>,
}));
vi.mock('../features/processing/ProcessingPage', () => ({
  default: () => <h1>Processing route</h1>,
}));
vi.mock('../features/visual-search/VisualSearchPage', () => ({
  default: () => <h1>Search route</h1>,
}));
vi.mock('../features/video-review/VideoReviewPage', () => ({
  default: () => <h1>Review route</h1>,
}));

function renderRoute(initialEntry: string) {
  const queryClient = createMaviQueryClient();
  queryClient.setDefaultOptions({
    queries: { retry: false, refetchOnWindowFocus: false },
    mutations: { retry: false },
  });
  const router = createMemoryRouter(appRoutes, { initialEntries: [initialEntry] });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('MAVI application routes', () => {
  beforeEach(() => {
    vi.mocked(getPlatformHealth).mockResolvedValue({
      status: 'Healthy',
      component: 'Mavi.Api',
      version: '1.0.0',
    });
  });

  it('renders the Overview at root and navigates through the primary navigation', async () => {
    const user = userEvent.setup();
    renderRoute('/');

    expect(await screen.findByRole('heading', { name: 'Overview route' })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Cameras' }));
    expect(await screen.findByRole('heading', { name: 'Cameras route' })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Videos' }));
    expect(await screen.findByRole('heading', { name: 'Videos route' })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Processing' }));
    expect(await screen.findByRole('heading', { name: 'Processing queue route' })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Import' }));
    expect(await screen.findByRole('heading', { name: 'Import route' })).toBeInTheDocument();
  });

  it('renders a not-found page for unknown routes', async () => {
    renderRoute('/nowhere');
    expect(await screen.findByText(/not found/i)).toBeInTheDocument();
  });

  it('resolves direct processing, Search and Review deep links in the client router', async () => {
    const processing = renderRoute('/processing/018f3f5a-2f70-7a2b-8a12-2d02f4c21421');
    expect(await screen.findByRole('heading', { name: 'Processing route' })).toBeInTheDocument();
    processing.unmount();

    const search = renderRoute('/search?objectClass=Person');
    expect(await screen.findByRole('heading', { name: 'Search route' })).toBeInTheDocument();
    search.unmount();

    renderRoute('/review/video/018f3f5a-2f70-7a2b-8a12-2d02f4c21421?trackId=018f3f5a-2f70-7a2b-8a12-2d02f4c21451');
    expect(await screen.findByRole('heading', { name: 'Review route' })).toBeInTheDocument();
  });

  it('navigates to Search from the primary navigation', async () => {
    const user = userEvent.setup();
    renderRoute('/cameras');

    await user.click(screen.getByRole('link', { name: 'Search' }));

    expect(await screen.findByRole('heading', { name: 'Search route' })).toBeInTheDocument();
  });
});
