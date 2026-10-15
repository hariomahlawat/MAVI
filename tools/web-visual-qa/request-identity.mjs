/**
 * X3 — page-issued request identity, part of the measurement contract
 * (ADR-012 Decision 15; UI specification §26).
 *
 * Under `forward` the harness gives every schedulable request (request-class
 * .mjs: same origin, under `/api/`, any method, not a media stream) an
 * identity assigned in the page, synchronously inside the `fetch` /
 * `XMLHttpRequest` call, in program order — before the browser's
 * prioritisation, connection pool or transport can reorder anything:
 *
 *   x-vqa-order: <docId>.<seq>.<run>
 *
 * - `docId`: a per-document nonce;
 * - `seq`: 1, 2, 3… per document, contiguous over the calls that reach the
 *   network (a call the browser would reject before sending takes no number);
 * - `run`: the synchronous stretch of script the call was made in (recorded
 *   only).
 *
 * admission.mjs admits requests to the network in `seq` order. The product
 * bundle is untouched: the harness installs this as an init script, it adds
 * one request header and one page-side log entry per numbered call, and
 * changes nothing else about the call — its method, URL, headers, body,
 * signal and credentials are the page's. A `Request` body is never read: a
 * `Request` input is checked, when an init accompanies it, on a clone.
 */
import { createHash } from 'node:crypto';
import { classifyRequest } from './request-class.mjs';

export const ORDER_HEADER = 'x-vqa-order';

/** The page-side instrumentation, as an init-script source. */
export const REQUEST_IDENTITY_SCRIPT = `(() => {
  if (!location.protocol.startsWith('http') || window.__vqaRequestLog) return;
  const classify = ${classifyRequest.toString()};
  const HEADER = ${JSON.stringify(ORDER_HEADER)};
  const docId = Math.floor(Math.random() * 0xffffffff).toString(36) + Math.floor(Math.random() * 0xffffffff).toString(36);
  const log = [];
  Object.defineProperty(window, '__vqaRequestLog', { value: { docId, log }, enumerable: false });
  let seq = 0; let run = 0; let runOpen = false;
  const bodyKind = (body) => {
    if (body === undefined || body === null) return null;
    if (typeof body === 'string') return 'text';
    const tag = Object.prototype.toString.call(body).slice(8, -1);
    return tag === 'Object' ? 'object' : tag;
  };
  const assign = (method, href, body, api) => {
    if (classify(method, href, location.origin) !== 'schedulable') return null;
    if (!runOpen) { runOpen = true; run += 1; queueMicrotask(() => { runOpen = false; }); }
    seq += 1;
    const url = new URL(href, location.origin);
    log.push([seq, run, method, url.pathname + url.search, bodyKind(body), api, performance.now()]);
    return docId + '.' + seq + '.' + run;
  };
  const isRequest = (value) => typeof Request === 'function' && value instanceof Request;
  const nativeFetch = window.fetch;
  if (typeof nativeFetch === 'function') {
    window.fetch = function fetch(input, init) {
      let method; let href; let body; let signal;
      try {
        const request = isRequest(input) ? input : null;
        method = String((init && init.method) || (request ? request.method : 'GET')).toUpperCase();
        href = new URL(request ? request.url : String(input), document.baseURI).href;
        body = init && 'body' in init ? init.body : (request && request.body ? 'stream' : null);
        signal = (init && init.signal) || (request ? request.signal : null);
      } catch { return nativeFetch.apply(this, arguments); }
      // A call that never reaches the network takes no number: an already
      // aborted signal, or one the browser rejects before sending (an invalid
      // method, header or URL — checked by constructing the request; a
      // Request input is valid already, and with an init beside it is checked
      // on a clone, so its body is never read).
      if (signal && signal.aborted) return nativeFetch.apply(this, arguments);
      if (!isRequest(input)) {
        try { new Request(input, init); } catch { return nativeFetch.apply(this, arguments); }
      } else if (input.bodyUsed) {
        return nativeFetch.apply(this, arguments);
      } else if (init !== undefined) {
        try { new Request(input.clone(), init); } catch { return nativeFetch.apply(this, arguments); }
      }
      const id = assign(method, href, body, 'fetch');
      if (!id) return nativeFetch.apply(this, arguments);
      const headers = new Headers(init && init.headers !== undefined ? init.headers : (isRequest(input) ? input.headers : undefined));
      headers.set(HEADER, id);
      return nativeFetch.call(this, input, Object.assign({}, init, { headers }));
    };
  }
  if (typeof XMLHttpRequest === 'function') {
    const opened = new WeakMap();
    const open = XMLHttpRequest.prototype.open;
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      const result = open.apply(this, arguments);
      try { opened.set(this, { method: String(method).toUpperCase(), href: new URL(String(url), document.baseURI).href, sent: false }); } catch { opened.delete(this); }
      return result;
    };
    XMLHttpRequest.prototype.send = function (body) {
      const target = opened.get(this);
      // Numbered only when send will reach the network: opened, not sent yet.
      if (target && !target.sent && this.readyState === 1) {
        target.sent = true;
        const id = assign(target.method, target.href, body, 'xhr');
        if (id) this.setRequestHeader(HEADER, id);
      }
      return send.apply(this, arguments);
    };
  }
})();`;

/** Parse an `x-vqa-order` value. */
export function parseOrder(value) {
  const m = /^([0-9a-z]+)\.([1-9][0-9]*)\.([1-9][0-9]*)$/.exec(String(value ?? ''));
  return m ? { docId: m[1], seq: Number(m[2]), run: Number(m[3]) } : null;
}

const sha = (text) => createHash('sha256').update(text).digest('hex');
const canonical = (rows) => rows.map((row) => JSON.stringify(row)).join('\n') + (rows.length ? '\n' : '');

/**
 * One case's request trace (diagnostic, never judged), each record kept
 * separately:
 * - `issue`: the page's identity log (final document) and, for documents the
 *   case left, the identities the browser saw — program order per document;
 * - `admission`: the order admission released requests in, and what it did
 *   with each unnumbered one;
 * - `transport`: what the browser reports for each request (CDP Network):
 *   finished, failed or cancelled, with status, and when;
 * - `server`: arrival order and time, answer time, status and outcome;
 * - `page`: when the page saw each response complete (Resource Timing).
 * Documents are numbered by first appearance (their nonces are random), so
 * traces of different runs compare. Times are kept but never hashed.
 */
export function buildRequestTrace({ pageLog, admission = null, transport, server, page = null }) {
  const docs = new Map();
  const doc = (docId) => { if (!docs.has(docId)) docs.set(docId, docs.size + 1); return docs.get(docId); };
  const issued = new Map();
  for (const t of transport) {
    const order = parseOrder(t.order);
    if (!order) continue;
    const key = `${order.docId}.${order.seq}`;
    if (!issued.has(key)) issued.set(key, { doc: order.docId, seq: order.seq, run: order.run, method: t.method, key: t.path, body: null, api: null });
  }
  if (pageLog) {
    for (const [seq, run, method, path, body, api] of pageLog.log) issued.set(`${pageLog.docId}.${seq}`, { doc: pageLog.docId, seq, run, method, key: path, body, api });
  }
  const issueRows = [...issued.values()].map((r) => ({ ...r, docOrdinal: doc(r.doc) })).sort((a, b) => a.docOrdinal - b.docOrdinal || a.seq - b.seq);
  const idOf = (order) => { const o = parseOrder(order); return o ? `${doc(o.docId)}.${o.seq}` : null; };
  const issue = issueRows.map((r) => ({ id: `${r.docOrdinal}.${r.seq}`, run: r.run, method: r.method, key: r.key, body: r.body, api: r.api }));
  const serverRows = server.map((s) => ({ id: idOf(s.order), method: s.method, key: s.path, kind: s.kind, image: s.image ?? false, outcome: s.outcome, ...(s.currentEpochCookie !== undefined ? { currentEpochCookie: s.currentEpochCookie } : {}), status: s.status ?? null, arrivedAt: s.arrivedAt, answeredAt: s.answeredAt ?? null }));
  const answered = serverRows.filter((s) => s.id && s.answeredAt !== null).sort((a, b) => a.answeredAt - b.answeredAt);
  return {
    issue,
    admission,
    transport: transport.map((t) => ({ id: idOf(t.order), method: t.method, key: t.path, type: t.type ?? null, outcome: t.outcome, status: t.status ?? null, error: t.error ?? null, sentAt: t.sentAt ?? null, endAt: t.endAt ?? null })),
    server: serverRows,
    page,
    hashes: {
      issue: sha(canonical(issue.map((r) => [r.id, r.method, r.key]))),
      arrival: sha(canonical(serverRows.filter((s) => s.id).map((s) => [s.id, s.method, s.key]))),
      response: sha(canonical(answered.map((s) => [s.id, s.method, s.key, s.outcome]))),
    },
  };
}
