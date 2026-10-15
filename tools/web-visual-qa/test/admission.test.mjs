/**
 * X3 — page-issued request identity and pre-transport admission (the
 * `forward` measurement contract: request-identity.mjs, admission.mjs,
 * server.mjs). Focused tests of its invariants:
 * - admission releases N+1 only on the exact acknowledgement of N (an
 *   unrelated request reaching the server first does not count) or N's
 *   failure;
 * - only a positively identified image (and a media stream) bypasses the
 *   order; any other unnumbered schedulable request is a fault, never admitted;
 * - a request cancelled while paused, a number never reported and a stale
 *   document all end deterministically;
 * - a duplicate identity is refused before the fixtures, their sequences or
 *   mutation state advance; an unnumbered request is refused at the server;
 * - the page wrapper never reads a Request body, and fetch/XHR keep their
 *   semantics (only the identity header is added).
 */
import assert from 'node:assert/strict';
import { request as httpRequest } from 'node:http';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, it } from 'node:test';
import { createAdmission } from '../admission.mjs';
import { ORDER_HEADER } from '../request-identity.mjs';
import { startServer } from '../server.mjs';
import { openBrowser, unitBlock } from './browser.mjs';

const tick = () => new Promise((resolve) => setImmediate(resolve));
const settleTicks = async (n = 10) => { for (let i = 0; i < n; i += 1) await tick(); };

/** A browser that records what admission asks of it, and an acknowledging server. */
function rig({ pageDocId = 'doc', backstopMs = 15_000 } = {}) {
  const handlers = new Map();
  const calls = [];
  const browser = {
    cdp: async (method, params) => { calls.push([method, params?.requestId ?? null]); return {}; },
    onEvent: (method, fn) => { handlers.set(method, fn); return () => handlers.delete(method); },
    evaluate: async () => pageDocId,
  };
  const identities = new Set(); const listeners = new Set();
  const server = {
    origin: 'http://127.0.0.1:1',
    hasIdentity: (key) => identities.has(key),
    onIdentity: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    arrive: (key) => { identities.add(key); for (const fn of listeners) fn(key); },
  };
  const admission = createAdmission(browser, server, { backstopMs });
  const emit = (method, params) => handlers.get(method)?.(params);
  const pause = (requestId, { seq = null, doc = 'doc', path = `/api/x${seq ?? ''}`, type = 'Fetch', method = 'GET' } = {}) => emit('Fetch.requestPaused', {
    requestId, networkId: `n-${requestId}`, resourceType: type,
    request: { method, url: `${server.origin}${path}`, headers: seq ? { [ORDER_HEADER]: `${doc}.${seq}.1` } : {} },
  });
  const continued = () => calls.filter(([m]) => m === 'Fetch.continueRequest').map(([, id]) => id);
  const failed = () => calls.filter(([m]) => m === 'Fetch.failRequest').map(([, id]) => id);
  return { admission, server, emit, pause, continued, failed, close: () => admission.close() };
}

describe('X3 admission (pre-transport, page-issued identity)', unitBlock(), () => {
  it('releases N+1 only when the server has acknowledged N itself — an unrelated media request arriving first does not count', async () => {
    const r = rig();
    await r.admission.start();
    r.pause('r1', { seq: 1 }); r.pause('r2', { seq: 2 });
    await settleTicks();
    assert.deepEqual(r.continued(), ['r1'], 'only the first is released');
    // A video stream is paused and continued at once, and reaches the server
    // before r1 does: no identity of the order arrived, so r2 waits.
    r.pause('m1', { path: '/api/videos/v1/content', type: 'Media' });
    r.server.arrive('unrelated.9');
    await settleTicks();
    assert.deepEqual(r.continued(), ['r1', 'm1']);
    r.server.arrive('doc.1');
    await settleTicks();
    assert.deepEqual(r.continued(), ['r1', 'm1', 'r2']);
    r.server.arrive('doc.2');
    const summary = await r.admission.stop();
    assert.deepEqual(summary.faults, []);
    assert.deepEqual(summary.released, ['1', '2']);
    r.close();
  });

  it('continues a positively identified image at once, outside the order; any other unnumbered schedulable request is a fault, failed and never admitted', async () => {
    const r = rig();
    await r.admission.start();
    r.pause('img', { path: '/api/artifacts/a/content', type: 'Image' });
    r.pause('rogue', { path: '/api/items', type: 'Fetch' });
    r.pause('rogue-xhr', { path: '/api/items', type: 'XHR', method: 'POST' });
    r.pause('other', { path: '/api/items', type: 'Other' });
    await settleTicks();
    assert.deepEqual(r.continued(), ['img']);
    assert.deepEqual(r.failed(), ['rogue', 'rogue-xhr', 'other']);
    const summary = await r.admission.stop();
    assert.equal(summary.faults.length, 3);
    assert.ok(summary.faults.every((f) => /without a page-issued identity/.test(f)), JSON.stringify(summary.faults));
    r.close();
  });

  it('a request cancelled while paused is settled by the browser’s report, deterministically: the next is released when its turn comes', async () => {
    const r = rig();
    await r.admission.start();
    r.pause('r1', { seq: 1 }); r.pause('r2', { seq: 2 }); r.pause('r3', { seq: 3 });
    await settleTicks();
    r.emit('Network.loadingFailed', { requestId: 'n-r2', canceled: true, errorText: 'net::ERR_ABORTED' });
    r.server.arrive('doc.1');
    await settleTicks();
    assert.deepEqual(r.continued(), ['r1', 'r3']);
    // A released request cancelled before it reached the server also ends its wait.
    r.emit('Network.loadingFailed', { requestId: 'n-r3', canceled: true, errorText: 'net::ERR_ABORTED' });
    r.pause('r4', { seq: 4 });
    await settleTicks();
    assert.deepEqual(r.continued(), ['r1', 'r3', 'r4']);
    r.server.arrive('doc.4');
    const summary = await r.admission.stop();
    assert.deepEqual(summary.released, ['1', '2:failed', '3:failed', '4']);
    assert.deepEqual(summary.faults, []);
    r.close();
  });

  it('a stale document can never order the current one: its requests are failed; the page’s own document is the authority', async () => {
    const r = rig({ pageDocId: 'current' });
    await r.admission.start();
    r.pause('old1', { seq: 1, doc: 'old' });
    r.pause('new1', { seq: 1, doc: 'current' });
    await settleTicks(20);
    assert.deepEqual(r.failed(), ['old1']);
    assert.deepEqual(r.continued(), ['new1']);
    r.pause('old2', { seq: 2, doc: 'old' });
    await settleTicks();
    assert.deepEqual(r.failed(), ['old1', 'old2']);
    r.server.arrive('current.1');
    const summary = await r.admission.stop();
    assert.ok(summary.bypassed.filter((b) => b.startsWith('stale-document:')).length === 2);
    r.close();
  });

  it('a number the browser never reports is detected by the backstop and reported as a fault; ordering is not decided by the timer', async () => {
    const r = rig({ backstopMs: 120 });
    await r.admission.start();
    r.pause('r2', { seq: 2 });
    for (let waited = 0; !r.continued().includes('r2') && waited < 3000; waited += 10) await new Promise((resolve) => setTimeout(resolve, 10));
    assert.deepEqual(r.continued(), ['r2'], 'after the fault the case ends in order');
    r.server.arrive('doc.2');
    const summary = await r.admission.stop();
    assert.equal(summary.faults.length, 1);
    assert.match(summary.faults[0], /doc\.1 was issued but the browser never reported it/);
    r.close();
  });

  it('a released request that neither arrives nor fails is reported by the backstop', async () => {
    const r = rig({ backstopMs: 120 });
    await r.admission.start();
    r.pause('r1', { seq: 1 });
    await new Promise((resolve) => setTimeout(resolve, 600));
    const summary = await r.admission.stop();
    assert.equal(summary.faults.length, 1);
    assert.match(summary.faults[0], /doc\.1 was released but neither reached the server nor failed/);
    r.close();
  });
});

/** A raw HTTP request to the fixture server (a transport the test controls). */
function raw(origin, path, { method = 'GET', headers = {}, body = null } = {}) {
  return new Promise((resolve) => {
    const req = httpRequest(origin + path, { method, headers, agent: false }, (res) => {
      let data = ''; res.on('data', (c) => { data += c; }); res.on('end', () => resolve({ status: res.statusCode, body: data }));
    });
    req.on('error', () => resolve({ status: 'refused' }));
    if (body) req.write(body);
    req.end();
  });
}

describe('X3 server: one arrival per identity; identity required under admission', unitBlock(), () => {
  let server; let dir; let scenario = {};
  before(async () => {
    dir = mkdtempSync(join(tmpdir(), 'mavi-vqa-admission-'));
    mkdirSync(join(dir, 'fixtures'));
    writeFileSync(join(dir, 'index.html'), '<!doctype html><title>x</title>');
    server = await startServer({ distDir: dir, fixtureDir: join(dir, 'fixtures'), scenario: () => scenario, footage: () => null, responseOrder: 'forward', requireIdentity: true });
  });
  after(async () => { await server.close(); rmSync(dir, { recursive: true, force: true }); });

  it('refuses a duplicate {epoch, identity} before the fixtures, their sequence counters or mutation state advance', async () => {
    scenario = { '/api/seq': { sequence: [{ n: 1 }, { n: 2 }] }, 'POST /api/act': { status: 201, body: { ok: true } } };
    server.resetSequences();
    const cookie = 'vqa-epoch=' + /vqa-epoch=(\d+)/.exec((await new Promise((resolve) => httpRequest(server.origin + '/case', { agent: false }, (res) => { res.resume(); resolve(res.headers['set-cookie']?.[0] ?? ''); }).end())))?.[1];
    const id = (n) => ({ [ORDER_HEADER]: `d1.${n}.1`, cookie });
    assert.deepEqual(await raw(server.origin, '/api/seq', { headers: id(1) }), { status: 200, body: '{"n":1}' });
    assert.equal((await raw(server.origin, '/api/seq', { headers: id(1) })).status, 'refused');
    // The sequence did not advance on the duplicate: the next identity gets the second answer.
    assert.deepEqual(await raw(server.origin, '/api/seq', { headers: id(2) }), { status: 200, body: '{"n":2}' });
    assert.equal((await raw(server.origin, '/api/act', { method: 'POST', headers: { ...id(3), 'content-type': 'application/json' }, body: '{}' })).status, 201);
    assert.equal((await raw(server.origin, '/api/act', { method: 'POST', headers: { ...id(3), 'content-type': 'application/json' }, body: '{}' })).status, 'refused');
    assert.deepEqual(server.requests().map((r) => `${r.method} ${r.path}`), ['GET /api/seq', 'GET /api/seq', 'POST /api/act']);
    assert.equal(server.faults().length, 2);
    assert.ok(server.faults().every((f) => /duplicate request identity/.test(f)));
    // The next case's epoch starts clean: the same identity is new there.
    server.resetSequences();
    assert.deepEqual(server.faults(), []);
  });

  it('refuses a schedulable request without an identity (a fault), but delivers an image at once, outside the order', async () => {
    scenario = { '/api/items': { ok: 1 } };
    server.resetSequences();
    assert.equal((await raw(server.origin, '/api/items')).status, 'refused');
    assert.equal((await raw(server.origin, '/api/items', { headers: { 'sec-fetch-dest': 'image' } })).status, 200);
    assert.equal(server.faults().length, 1);
    assert.match(server.faults()[0], /without a page-issued identity/);
    assert.deepEqual(server.scheduled(), [], 'the image was not ordered');
  });
});

describe('X3 page identity: fetch and XHR keep their semantics; a Request body is never read', unitBlock(), () => {
  const API = {
    '/api/items': { items: [1, 2] },
    '/api/items/7': { id: 7 },
    'POST /api/items': { status: 201, body: { id: 9 } },
    'PUT /api/items/7': { id: 7, renamed: true },
    'PATCH /api/items/7': { id: 7, patched: true },
    'DELETE /api/items/7': { status: 204, body: null },
    '/api/broken': 'unavailable',
    '/api/teapot': { status: 418, body: { title: 'no' } },
    '/api/slow': 'hang',
  };
  const SCENARIOS = {
    'fetch GET query': `fetch('/api/items?page=2&q=a%20b').then(async (r) => [r.status, await r.text()])`,
    'fetch POST JSON, credentials include': `fetch('/api/items', { method: 'POST', credentials: 'include', headers: { 'content-type': 'application/json', 'x-app': 'a' }, body: JSON.stringify({ name: 'x' }) }).then(async (r) => [r.status, await r.text()])`,
    'fetch Request with a body, no init': `(() => { const q = new Request('/api/items', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{"from":"request"}' }); return fetch(q).then(async (r) => [r.status, await r.text(), q.bodyUsed]); })()`,
    'fetch Request with a body and an init': `(() => { const q = new Request('/api/items/7', { method: 'PUT', headers: new Headers({ 'content-type': 'application/json' }), body: '{"name":"y"}' }); return fetch(q, { headers: { 'content-type': 'application/json', 'x-extra': '1' } }).then(async (r) => [r.status, await r.text(), q.bodyUsed]); })()`,
    'fetch PATCH JSON': `fetch('/api/items/7', { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: '{"p":1}' }).then(async (r) => [r.status, await r.text()])`,
    'fetch DELETE with a body': `fetch('/api/items/7', { method: 'DELETE', headers: { 'content-type': 'application/json' }, body: '{"why":"x"}' }).then((r) => [r.status])`,
    'fetch 503 and 418': `Promise.all([fetch('/api/broken').then((r) => r.status), fetch('/api/teapot').then(async (r) => [r.status, await r.text()])])`,
    'fetch held open, aborted by its signal': `(() => { const c = new AbortController(); const p = fetch('/api/slow', { signal: c.signal }).then(() => 'resolved', (e) => e.name); setTimeout(() => c.abort(), 300); return p; })()`,
    'fetch already aborted': `(() => { const c = new AbortController(); c.abort(); return fetch('/api/items', { signal: c.signal }).then(() => 'resolved', (e) => e.name); })()`,
    'fetch rejected before sending (invalid method)': `fetch('/api/items', { method: 'CONNECT' }).then(() => 'resolved', (e) => e.name)`,
    'XHR GET': `new Promise((done) => { const x = new XMLHttpRequest(); x.open('GET', '/api/items'); x.onload = () => done([x.status, x.responseText]); x.send(); })`,
    'XHR POST JSON, withCredentials': `new Promise((done) => { const x = new XMLHttpRequest(); x.open('POST', '/api/items'); x.withCredentials = true; x.setRequestHeader('content-type', 'application/json'); x.onload = () => done([x.status, x.responseText]); x.send(JSON.stringify({ name: 'z' })); })`,
    'XHR DELETE': `new Promise((done) => { const x = new XMLHttpRequest(); x.open('DELETE', '/api/items/7'); x.onload = () => done([x.status]); x.send(); })`,
    'XHR aborted': `new Promise((done) => { const x = new XMLHttpRequest(); x.open('GET', '/api/slow'); x.onabort = () => done(['abort', x.readyState, x.status]); x.send(); setTimeout(() => x.abort(), 300); })`,
  };
  async function observe(lane) {
    const out = {};
    for (const [name, script] of Object.entries(SCENARIOS)) {
      await lane.page('<main>fidelity</main>', { api: API });
      lane.browser.clearRequestEvents();
      const seen = await lane.browser.evaluate(script);
      const traffic = lane.server.traffic();
      out[name] = {
        seen,
        received: lane.server.requests().map(({ method, path, search, body }) => ({ method, path, search, body })),
        headers: lane.browser.requestEvents().map((e) => e.headerNames.filter((h) => h !== ORDER_HEADER)),
        numbered: traffic.map((t) => Boolean(t.order)),
      };
      await lane.browser.goto('about:blank');
      lane.server.releaseHung();
    }
    return out;
  }
  let plain; let admitted;
  before(async () => {
    plain = await openBrowser({ responseOrder: 'forward', admission: false });
    plain.browser.recordRequests(true);
    admitted = await openBrowser({ responseOrder: 'forward' });
  });
  after(async () => { await plain.close(); await admitted.close(); });

  it('sees and sends the same with and without the identity and admission, adding only the identity header', async () => {
    const without = await observe(plain);
    const withIt = await observe(admitted);
    for (const name of Object.keys(SCENARIOS)) {
      assert.deepEqual(withIt[name].seen, without[name].seen, `${name}: what the page saw`);
      assert.deepEqual(withIt[name].received, without[name].received, `${name}: what the server received`);
      assert.deepEqual(withIt[name].headers, without[name].headers, `${name}: request headers other than ${ORDER_HEADER}`);
      assert.ok(withIt[name].numbered.every(Boolean), `${name}: every request that reached the server carried its identity`);
    }
    // The cases meant what they say.
    assert.deepEqual(withIt['fetch Request with a body, no init'].received[0].body, '{"from":"request"}');
    assert.deepEqual(withIt['fetch Request with a body and an init'].received[0].body, '{"name":"y"}');
    assert.equal(withIt['fetch held open, aborted by its signal'].seen, 'AbortError');
    assert.equal(withIt['fetch rejected before sending (invalid method)'].seen, 'TypeError');
    assert.equal(withIt['fetch already aborted'].received.length, 0);
    assert.deepEqual(admitted.admissionFaults, []);
  });

  it('numbers exactly the calls that reach the network, contiguously, in program order', async () => {
    await admitted.page('<main>numbers</main>', { api: API });
    const log = await admitted.browser.evaluate(`(async () => {
      const c = new AbortController(); c.abort();
      fetch('/api/items', { signal: c.signal }).catch(() => {});        // never sent: no number
      fetch('/api/items', { method: 'CONNECT' }).catch(() => {});        // rejected before sending: no number
      fetch('/api/videos/v1/content').catch(() => {});                   // media: no number
      fetch('/api/items?a=1'); fetch('/api/items/7', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: '{}' });
      const x = new XMLHttpRequest(); x.open('GET', '/api/items?a=2'); x.send();
      try { x.send(); } catch { /* sent already: no second number */ }
      await new Promise((r) => setTimeout(r, 600));
      return window.__vqaRequestLog.log.map((r) => [r[0], r[2], r[3]]);
    })()`);
    assert.deepEqual(log, [[1, 'GET', '/api/items?a=1'], [2, 'PUT', '/api/items/7'], [3, 'GET', '/api/items?a=2']]);
  });
});
