import { useEffect, useState } from 'react';
import { getPlatformHealth, type PlatformHealth } from './api/platform';
import { getSystemConfig, type SystemConfig } from './api/system';

export default function App() {
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [, setSystemConfig] = useState<SystemConfig | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getPlatformHealth(controller.signal)
      .then((result) => setHealth(result))
      .catch(() => setUnavailable(true));
    getSystemConfig(controller.signal)
      .then(setSystemConfig)
      .catch(() => setUnavailable(true));

    return () => controller.abort();
  }, []);

  return (
    <main className="shell">
      <section className="hero" aria-labelledby="mavi-title">
        <p className="eyebrow">MISSION-AWARE VISUAL INTELLIGENCE</p>
        <h1 id="mavi-title">MAVI</h1>
        <p className="summary">
          Offline-production visual intelligence platform. Repository bootstrap only — CCTV analytics are intentionally not implemented yet.
        </p>
        <div className="status" role="status">
          <span className={`indicator ${health ? 'ready' : unavailable ? 'unavailable' : 'checking'}`} />
          {health
            ? `${health.component} ${health.version} — ${health.status}`
            : unavailable
              ? 'Operational API unavailable'
              : 'Checking operational API…'}
        </div>
      </section>
    </main>
  );
}
