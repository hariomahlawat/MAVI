import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { getPlatformHealth } from '../api/platform';
import Icon, { type IconName } from '../shared/components/Icon';
import { Breadcrumbs, SurfaceSlotProvider } from '../shared/workspace';
import { queryKeys } from './queryClient';

type NavItem = { to: string; label: string; icon: IconName; end?: boolean };

type NavGroup = { label: string; items: NavItem[] };

/**
 * Navigation grouped per section 5, ordered by operator workflow rather than
 * alphabetically: know what you have, bring media in, watch it process, then
 * investigate what came out.
 *
 * Section 5 also says an item is added only when its destination exists, so
 * Investigate holds Search alone. Events, Entities and Cases belong to it and
 * are deliberately absent until they are real routes.
 */
export const navigationGroups: NavGroup[] = [
  {
    label: 'Operate',
    items: [
      { to: '/', label: 'Overview', icon: 'overview', end: true },
      { to: '/cameras', label: 'Cameras', icon: 'camera' },
      { to: '/videos', label: 'Videos', icon: 'video' },
      { to: '/import', label: 'Import', icon: 'upload' },
      { to: '/processing', label: 'Processing', icon: 'activity' },
    ],
  },
  {
    label: 'Investigate',
    items: [
      { to: '/search', label: 'Search', icon: 'search' },
    ],
  },
];

/** Flattened, for callers that only care about the destinations themselves. */
export const primaryNavigation: NavItem[] = navigationGroups.flatMap((group) => group.items);

const sectionTitles: Array<[RegExp, string]> = [
  [/^\/review\//, 'Review'],
  [/^\/processing\/./, 'Processing'],
  [/^\/processing$/, 'Processing'],
  [/^\/search/, 'Search'],
  [/^\/videos/, 'Videos'],
  [/^\/cameras/, 'Cameras'],
  [/^\/import/, 'Import'],
  [/^\/$/, 'Overview'],
];

export function sectionTitleFor(pathname: string): string {
  const match = sectionTitles.find(([pattern]) => pattern.test(pathname));
  return match ? match[1] : 'MAVI';
}

const collapseKey = 'mavi.sidebar.collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(collapseKey) === '1';
  } catch {
    return false;
  }
}

export default function AppShell() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => {
    try {
      window.localStorage.setItem(collapseKey, collapsed ? '1' : '0');
    } catch {
      // A blocked store only loses the preference; the shell still works.
    }
  }, [collapsed]);

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

  return (
    <div className={collapsed ? 'shell shell--collapsed' : 'shell'}>
      <aside className="sidebar" aria-label="Primary">
        <div className="sidebar__brand">
          <span className="brand-mark" aria-hidden="true">M</span>
          <div>
            <strong>MAVI</strong>
            <span>Visual Intelligence</span>
          </div>
        </div>
        <nav className="sidebar__nav" aria-label="Primary navigation">
          {navigationGroups.map((group) => (
            <div className="sidebar__group" key={group.label} role="group" aria-label={group.label}>
              {/* Hidden when collapsed, so the group label is kept for
                  assistive technology rather than lost with the width. */}
              <p className="sidebar__section" aria-hidden="true">{group.label}</p>
              {group.items.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end} title={collapsed ? item.label : undefined}>
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
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
          <button
            type="button"
            className="btn btn--ghost btn--sm sidebar__toggle"
            onClick={() => setCollapsed((value) => !value)}
            aria-pressed={collapsed}
            aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
            title={collapsed ? 'Expand navigation' : 'Collapse navigation'}
          >
            <Icon name="sidebar" size="sm" />
          </button>
        </div>
      </aside>

      <SurfaceSlotProvider>
        {(attachContextBar, claimed) => (
          <div className="content">
            {/* Section 5: the topbar *is* the Context Bar. One band, filled by
                the surface through <ContextBar>; a surface that has not been
                migrated onto an archetype yet leaves the section name it has
                always shown. */}
            <header className="context-bar" ref={attachContextBar}>
              {claimed ? null : (
                <Breadcrumbs crumbs={[{ label: sectionTitleFor(location.pathname) }]} />
              )}
            </header>
            <main className="main" id="main">
              <Outlet />
            </main>
          </div>
        )}
      </SurfaceSlotProvider>
    </div>
  );
}
