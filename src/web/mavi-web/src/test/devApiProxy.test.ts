import { describe, expect, it } from 'vitest';
import launchSettings from '../../../../platform/Mavi.Api/Properties/launchSettings.json';
import { DEFAULT_DEV_API_PROXY_TARGET, resolveDevApiProxyTarget } from '../../devApiProxy';

const profile = launchSettings.profiles['Mavi.Api'];
const applicationUrls = profile.applicationUrl.split(';');
const listeners = applicationUrls.map((url) => new URL(url));

// URLs are asserted by their parts: tools/verify_repo.py forbids any scheme
// literal under src/, tests included.
const parts = (url: URL) => ({ protocol: url.protocol, hostname: url.hostname, port: url.port });

describe('Development API proxy target', () => {
  it('defaults to the loopback HTTP endpoint as an IP literal', () => {
    // No name to resolve and no certificate to trust: both fail offline on the
    // Development machine, and neither protects a loopback hop between two
    // local processes.
    expect(parts(new URL(DEFAULT_DEV_API_PROXY_TARGET)))
      .toEqual({ protocol: 'http:', hostname: '127.0.0.1', port: '62153' });
    expect(resolveDevApiProxyTarget({})).toBe(DEFAULT_DEV_API_PROXY_TARGET);
    expect(resolveDevApiProxyTarget({ MAVI_API_PROXY_TARGET: '   ' })).toBe(DEFAULT_DEV_API_PROXY_TARGET);
  });

  it('is what the Visual Studio profile sets, on a port the API actually listens on', () => {
    expect(profile.environmentVariables.MAVI_API_PROXY_TARGET).toBe(DEFAULT_DEV_API_PROXY_TARGET);
    const target = new URL(DEFAULT_DEV_API_PROXY_TARGET);
    expect(listeners.some((url) => url.protocol === target.protocol && url.port === target.port)).toBe(true);
  });

  it('keeps the API listening on both HTTPS and HTTP', () => {
    expect(listeners.map(parts)).toEqual([
      { protocol: 'https:', hostname: 'localhost', port: '62152' },
      { protocol: 'http:', hostname: 'localhost', port: '62153' },
    ]);
  });

  it('still honours an explicit override, trimmed', () => {
    const https = applicationUrls.find((url) => new URL(url).protocol === 'https:')!;
    expect(resolveDevApiProxyTarget({ MAVI_API_PROXY_TARGET: ` ${https} ` })).toBe(https);
  });

  it('is never reached by application code, which calls /api same-origin', () => {
    const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../test/**'], {
      query: '?raw',
      import: 'default',
      eager: true,
    }) as Record<string, string>;
    expect(Object.keys(sources).length).toBeGreaterThan(20);
    const offenders = Object.entries(sources)
      .filter(([, text]) => /62152|62153|MAVI_API_PROXY_TARGET/.test(text))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
