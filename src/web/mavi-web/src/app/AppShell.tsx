import { useQuery } from '@tanstack/react-query';
import { useEffect, useId, useLayoutEffect, useRef, useState, type MouseEvent } from 'react';
import { Link, Outlet, useMatches, useNavigate } from 'react-router-dom';
import { getPlatformHealth } from '../api/platform';
import Icon from '../shared/components/Icon';
import Drawer from '../shared/overlay/Drawer';
import Tooltip from '../shared/overlay/Tooltip';
import { SHELL_QUERIES, useMediaQuery } from '../shared/overlay/useMediaQuery';
import {
  barClass,
  Breadcrumbs,
  crumbsFor,
  documentTitleFor,
  ownerOf,
  SECTIONS,
  SurfaceSlotProvider,
  type SurfaceId,
} from '../shared/workspace';
import { queryKeys } from './queryClient';
import ShortcutSheet from './ShortcutSheet';
import { useGlobalShortcuts } from './useGlobalShortcuts';

const collapseKey = 'mavi.sidebar.collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(collapseKey) === '1';
  } catch {
    return false;
  }
}

/**
 * The surface the router has matched, as the route itself names it (`handle`).
 * The deepest match wins; a route that names nothing — the catch-all — is the
 * one surface that owns no rail item.
 */
function useCurrentSurface(): SurfaceId {
  const matches = useMatches();
  for (let index = matches.length - 1; index >= 0; index -= 1) {
    const handle = matches[index].handle as { surface?: SurfaceId } | undefined;
    if (handle?.surface) return handle.surface;
  }
  return 'not-found';
}

/**
 * The application shell (§5).
 *
 * Everything it says about where the operator is comes from the IA map
 * (`shared/workspace/ia.ts`): which rail item is highlighted, the crumb it
 * shows before a surface has published its own, and the document title when
 * none has. It holds no second table of routes or titles.
 *
 * Landmarks (§5, §23): the skip link is the first focusable element; the rail
 * head is the page's one `banner`, the rail is the primary `navigation`, and
 * the workspace — Context Bar and surface together — is the one `main`. The
 * Context Bar is deliberately a plain band rather than a `<header>`: the page
 * has one banner, and a second header-shaped landmark would be announced as
 * one by any tool that does not scope `header` to `main`.
 */
export default function AppShell() {
  const surface = useCurrentSurface();
  const owner = ownerOf(surface);
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [sheetOpen, setSheetOpen] = useState(false);
  // §25 Tier B: below the workstation width the rail is collapsed by default
  // and the toggle opens it as an overlay — the shared Drawer, so focus moves
  // in, the workspace is inert, Escape and the scrim close it and focus goes
  // back to the toggle. The operator's Tier A choice is neither read nor
  // written here: it is a preference for the workstation, and a compact window
  // keeps it for when the window is wide again.
  const compact = useMediaQuery(SHELL_QUERIES.compact);
  const narrow = useMediaQuery(SHELL_QUERIES.narrow);
  const [railOpen, setRailOpen] = useState(false);
  // Leaving the compact range closes the overlay, so it is never found open —
  // and modal — when the window comes back; so does entering the narrow shell,
  // whose rail hides its control and its labels (Tier C, S5/T2), where an open
  // overlay would be a modal of unnamed icons.
  useEffect(() => {
    if (!compact || narrow) setRailOpen(false);
  }, [compact, narrow]);
  const railCollapsed = compact ? !railOpen : collapsed;
  const railRef = useRef<HTMLDivElement | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);
  const navId = useId();

  // The operator's choice, kept across sessions and never changed by the shell
  // at Tier A (§5): there is no width at which this effect is written by
  // anything other than the control.
  useEffect(() => {
    try {
      window.localStorage.setItem(collapseKey, collapsed ? '1' : '0');
    } catch {
      // A blocked store only loses the preference; the shell still works.
    }
  }, [collapsed]);

  useGlobalShortcuts({
    // Nothing behind an open overlay answers the keyboard (§20).
    enabled: !sheetOpen && !railOpen,
    onNavigate: (to) => navigate(to),
    onOpenSheet: () => setSheetOpen(true),
  });

  const health = useQuery({
    queryKey: queryKeys.platformHealth,
    queryFn: ({ signal }) => getPlatformHealth(signal),
    retry: 1,
    refetchInterval: 30_000,
  });

  const healthTone = health.isSuccess ? 'ok' : health.isError ? 'error' : 'pending';
  const healthText = health.isSuccess
    ? `${health.data.status} · ${health.data.version}`
    : health.isError
      ? 'API unavailable'
      : 'Checking API';

  // A link's own fragment navigation moves the scroll position but, in most
  // browsers, not keyboard focus: the next Tab would start from the skip link
  // again. So the link moves focus itself.
  function skipToWorkspace(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    mainRef.current?.focus();
  }

  const collapseLabel = compact
    ? (railOpen ? 'Close navigation' : 'Open navigation')
    : (collapsed ? 'Expand navigation' : 'Collapse navigation');

  const shellClass = ['shell', railCollapsed ? 'shell--collapsed' : '', compact ? 'shell--compact' : '', railOpen ? 'shell--rail-open' : '']
    .filter(Boolean).join(' ');

  return (
    <div className={shellClass}>
      <a className="skip-link" href="#main" onClick={skipToWorkspace}>Skip to workspace</a>

      <Drawer
        open={railOpen}
        overlay={compact}
        onClose={() => setRailOpen(false)}
        covers={[mainRef]}
        coversViewport
        className="sidebar"
        panelRef={railRef}
      >
        {/* The overlay's name (§20: an overlay is named by its heading). Only
            where the rail can be an overlay, so the workstation's outline is
            unchanged. */}
        {compact ? <h2 className="visually-hidden">Navigation</h2> : null}
        {/* The rail head is the page's banner (§5). */}
        <header className="sidebar__brand">
          <span className="brand-mark" aria-hidden="true">M</span>
          <div>
            <strong>MAVI</strong>
            <span>Visual Intelligence</span>
          </div>
        </header>
        <nav className="sidebar__nav" id={navId} aria-label="Primary">
          {SECTIONS.map((section) => (
            <div className="sidebar__group" key={section.label} role="group" aria-label={section.label}>
              {/* Hidden when collapsed, so the group label is kept for
                  assistive technology rather than lost with the width. */}
              <p className="sidebar__section" aria-hidden="true">{section.label}</p>
              {section.destinations.map((item) => {
                // Highlighted by ownership, not by path prefix: Scene and
                // Analytics are Cameras' because the map says so, Review is
                // Search's, and Not found is nobody's.
                const active = owner?.id === item.id;
                const current = active ? (surface === item.id ? 'page' : 'true') : undefined;
                return (
                  <Link
                    key={item.id}
                    to={item.to}
                    className={active ? 'active' : undefined}
                    aria-current={current}
                    // §5: the one sanctioned use of `title` — a collapsed rail item.
                    title={railCollapsed ? item.label : undefined}
                    // A destination chosen from the overlay closes it.
                    onClick={railOpen ? () => setRailOpen(false) : undefined}
                  >
                    <Icon name={item.icon} />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar__footer">
          <div className="api-health" role="status" aria-live="polite">
            <span className={`status-dot status-dot--${healthTone}`} aria-hidden="true" />
            <span className="api-health__text">
              <strong>API</strong>
              <span>{healthText}</span>
            </span>
            <span className="visually-hidden">{healthText}</span>
          </div>
          {/* §5: a labelled 32px control with a visible icon whose state is
              announced — `aria-expanded` on the navigation it controls — and
              whose name is its visible text when there is room for text. */}
          {/* Collapsed, the control is icon-only: its name is `aria-label`, and
              the same words are a hint on hover and focus (§27 Tooltip). */}
          <Tooltip content={collapseLabel} enabled={railCollapsed}>
            <button
              type="button"
              className="sidebar__toggle"
              onClick={() => (compact ? setRailOpen((open) => !open) : setCollapsed((value) => !value))}
              aria-expanded={!railCollapsed}
              aria-controls={navId}
              aria-label={railCollapsed ? collapseLabel : undefined}
            >
              <Icon name="sidebar" />
              {railCollapsed ? null : <span>{collapseLabel}</span>}
            </button>
          </Tooltip>
        </div>
      </Drawer>

      <SurfaceSlotProvider>
        {({ attachContextBar, claimed, tone, title, scroll }) => (
          <main className="content" id="main" tabIndex={-1} ref={mainRef}>
            <DocumentTitle title={title ?? documentTitleFor(crumbsFor(surface))} />
            {/* Section 5: the topbar *is* the Context Bar. One band, filled by
                the surface through <ContextBar>; a surface that publishes
                nothing — a terminal state rendered without one — shows its
                place in the IA map rather than a bare product name. */}
            <div className={barClass(tone)} ref={attachContextBar}>
              {claimed ? null : <Breadcrumbs crumbs={crumbsFor(surface)} />}
            </div>
            {/* The archetype mounted below says whether this column may scroll
                (§4). The shell applies what it is told and knows nothing about
                which surface it is. */}
            <div className="main" data-scroll={scroll}>
              <Outlet />
            </div>
          </main>
        )}
      </SurfaceSlotProvider>

      {sheetOpen ? (
        <ShortcutSheet onClose={() => setSheetOpen(false)} covers={[railRef, mainRef]} surface={surface} />
      ) : null}
    </div>
  );
}

/** The one place the document title is written (§5, §37.1 long names). */
function DocumentTitle({ title }: { title: string }) {
  // Before paint, in the same phase the Context Bar registers its title in:
  // a passive effect would leave the previous surface's title in the tab, and
  // with assistive technology, for a frame after navigating away.
  useLayoutEffect(() => {
    document.title = title;
  }, [title]);
  return null;
}
