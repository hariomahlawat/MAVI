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

vi.mock('../features/cameras/CamerasPage', () => ({
  default: () => <h1>Cameras route</h1>,
}));
vi.mock('../features/video-import/VideoImportPage', () => ({
  default: () => <h1>Import route</h1>,
}));
vi.mock('../features/processing/ProcessingPage', () => ({
  default: () => <h1>Processing route</h1>,
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

describe('Task-15 application routes', () => {
  beforeEach(() => {
    vi.mocked(getPlatformHealth).mockResolvedValue({
      status: 'Healthy',
      component: 'Mavi.Api',
      version: '1.0.0',
    });
  });

  it('redirects root to Cameras and navigates to Import', async () => {
    const user = userEvent.setup();
    renderRoute('/');

    expect(await screen.findByRole('heading', { name: 'Cameras route' })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Import' }));
    expect(await screen.findByRole('heading', { name: 'Import route' })).toBeInTheDocument();
  });

  it('resolves a direct processing deep link in the client router', async () => {
    renderRoute('/processing/018f3f5a-2f70-7a2b-8a12-2d02f4c21421');
    expect(await screen.findByRole('heading', { name: 'Processing route' })).toBeInTheDocument();
  });
});
