/**
 * Where the Vite development server proxies `/api` — Development only.
 *
 * The default is the API's plain-HTTP loopback endpoint as an IP literal, not
 * `https://localhost:62152`, for two offline reasons:
 *
 * - `localhost` is a name. Node resolves it with `AI_ADDRCONFIG`, and Windows does
 *   not count loopback as a configured address, so with every network adapter
 *   disabled the lookup can fail although the API is listening. `127.0.0.1` needs
 *   no resolution at all.
 * - The browser already speaks plain HTTP to Vite on `127.0.0.1:5173`. TLS on the
 *   Vite → API leg, between two local processes, protects nothing the browser can
 *   see, while depending on the development certificate.
 *
 * `Mavi.Api` still listens on both `https://localhost:62152` and
 * `http://localhost:62153`; this changes only the proxy's upstream. Published
 * builds serve the compiled UI same-origin from ASP.NET Core and never use this.
 * `MAVI_API_PROXY_TARGET` still overrides the default.
 */
export const DEFAULT_DEV_API_PROXY_TARGET = 'http://127.0.0.1:62153';

export function resolveDevApiProxyTarget(env: Readonly<Record<string, string | undefined>>): string {
  return env.MAVI_API_PROXY_TARGET?.trim() || DEFAULT_DEV_API_PROXY_TARGET;
}
