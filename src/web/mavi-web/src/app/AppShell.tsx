import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { getPlatformHealth } from '../api/platform';
import Icon, { type IconName } from '../shared/components/Icon';
import { queryKeys } from './queryClient';

type NavItem = { to: string; label: string; icon: IconName; end?: boolean };

// Primary navigation follows the operator workflow left to right: know what
// you have, bring media in, watch it process, then search and review.
export const primaryNavigation: NavItem[] = [
  { to: '/', label: 'Overview', icon: 'overview', end: true },
  { to: '/cameras', label: 'Cameras', icon: 'camera' },
  { to: '/videos', label: 'Videos', icon: 'video' },
  { to: '/import', label: 'Import', icon: 'upload' },
  { to: '/processing', label: 'Processing', icon: 'activity' },
  { to: '/search', label: 'Search', icon: 'search' },
];

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
          {primaryNavigation.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} title={collapsed ? item.label : undefined}>
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
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

      <div className="content">
        <header className="topbar">
          <div className="topbar__crumbs">
            <strong>{sectionTitleFor(location.pathname)}</strong>
          </div>
          <div className="topbar__spacer" />
        </header>
        <main className="main" id="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
