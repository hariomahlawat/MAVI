import { useQuery } from '@tanstack/react-query';
import { NavLink, Outlet } from 'react-router-dom';
import { getPlatformHealth } from '../api/platform';
import { queryKeys } from './queryClient';

export default function AppShell() {
  const health = useQuery({
    queryKey: queryKeys.platformHealth,
    queryFn: ({ signal }) => getPlatformHealth(signal),
    retry: 1,
    refetchInterval: 30_000,
  });

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">M</span>
          <div>
            <strong>MAVI</strong>
            <span>Mission-Aware Visual Intelligence</span>
          </div>
        </div>
        <nav className="primary-nav" aria-label="Primary navigation">
          <NavLink to="/cameras">Cameras</NavLink>
          <NavLink to="/import">Import</NavLink>
          <NavLink to="/search">Search</NavLink>
        </nav>
        <div className="api-health" role="status" aria-live="polite">
          <span
            className={`status-dot ${health.isSuccess ? 'status-dot--ok' : health.isError ? 'status-dot--error' : 'status-dot--pending'}`}
            aria-hidden="true"
          />
          {health.isSuccess
            ? `${health.data.status} · ${health.data.version}`
            : health.isError
              ? 'API unavailable'
              : 'Checking API'}
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
