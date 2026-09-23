import { describe, expect, it } from 'vitest';
import launchSettings from '../../../../platform/Mavi.Api/Properties/launchSettings.json';
import { DEFAULT_DEV_API_PROXY_TARGET, resolveDevApiProxyTarget } from '../../devApiProxy';

const profile = launchSettings.profiles['Mavi.Api'];
const applicationUrls = profile.applicationUrl.split(';');

describe('Development API proxy target', () => {
  it('defaults to the loopback HTTP endpoint as an IP literal', () => {
    // No name to resolve and no certificate to trust: both fail offline on the
    // Development machine, and neither protects a loopback hop between two
    // local processes.
    expect(DEFAULT_DEV_API_PROXY_TARGET).toBe('http://127.0.0.1:62153');
    expect(resolveDevApiProxyTarget({})).toBe(DEFAULT_DEV_API_PROXY_TARGET);
    expect(resolveDevApiProxyTarget({ MAVI_API_PROXY_TARGET: '   ' })).toBe(DEFAULT_DEV_API_PROXY_TARGET);
  });

  it('is what the Visual Studio profile sets, on a port the API actually listens on', () => {
    expect(profile.environmentVariables.MAVI_API_PROXY_TARGET).toBe(DEFAULT_DEV_API_PROXY_TARGET);
    const target = new URL(DEFAULT_DEV_API_PROXY_TARGET);
    const listening = applicationUrls.map((url) => new URL(url));
    expect(listening.some((url) => url.protocol === target.protocol && url.port === target.port)).toBe(true);
  });

  it('keeps the API listening on both HTTPS and HTTP', () => {
    expect(applicationUrls).toEqual(['https://localhost:62152', 'http://localhost:62153']);
  });

  it('still honours an explicit override, trimmed', () => {
    expect(resolveDevApiProxyTarget({ MAVI_API_PROXY_TARGET: ' https://localhost:62152 ' }))
      .toBe('https://localhost:62152');
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
