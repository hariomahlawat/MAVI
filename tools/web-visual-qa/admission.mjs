/**
 * X3 — pre-transport admission control, part of the measurement contract
 * (ADR-012 Decision 15; UI specification §26).
 *
 * Under `forward`, every `/api/` request the page makes is paused by the
 * browser itself (CDP Fetch, Request stage) — before connection-pool
 * admission, so the per-origin connection limit cannot reorder or starve
 * it — and admitted to the network by this controller:
 *
 * - a numbered request (request-identity.mjs) of the current document is
 *   admitted in `seq` order, one at a time: N+1 only once the fixture server
 *   has acknowledged the exact identity `<docId>.<N>` (server.hasIdentity /
 *   onIdentity — never a count of arrivals), or Chromium has reported N
 *   failed or cancelled (Network.loadingFailed). The server then answers in
 *   arrival order with its spacing: the page's issue order.
 * - a qualified artifact image (`resourceType: Image` on
 *   `/api/artifacts/{id}/content`, request-class.mjs) and a media stream are
 *   continued at once, outside the order;
 * - any other request without an identity is a harness fault: it is failed,
 *   never admitted.
 * - the current document is the page's own (`window.__vqaRequestLog.docId`);
 *   before its first request is released the fixture server is bound to it
 *   (server.bindDocument), and the server refuses identity-bearing traffic of
 *   any other document before any fixture state — the final isolation
 *   authority. A request of another document seen here is failed; a second
 *   document becoming current within one window is a harness fault.
 *
 * Nothing waits on a timer to decide an order. A backstop timer only detects
 * and reports a harness fault (a released request that neither arrives nor
 * fails; a number the browser never reports), after which admission
 * continues in `seq` order so the case ends — and the case is invalid.
 */
import { classifyRequest, isQualifiedArtifactImage } from './request-class.mjs';
import { ORDER_HEADER, parseOrder } from './request-identity.mjs';

export const ADMISSION_METHOD = 'page-identity+cdp-pre-transport';
export const ADMISSION_BACKSTOP_MS = 15_000;
const PATTERNS = [{ urlPattern: '*/api/*', requestStage: 'Request' }];

/**
 * @param {object} browser  cdp.mjs page handle
 * @param {object} server  server.mjs handle (origin, bindDocument, unbindDocument, hasIdentity, onIdentity)
 * @param {{ backstopMs?: number }} [options]
 */
export function createAdmission(browser, server, { backstopMs = ADMISSION_BACKSTOP_MS } = {}) {
  let s = null; // per-case state; null when not admitting
  const fresh = () => ({
    docId: null, next: 1, paused: new Map(), failed: new Set(), netSeq: new Map(), staleDocs: new Set(),
    waiting: null, pumping: false, released: [], bypassed: [], faults: [], images: new Set(), lastProgress: Date.now(),
  });
  const cont = (requestId) => browser.cdp('Fetch.continueRequest', { requestId });
  const fail = (requestId) => browser.cdp('Fetch.failRequest', { requestId, errorReason: 'BlockedByClient' });
  // The acknowledgement reads the run's own document, never the controller's
  // current state (a stop during a wait leaves that null).
  const ack = (st, seq) => server.hasIdentity(`${st.docId}.${seq}`);

  /** The page's own document identity (the authority), read from the page. */
  async function pageDocId() {
    for (let i = 0; i < 3; i += 1) {
      try { return await browser.evaluate('window.__vqaRequestLog ? window.__vqaRequestLog.docId : null'); } catch { /* navigating */ }
    }
    return null;
  }

  async function pump() {
    const st = s;
    if (!st || st.pumping) return;
    st.pumping = true;
    try {
      for (;;) {
        if (s !== st) return;
        const seq = st.next;
        if (st.failed.has(seq)) { st.released.push(`${seq}:failed`); st.next += 1; st.lastProgress = Date.now(); continue; }
        if (!st.paused.has(seq)) break;
        const requestId = st.paused.get(seq); st.paused.delete(seq);
        try { await cont(requestId); } catch { /* cancelled while paused: Network.loadingFailed resolves it */ }
        // Exact acknowledgement: this identity at the server, or its failure.
        if (!ack(st, seq) && !st.failed.has(seq)) {
          await new Promise((resolve) => {
            const started = Date.now();
            let off = () => {};
            const timer = setInterval(() => {
              if (s !== st) { done(); return; }
              if (Date.now() - started > backstopMs) {
                st.faults.push(`admission: request ${st.docId}.${seq} was released but neither reached the server nor failed within ${backstopMs} ms`);
                done();
              }
            }, 50);
            function done() { off(); clearInterval(timer); if (st.waiting?.seq === seq) st.waiting = null; resolve(); }
            st.waiting = { seq, done };
            off = server.onIdentity((key) => { if (key === `${st.docId}.${seq}`) done(); });
            if (ack(st, seq) || st.failed.has(seq)) done();
          });
        }
        st.released.push(st.failed.has(seq) && !ack(st, seq) ? `${seq}:failed` : String(seq));
        st.next += 1;
        st.lastProgress = Date.now();
      }
    } finally { st.pumping = false; }
  }

  // A number the browser never reports blocks the ones after it: detected and
  // reported (the case is invalid), then skipped so the case can end.
  const watchdog = setInterval(() => {
    const st = s;
    if (!st || st.pumping || st.waiting) return;
    if (st.paused.size && !st.paused.has(st.next) && !st.failed.has(st.next) && Date.now() - st.lastProgress > backstopMs) {
      st.faults.push(`admission: request ${st.docId}.${st.next} was issued but the browser never reported it (later numbers waited ${backstopMs} ms)`);
      st.failed.add(st.next);
      pump();
    }
  }, 250);
  watchdog.unref?.();

  browser.onEvent('Fetch.requestPaused', async (p) => {
    const st = s;
    if (!st) { cont(p.requestId).catch(() => {}); return; }
    const kind = classifyRequest(p.request.method, p.request.url, server.origin);
    const url = new URL(p.request.url);
    const where = `${p.request.method} ${url.pathname}${url.search}`;
    if (kind !== 'schedulable') { st.bypassed.push(`${kind}:${where}`); cont(p.requestId).catch(() => {}); return; }
    const order = parseOrder(p.request.headers[ORDER_HEADER] ?? Object.entries(p.request.headers).find(([k]) => k.toLowerCase() === ORDER_HEADER)?.[1]);
    if (!order) {
      // Only the qualified artifact image (an evidence crop in a fixed-size
      // box: request-class.mjs) is delivered outside the order.
      if (p.resourceType === 'Image' && isQualifiedArtifactImage(p.request.url, server.origin)) {
        st.bypassed.push(`image:${where}`);
        st.images.add(p.networkId);
        cont(p.requestId).catch(() => {});
        return;
      }
      st.faults.push(`admission: a schedulable ${p.resourceType} request without a page-issued identity: ${where} (failed, not admitted)`);
      fail(p.requestId).catch(() => {});
      return;
    }
    if (st.staleDocs.has(order.docId)) { st.bypassed.push(`stale-document:${where}`); fail(p.requestId).catch(() => {}); return; }
    if (order.docId !== st.docId) {
      // One question to the page at a time; requests pausing meanwhile wait for its answer.
      st.resolving ??= pageDocId().finally(() => { st.resolving = null; });
      const current = await st.resolving;
      if (s !== st) { cont(p.requestId).catch(() => {}); return; }
      if (st.staleDocs.has(order.docId) || current !== order.docId) { st.staleDocs.add(order.docId); st.bypassed.push(`stale-document:${where}`); fail(p.requestId).catch(() => {}); return; }
    }
    if (order.docId !== st.docId) {
      if (st.docId !== null) {
        // One document per admission window: a second one becoming current is
        // a harness fault, and none of the first one's sequencing state is
        // carried over to it — its requests are failed.
        st.faults.push(`admission: a second document (${order.docId}) became current within one admission window (after ${st.docId}); its requests were failed`);
        st.staleDocs.add(order.docId);
        st.bypassed.push(`second-document:${where}`);
        fail(p.requestId).catch(() => {});
        return;
      }
      // The current document: the fixture server is bound to it before its
      // first request is released (server.bindDocument) and refuses any other.
      st.docId = order.docId;
      server.bindDocument(st.docId);
    }
    st.netSeq.set(p.networkId, order.seq);
    st.paused.set(order.seq, p.requestId);
    pump();
  });
  browser.onEvent('Network.requestWillBeSent', (p) => {
    const st = s;
    if (!st) return;
    const order = parseOrder(p.request.headers?.[ORDER_HEADER]);
    if (order && order.docId === st.docId) st.netSeq.set(p.requestId, order.seq);
  });
  browser.onEvent('Network.loadingFailed', (p) => {
    const st = s;
    if (!st) return;
    st.images.delete(p.requestId);
    const seq = st.netSeq.get(p.requestId);
    if (seq === undefined) return;
    // Cancelled or failed — before or after it was admitted: either way the
    // browser has settled it, deterministically.
    st.failed.add(seq);
    st.paused.delete(seq);
    if (st.waiting?.seq === seq) st.waiting.done();
    pump();
  });
  browser.onEvent('Network.loadingFinished', (p) => { s?.images.delete(p.requestId); });

  return {
    method: ADMISSION_METHOD,
    /** Begin admitting for a case (before its document is requested). */
    async start() {
      server.unbindDocument();
      s = fresh();
      await browser.cdp('Fetch.enable', { patterns: PATTERNS });
    },
    /** Requests this controller still holds or awaits (settling counts them). */
    pending() {
      if (!s) return 0;
      return s.paused.size + (s.waiting ? 1 : 0) + s.images.size;
    },
    /** End the case: what was admitted, bypassed and faulted. Anything still held is a fault. */
    async stop() {
      const st = s;
      if (!st) return null;
      // A request paused at the very end, its predecessor still on its way to
      // the browser's network layer, is given the time to be admitted.
      for (let waited = 0; (st.paused.size || st.waiting) && waited < 2000; waited += 20) await new Promise((r) => setTimeout(r, 20));
      s = null;
      server.unbindDocument();
      if (st.paused.size) st.faults.push(`admission: ${st.paused.size} numbered request(s) were still held when the case ended (${[...st.paused.keys()].sort((a, b) => a - b).map((n) => `${st.docId}.${n}`).join(', ')})`);
      try { await browser.cdp('Fetch.disable'); } catch { /* the browser is closing */ }
      return { method: ADMISSION_METHOD, released: st.released, bypassed: st.bypassed, faults: st.faults };
    },
    close() { clearInterval(watchdog); s = null; server.unbindDocument(); },
  };
}
