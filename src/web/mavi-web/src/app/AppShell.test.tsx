import { SEARCH_SHORTCUTS } from '../features/visual-search/searchShortcuts';
import { QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useState } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getPlatformHealth } from '../api/platform';
import { SHELL_QUERIES } from '../shared/overlay/useMediaQuery';
import { DESTINATIONS, ownerOf, type SurfaceId } from '../shared/workspace';
import { stubMatchMedia, stubMatchMediaLive } from '../test/matchMedia';
import { createMaviQueryClient } from './queryClient';
import { appRoutes } from './router';
import { CHORD_TIMEOUT_MS } from './useGlobalShortcuts';

vi.mock('../api/platform', () => ({ getPlatformHealth: vi.fn() }));

// Pages are stand-ins: the shell is under test. Most publish nothing, so the
// shell's own IA-derived crumb and title are what is asserted; Scene publishes
// a Context Bar whose camera identity arrives late, as a real one does.
vi.mock('../features/overview/OverviewPage', () => ({
  default: () => (
    <div>
      <h2>Overview route</h2>
      <button type="button">Overview action</button>
      <input aria-label="Filter" />
      <textarea aria-label="Note" />
      <select aria-label="Choice"><option>one</option></select>
      <div contentEditable suppressContentEditableWarning aria-label="Editable">editable</div>
    </div>
  ),
}));
vi.mock('../features/cameras/CamerasPage', () => ({ default: () => <h2>Cameras route</h2> }));
vi.mock('../features/videos/VideosPage', () => ({ default: () => <h2>Videos route</h2> }));
vi.mock('../features/processing/ProcessingQueuePage', () => ({ default: () => <h2>Processing queue route</h2> }));
vi.mock('../features/video-import/VideoImportPage', () => ({ default: () => <h2>Import route</h2> }));
vi.mock('../features/processing/ProcessingPage', () => ({ default: () => <h2>Processing route</h2> }));
vi.mock('../features/visual-search/VisualSearchPage', () => ({ default: () => <h2>Search route</h2> }));
vi.mock('../features/video-review/VideoReviewPage', () => ({ default: () => <h2>Review route</h2> }));
vi.mock('../features/analytics/AnalyticsPage', () => ({ default: () => <h2>Analytics route</h2> }));
vi.mock('../features/scene-editor/SceneEditorPage', async () => {
  const { ContextBar } = await import('../shared/workspace');
  function Scene() {
    const [name, setName] = useState<string | null>(null);
    // The camera arrives when the test says so, as a request completing would.
    useEffect(() => {
      const arrive = () => setName('CAM-01 · North Gate');
      window.addEventListener('test:camera-arrives', arrive);
      return () => window.removeEventListener('test:camera-arrives', arrive);
    }, []);
    return (
      <>
        <ContextBar surface="scene" object={name ? { label: name } : undefined} />
        <h2>Scene route</h2>
      </>
    );
  }
  return { default: Scene };
});

const CAMERA = '018f3f5a-2f70-7a2b-8a12-2d02f4c21412';
const VIDEO = '018f3f5a-2f70-7a2b-8a12-2d02f4c21421';

function renderAt(path: string) {
  const queryClient = createMaviQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false } });
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router };
}

const rail = () => screen.getByRole('navigation', { name: 'Primary' });
const crumbs = () => screen.getByRole('navigation', { name: 'Breadcrumb' });
const activeRailItems = () => within(rail()).getAllByRole('link').filter((link) => link.classList.contains('active'));

beforeEach(() => {
  vi.mocked(getPlatformHealth).mockResolvedValue({ status: 'Healthy', component: 'Mavi.Api', version: '1.0.0' });
  window.localStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe('the shell derives its IA from one map (§5)', () => {
  const routes: Array<[string, SurfaceId, string]> = [
    ['/', 'overview', 'Overview route'],
    ['/cameras', 'cameras', 'Cameras route'],
    [`/cameras/${CAMERA}/scene`, 'scene', 'Scene route'],
    [`/cameras/${CAMERA}/analytics`, 'analytics', 'Analytics route'],
    ['/videos', 'videos', 'Videos route'],
    ['/import', 'import', 'Import route'],
    ['/processing', 'processing', 'Processing queue route'],
    [`/processing/${VIDEO}`, 'processing-detail', 'Processing route'],
    ['/search', 'search', 'Search route'],
    [`/review/video/${VIDEO}?trackId=${VIDEO}`, 'review', 'Review route'],
  ];

  it.each(routes)('%s highlights exactly its owning rail item, whose label is its root crumb', async (path, surface, heading) => {
    renderAt(path);
    await screen.findByRole('heading', { name: heading });
    const owner = ownerOf(surface)!;
    const active = activeRailItems();
    expect(active).toHaveLength(1);
    expect(active[0]).toHaveTextContent(owner.label);
    // The root surface is the page; a child surface marks its owner current within the set.
    expect(active[0]).toHaveAttribute('aria-current', surface === owner.id ? 'page' : 'true');
    expect(within(crumbs()).getAllByRole('listitem')[0]).toHaveTextContent(owner.label);
  });

  it('owns Scene and Analytics by Cameras and Review by Search', async () => {
    const scene = renderAt(`/cameras/${CAMERA}/scene`);
    await screen.findByRole('heading', { name: 'Scene route' });
    expect(activeRailItems()[0]).toHaveTextContent('Cameras');
    scene.unmount();
    renderAt(`/review/video/${VIDEO}?trackId=${VIDEO}`);
    await screen.findByRole('heading', { name: 'Review route' });
    expect(activeRailItems()[0]).toHaveTextContent('Search');
  });

  it('renders Not found inside the shell with no rail item highlighted — even under an owned path', async () => {
    for (const path of ['/nowhere', `/cameras/${CAMERA}/unknown`]) {
      const view = renderAt(path);
      await screen.findByRole('heading', { name: 'Not found', level: 1 });
      expect(activeRailItems()).toHaveLength(0);
      expect(within(rail()).queryAllByRole('link', { current: true })).toHaveLength(0);
      expect(within(crumbs()).getByText('Not found')).toHaveAttribute('aria-current', 'page');
      await waitFor(() => expect(document.title).toBe('Not found — MAVI'));
      view.unmount();
    }
  });

  it('lists the rail in the map order, grouped Operate and Investigate', async () => {
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    expect(within(rail()).getAllByRole('link').map((link) => link.textContent)).toEqual(DESTINATIONS.map((entry) => entry.label));
    expect(within(rail()).getAllByRole('group').map((group) => group.getAttribute('aria-label'))).toEqual(['Operate', 'Investigate']);
  });
});

describe('document title (§5, §37.1 long names)', () => {
  it('derives the title from the same map, root surfaces included', async () => {
    renderAt('/videos');
    await screen.findByRole('heading', { name: 'Videos route' });
    await waitFor(() => expect(document.title).toBe('Videos — MAVI'));
  });

  it('carries the full dynamic identity once it resolves, and no stale title on the way out', async () => {
    const user = userEvent.setup();
    renderAt(`/cameras/${CAMERA}/scene`);
    await screen.findByRole('heading', { name: 'Scene route' });
    // Before the camera arrives: the surface and its section, no invented name.
    await waitFor(() => expect(document.title).toBe('Scene — Cameras — MAVI'));
    act(() => { window.dispatchEvent(new Event('test:camera-arrives')); });
    await waitFor(() => expect(document.title).toBe('Scene — CAM-01 · North Gate — Cameras — MAVI'));

    await user.click(within(rail()).getByRole('link', { name: 'Videos' }));
    await screen.findByRole('heading', { name: 'Videos route' });
    await waitFor(() => expect(document.title).toBe('Videos — MAVI'));
    expect(document.title).not.toContain('CAM-01');
  });
});

describe('rail collapse control (§5)', () => {
  it('is a named 32px-metric control that announces the rail state and persists the choice', async () => {
    const user = userEvent.setup();
    const first = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    const toggle = screen.getByRole('button', { name: 'Collapse navigation' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(toggle).toHaveAttribute('aria-controls', rail().id);
    expect(toggle).not.toHaveAttribute('title');
    expect(toggle).toHaveClass('sidebar__toggle');

    await user.click(toggle);
    const expand = screen.getByRole('button', { name: 'Expand navigation' });
    expect(expand).toHaveAttribute('aria-expanded', 'false');
    expect(window.localStorage.getItem('mavi.sidebar.collapsed')).toBe('1');
    first.unmount();

    // A new session keeps the operator's choice.
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    expect(screen.getByRole('button', { name: 'Expand navigation' })).toHaveAttribute('aria-expanded', 'false');
  });
});

describe('Tier B rail (§25: collapsed by default, an overlay when opened)', () => {
  let unstub: () => void = () => {};
  beforeEach(() => {
    // Compact width: only the shell's Tier B query matches.
    unstub = stubMatchMedia((query) => query === SHELL_QUERIES.compact);
  });
  afterEach(() => unstub());

  it('is collapsed by default whatever the workstation preference, and keeps that preference', async () => {
    window.localStorage.setItem('mavi.sidebar.collapsed', '0');
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });

    const toggle = screen.getByRole('button', { name: 'Open navigation' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveAttribute('aria-controls', rail().id);
    expect(document.querySelector('.shell')).toHaveClass('shell--compact', 'shell--collapsed');
    // The operator's Tier A choice is not overwritten by the compact default.
    expect(window.localStorage.getItem('mavi.sidebar.collapsed')).toBe('0');
  });

  it('opens as a named modal overlay over an inert workspace, contains Tab, and closes on Escape with focus restored', async () => {
    const user = userEvent.setup();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    const toggle = screen.getByRole('button', { name: 'Open navigation' });

    await user.click(toggle);
    const overlay = screen.getByRole('dialog', { name: 'Navigation' });
    expect(overlay).toHaveAttribute('aria-modal', 'true');
    expect(overlay).toContainElement(rail());
    expect(document.activeElement).toHaveTextContent('Navigation');
    expect(document.getElementById('main')).toHaveAttribute('inert');
    expect(screen.getByRole('button', { name: 'Close navigation' })).toHaveAttribute('aria-expanded', 'true');

    // Tab cycles inside the overlay only.
    for (let step = 0; step < 16; step += 1) {
      await user.tab();
      expect(overlay).toContainElement(document.activeElement as HTMLElement);
    }

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
    expect(document.getElementById('main')).not.toHaveAttribute('inert');
    expect(screen.getByRole('button', { name: 'Open navigation' })).toHaveFocus();
  });

  it('lets no global shortcut act behind the open overlay', async () => {
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.click(screen.getByRole('button', { name: 'Open navigation' }));

    await user.keyboard('gc');
    expect(router.state.location.pathname).toBe('/');
    expect(screen.getByRole('dialog', { name: 'Navigation' })).toBeInTheDocument();
  });

  it('closes when a destination is chosen from it', async () => {
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.click(screen.getByRole('button', { name: 'Open navigation' }));

    await user.click(within(rail()).getByRole('link', { name: 'Cameras' }));
    await screen.findByRole('heading', { name: 'Cameras route' });
    expect(router.state.location.pathname).toBe('/cameras');
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
    expect(document.getElementById('main')).not.toHaveAttribute('inert');
  });

  it('never writes the workstation preference from the compact toggle', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('mavi.sidebar.collapsed', '1');
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.click(screen.getByRole('button', { name: 'Open navigation' }));
    await user.keyboard('{Escape}');
    expect(window.localStorage.getItem('mavi.sidebar.collapsed')).toBe('1');
  });
});

describe('Tier C navigation (§25: a top-of-page menu control opening an overlay)', () => {
  const tierC = (query: string) => query === SHELL_QUERIES.compact || query === SHELL_QUERIES.narrow;
  const tierB = (query: string) => query === SHELL_QUERIES.compact;
  let restore: () => void = () => {};
  afterEach(() => restore());

  it('opens the same navigation from a named control leading the Context Bar, as a modal overlay, and returns focus to it on Escape', async () => {
    restore = stubMatchMedia(tierC);
    const user = userEvent.setup();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    expect(document.querySelector('.shell')).toHaveClass('shell--narrow');
    // The rail's own control is not offered at Tier C; the menu is, in the band.
    const menu = within(document.querySelector('.context-bar') as HTMLElement).getByRole('button', { name: 'Open navigation' });
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect(menu).toHaveAttribute('aria-controls', rail().id);

    await user.click(menu);
    const overlay = screen.getByRole('dialog', { name: 'Navigation' });
    expect(overlay).toContainElement(rail());
    expect(document.getElementById('main')).toHaveAttribute('inert');
    // Shift+Tab from the heading it focused stays inside (the T1 trap fix).
    await user.tab({ shift: true });
    expect(overlay).toContainElement(document.activeElement as HTMLElement);

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
    expect(document.getElementById('main')).not.toHaveAttribute('inert');
    expect(menu).toHaveFocus();
  });

  it('closes after a destination is chosen from it', async () => {
    restore = stubMatchMedia(tierC);
    const user = userEvent.setup();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.click(within(document.querySelector('.context-bar') as HTMLElement).getByRole('button', { name: 'Open navigation' }));
    await user.click(within(rail()).getByRole('link', { name: /Cameras/ }));
    await screen.findByRole('heading', { name: 'Cameras route' });
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
  });

  it('closes an overlay open across 768px and puts focus on the control the new tier offers — never on its hidden heading (T1 carry-over)', async () => {
    const live = stubMatchMediaLive(tierB);
    restore = live.restore;
    const user = userEvent.setup();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    // Open at Tier B from the rail's toggle; cross into Tier C.
    await user.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(document.activeElement).toHaveTextContent('Navigation');
    live.set(tierC);
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
    expect(document.getElementById('main')).not.toHaveAttribute('inert');
    const menu = within(document.querySelector('.context-bar') as HTMLElement).getByRole('button', { name: 'Open navigation' });
    expect(menu).toHaveFocus();

    // Open at Tier C from the menu; cross back into Tier B.
    await user.click(menu);
    live.set(tierB);
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
    expect(document.querySelector('.context-bar .shell__menu')).toBeNull();
    expect(document.querySelector('.sidebar__toggle')).toHaveFocus();
  });

  it('leads the Context Bar with the menu control in the document, not only on screen, when the window narrows live (T3)', async () => {
    // A live crossing — a resize, or 200% page zoom pressed on a page in use —
    // mounts the menu after the surface has published its Context Bar: the
    // keyboard must still reach the menu first, as it is drawn.
    const live = stubMatchMediaLive(tierB);
    restore = live.restore;
    renderAt(`/cameras/${CAMERA}/scene`);
    await screen.findByRole('heading', { name: 'Scene route' });
    act(() => { window.dispatchEvent(new Event('test:camera-arrives')); });
    live.set(tierC);
    const bar = document.querySelector('.context-bar') as HTMLElement;
    const menu = within(bar).getByRole('button', { name: 'Open navigation' });
    expect(bar.querySelector('button, a[href], [tabindex]:not([tabindex="-1"])')).toBe(menu);
    expect(menu.compareDocumentPosition(within(bar).getByRole('navigation', { name: 'Breadcrumb' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("moves focus from a closed rail's control to the menu when the window narrows, and back", () => {
    const live = stubMatchMediaLive(tierB);
    restore = live.restore;
    renderAt('/');
    const toggle = document.querySelector('.sidebar__toggle') as HTMLElement;
    toggle.focus();
    live.set(tierC);
    expect(document.querySelector('.shell__menu')).toHaveFocus();
    live.set(tierB);
    expect(document.querySelector('.sidebar__toggle')).toHaveFocus();
  });

  it('lets no global shortcut act behind the open overlay', async () => {
    restore = stubMatchMedia(tierC);
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.click(within(document.querySelector('.context-bar') as HTMLElement).getByRole('button', { name: 'Open navigation' }));
    await user.keyboard('gv');
    expect(router.state.location.pathname).toBe('/');
  });
});

describe('skip link and landmarks (§5, §23)', () => {
  it('puts the skip link first, and moves focus to the workspace', async () => {
    const user = userEvent.setup();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.tab();
    const skip = screen.getByRole('link', { name: 'Skip to workspace' });
    expect(skip).toHaveFocus();
    await user.keyboard('{Enter}');
    const main = screen.getByRole('main');
    expect(main).toHaveFocus();
    expect(main).toHaveAttribute('id', 'main');
  });

  it('has one banner (the rail head), the primary navigation, and one main', async () => {
    renderAt(`/cameras/${CAMERA}/scene`);
    await screen.findByRole('heading', { name: 'Scene route' });
    const banners = screen.getAllByRole('banner');
    expect(banners).toHaveLength(1);
    expect(banners[0]).toHaveClass('sidebar__brand');
    expect(screen.getAllByRole('main')).toHaveLength(1);
    // The Context Bar is a band inside main, not a second banner.
    expect(screen.getByRole('main').querySelector('.context-bar')).not.toBeNull();
    expect(screen.getAllByRole('navigation').map((nav) => nav.getAttribute('aria-label')).sort()).toEqual(['Breadcrumb', 'Primary']);
  });
});

describe('global keys (§5, §22)', () => {
  it.each(DESTINATIONS.map((entry) => [entry.key, entry.label, entry.to] as const))('g %s opens %s', async (key, _label, to) => {
    const user = userEvent.setup();
    const { router } = renderAt(to === '/' ? '/videos' : '/');
    await waitFor(() => expect(router.state.navigation.state).toBe('idle'));
    await user.keyboard(`g${key}`);
    await waitFor(() => expect(router.state.location.pathname).toBe(to));
  });

  it('does nothing for an incomplete chord, an unknown letter, or a letter after the chord expired', async () => {
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.keyboard('g');
    expect(router.state.location.pathname).toBe('/');
    await user.keyboard('x');
    expect(router.state.location.pathname).toBe('/');
    // The chord was spent on `x`: a destination letter now means nothing.
    await user.keyboard('c');
    expect(router.state.location.pathname).toBe('/');

    const now = Date.now();
    const clock = vi.spyOn(Date, 'now').mockReturnValue(now);
    await user.keyboard('g');
    clock.mockReturnValue(now + CHORD_TIMEOUT_MS + 1);
    await user.keyboard('c');
    expect(router.state.location.pathname).toBe('/');
  });

  it.each(['Filter', 'Note', 'Choice', 'Editable'])('never fires while typing in %s', async (name) => {
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    const field = screen.getByLabelText(name);
    field.focus();
    await user.keyboard('gc?');
    expect(router.state.location.pathname).toBe('/');
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument();
  });

  it('opens the shortcut sheet on ?, names the implemented keys, and closes on Escape with focus returned', async () => {
    const user = userEvent.setup();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    const invoker = screen.getByRole('button', { name: 'Overview action' });
    invoker.focus();
    await user.keyboard('?');

    const sheet = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(screen.getByRole('heading', { name: 'Keyboard shortcuts' })).toHaveFocus();
    for (const entry of DESTINATIONS) {
      const row = within(sheet).getByText(entry.label).closest('.shortcut-list__row') as HTMLElement;
      expect(row).toHaveTextContent(`g ${entry.key}`);
    }
    // What it covers is inert.
    expect(screen.getByRole('main', { hidden: true })).toHaveAttribute('inert');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument();
    expect(invoker).toHaveFocus();
    expect(screen.getByRole('main')).not.toHaveAttribute('inert');
  });

  it("lists the open surface's own keys in the sheet — Search's legend lives here, not in its header (§17)", async () => {
    const user = userEvent.setup();
    const first = renderAt('/search');
    await screen.findByRole('heading', { name: 'Search route' });
    await user.keyboard('?');
    const sheet = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(sheet).getByRole('heading', { name: 'Search results' })).toBeInTheDocument();
    for (const shortcut of SEARCH_SHORTCUTS) {
      const row = within(sheet).getByText(shortcut.description).closest('.shortcut-list__row') as HTMLElement;
      for (const key of shortcut.keys) expect(within(row).getByText(key, { selector: 'kbd' })).toBeInTheDocument();
    }
    first.unmount();

    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.keyboard('?');
    const elsewhere = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(elsewhere).queryByRole('heading', { name: 'Search results' })).not.toBeInTheDocument();
  });

  it('keeps focus inside the sheet, and lets no surface shortcut act behind it', async () => {
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    const surfaceKeys = vi.fn();
    window.addEventListener('keydown', surfaceKeys);
    try {
      await user.keyboard('?');
      const sheet = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
      for (let index = 0; index < 4; index += 1) {
        await user.tab();
        expect(sheet.contains(document.activeElement)).toBe(true);
      }
      surfaceKeys.mockClear();
      await user.keyboard('jkgc');
      expect(surfaceKeys).not.toHaveBeenCalled();
      expect(router.state.location.pathname).toBe('/');
    } finally {
      window.removeEventListener('keydown', surfaceKeys);
    }
  });

  it("lets no key reach the surface after a click on the sheet's plain text", async () => {
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    const surfaceKeys = vi.fn();
    window.addEventListener('keydown', surfaceKeys);
    try {
      await user.keyboard('?');
      const sheet = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
      // A click on text focuses the panel itself, outside any inner wrapper.
      await user.click(within(sheet).getByText('Shortcuts do nothing while you are typing in a field.'));
      surfaceKeys.mockClear();
      await user.keyboard('{Delete}{ArrowLeft}jgc');
      expect(surfaceKeys).not.toHaveBeenCalled();
      expect(router.state.location.pathname).toBe('/');
      expect(sheet).toBeInTheDocument();
    } finally {
      window.removeEventListener('keydown', surfaceKeys);
    }
  });

  it('spends the chord on a key a surface consumed: g, then a consumed j, then v does not navigate', async () => {
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    const button = screen.getByRole('button', { name: 'Overview action' });
    button.addEventListener('keydown', (event) => { if (event.key === 'j') event.preventDefault(); });
    button.focus();
    await user.keyboard('gjv');
    expect(router.state.location.pathname).toBe('/');
  });

  it('names the collapsed control by a hint as well as its accessible name', async () => {
    const user = userEvent.setup();
    renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    await user.click(screen.getByRole('button', { name: 'Collapse navigation' }));
    const expand = screen.getByRole('button', { name: 'Expand navigation' });
    expect(expand).toHaveAccessibleDescription('Expand navigation');
  });

  it('does not navigate behind an open modal overlay', async () => {
    const user = userEvent.setup();
    const { router } = renderAt('/');
    await screen.findByRole('heading', { name: 'Overview route' });
    const modal = document.createElement('div');
    modal.setAttribute('aria-modal', 'true');
    document.body.appendChild(modal);
    try {
      await user.keyboard('gc');
      expect(router.state.location.pathname).toBe('/');
    } finally {
      modal.remove();
    }
  });
});
