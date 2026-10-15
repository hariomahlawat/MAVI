/**
 * The one request-classification contract shared by the page-side request
 * identity instrumentation (request-identity.mjs) and the fixture server
 * (server.mjs) and admission (admission.mjs). Under the X3 `forward` order
 * every request the fixture server could schedule carries a harness identity
 * assigned before transport; only media streams are excluded, by this same
 * rule on every side, so they can never disagree about which requests are
 * numbered.
 *
 * `classifyRequest` is self-contained (no imports, no outer references): the
 * instrumentation serialises its source into the page, and a table test
 * (test/admission.test.mjs) proves the page's copy and this one agree.
 */

/**
 * @param {string} method  any HTTP method (the class does not depend on it)
 * @param {string} href  absolute or relative URL
 * @param {string} documentOrigin  the issuing document's origin
 * @returns {'schedulable'|'media'|'not-api'|'other-origin'|'unparsable'}
 * - `schedulable`: same origin, path under `/api/`, not a media stream —
 *   any method;
 * - `media`: a video stream (`/api/videos/{id}/content`), which the element
 *   requests in ranges for as long as it plays;
 * - `not-api`: same origin, outside `/api/` (the document, the bundle, assets);
 * - `other-origin`: never the fixture server's;
 * - `unparsable`: no URL could be formed.
 */
export function classifyRequest(method, href, documentOrigin) {
  let url;
  try { url = new URL(String(href), documentOrigin); } catch { return 'unparsable'; }
  if (url.origin !== documentOrigin) return 'other-origin';
  if (!url.pathname.startsWith('/api/')) return 'not-api';
  if (/^\/api\/videos\/[^/]+\/content$/.test(url.pathname)) return 'media';
  return 'schedulable';
}
