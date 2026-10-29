/**
 * Static host for the built frontend plus canned API responses.
 *
 * The visual-QA pass runs against the real production bundle rather than the
 * dev server: the bundle is what operators get, and serving `dist` avoids the
 * dev server's module URLs colliding with the `/api/` prefix the fixtures
 * answer on. Nothing here requires the application to be altered to make
 * inspection easier (section 26).
 */
import { execFileSync } from 'node:child_process';
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { basename, dirname, extname, join, normalize } from 'node:path';
import { encodeTrajectory } from './msgpack.mjs';
import { classifyRequest, isQualifiedArtifactImage } from './request-class.mjs';
import { ORDER_HEADER, parseOrder } from './request-identity.mjs';

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.webm': 'video/webm',
  '.woff2': 'font/woff2',
};

/**
 * @param {object} options
 * @param {string} options.distDir  built frontend
 * @param {string} options.fixtureDir  directory of `<name>.json` API fixtures
 * @param {() => Record<string, unknown>} options.scenario  current fixture overrides
 * @param {() => string} options.footage  path to the clip the current state uses
 * @param {() => boolean} [options.textSpacing]  whether the text-spacing lane's overrides are served (X1)
 */
/** WCAG 1.4.12's overrides, as a user would apply them: no author style outranks them. */
export const TEXT_SPACING_CSS = '* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }';

/**
 * The data-response order a run pins (X3 determinism). With `natural` each
 * request is answered as it arrives, so when the page sees concurrent
 * responses — and so which intermediate layouts it paints — is left to
 * scheduling. `forward` (the gate's, performance.mjs) answers data requests
 * one at a time, in the order the page issued them, each no sooner than
 * RESPONSE_SPACING_MS after the previous answer, so every intermediate layout
 * of a load is painted and a case's CLS is a function of the bundle alone.
 *
 * The order is the page's, not the transport's: the harness numbers each
 * schedulable request in the page as it is issued (request-identity.mjs) and
 * admits it to the network one at a time, in that order, before the browser's
 * connection pool (admission.mjs). This server answers what it receives in
 * the order received — which admission has made the issue order — and
 * acknowledges each identity's arrival so admission can release the next.
 * Images and media streams are answered as they come, outside the order.
 */
const ORIGIN_BASE = 'http://127.0.0.1';
/** The review's Faces panel route (PoC S6): `/api/tracks/{id}/faces`. */
const TRACK_FACES = /^\/api\/tracks\/[^/]+\/faces$/;
export const RESPONSE_ORDERS = Object.freeze(['natural', 'forward']);
export const RESPONSE_SPACING_MS = 120;

/**
 * The pinned-order scheduler, one generation per case. Answers go one at a time
 * from the generation's queue, in the order submitted: each is sent, then the
 * next waits spacingMs from that moment (measured from the send, so a timer
 * that fires late never brings the next answer closer).
 *
 * reset() closes the generation: every timer it set is cancelled, its queue
 * is dropped (each entry's `drop` refuses its request), and a fresh
 * generation begins with nothing pending and no spacing owed. No closure of a
 * closed generation can run — its timers are cleared and guarded — so a
 * previous case cannot shift the next case's order or timing.
 * `setTimer`/`clearTimer`/`now` are injectable for a virtual clock in tests.
 */
export function createResponseScheduler({ spacingMs = RESPONSE_SPACING_MS, setTimer = setTimeout, clearTimer = clearTimeout, now = () => performance.now() } = {}) {
  const open = () => {
    // `arrivals`: each request submitted in this generation, in order, with
    // when it arrived and when it was answered — a diagnostic.
    const g = { queue: [], arrivals: [], timers: new Set(), pumping: false, live: true };
    const later = (fn, ms) => {
      const t = setTimer(() => { g.timers.delete(t); if (g.live) fn(); }, ms);
      g.timers.add(t);
    };
    const pump = () => {
      const entry = g.queue.shift();
      if (!entry) { g.pumping = false; return; }
      entry.arrival.answeredAt = now();
      entry.answer();
      later(pump, spacingMs);
    };
    g.submit = (entry) => {
      entry.arrival = { label: entry.label, at: now(), answeredAt: null };
      g.arrivals.push(entry.arrival);
      g.queue.push(entry);
      if (!g.pumping) { g.pumping = true; pump(); }
    };
    g.close = () => {
      g.live = false;
      for (const t of g.timers) clearTimer(t);
      g.timers.clear();
      const dropped = g.queue.splice(0);
      for (const entry of dropped) entry.drop?.();
    };
    return g;
  };
  let generation = open();
  return {
    submit: (answer, drop, label) => generation.submit({ answer, drop, label }),
    reset() { generation.close(); generation = open(); },
    /** What the current generation still holds (diagnostic and tests). */
    pending: () => ({ queued: generation.queue.length, timers: generation.timers.size }),
    /** The current generation's requests in arrival order, with when each arrived and was answered (diagnostic and tests). */
    arrivals: () => generation.arrivals.map((a) => ({ ...a })),
  };
}

/**
 * @param {object} options
 * @param {boolean} [options.requireIdentity]  under `forward`, every
 *   schedulable request must carry its page-issued identity (admission.mjs
 *   admits nothing else); one without it that is not an image is a harness
 *   fault, refused before it can reach the fixtures.
 */
export function startServer({ distDir, fixtureDir, scenario, footage, textSpacing = () => false, responseOrder = 'natural', requireIdentity = false }) {
  if (!RESPONSE_ORDERS.includes(responseOrder)) throw new Error(`unknown response order "${responseOrder}" (${RESPONSE_ORDERS.join(', ')})`);
  const scheduler = responseOrder === 'natural' ? null : createResponseScheduler();
  /** Bumped by resetSequences: a queued answer of an earlier epoch is dropped. */
  let epoch = 0;
  /**
   * A pinned order holds answers, so a document the harness is leaving can
   * still have a request on its way when the next case resets the fixtures;
   * answered in the new epoch, it would consume the new case's sequenced
   * fixtures (a previous page's poll taking the first answer of the next
   * page's lookup). Each document carries the epoch it was served in, as a
   * cookie its requests send back, and a request of an earlier epoch is
   * refused unanswered.
   */
  const documentEpoch = () => (responseOrder === 'natural' ? {} : { 'set-cookie': `vqa-epoch=${epoch}; Path=/; SameSite=Lax` });
  const staleDocument = (req) => {
    const sent = /(?:^|;\s*)vqa-epoch=(\d+)/.exec(req.headers.cookie ?? '')?.[1];
    return sent !== undefined && Number(sent) !== epoch;
  };

  /**
   * Responses deliberately left unanswered to hold a loading state. They must
   * be released when that state ends: the browser allows only a handful of
   * connections per origin, and leaving six hung requests open makes the next
   * state's requests queue behind them — which looks exactly like the next
   * state failing to render.
   */
  const hung = new Set();
  /** How many times each sequenced override has answered, per scenario. */
  const sequenceCounts = new Map();
  /**
   * X2: the requests the application has made since the last reset, in
   * order — a journey proves its operator action reached the backend from
   * this, never assumes it — and the mutations already received, which flip a
   * `{ after, before, then }` override from its before-state to its after-state.
   */
  const requests = [];
  const received = new Set();
  /**
   * Request accounting for deterministic settling (V3): how many requests are
   * in flight and how many have started. A request deliberately held to keep
   * a loading state open is not "in flight" — it will never complete, by
   * design — and media streams are not data readiness, which the overlay
   * check settles on its own.
   */
  const network = { inflight: 0, started: 0 };
  /** X3 (diagnostic): the `/api/` requests as this server saw them. */
  const traffic = [];
  /** X3: the identities that have arrived in this epoch, and who is waiting to hear of one. */
  const identities = new Map();
  const identityListeners = new Set();
  /** X3: the page document admission accepted as current (null: none), and its highest number seen. */
  let boundDocument = null;
  let highestSeq = 0;
  const faults = [];
  const server = createServer((req, res) => {
    const path = new URL(req.url ?? '/', 'http://127.0.0.1').pathname;
    if (process.env.MAVI_VQA_TRACE && path.startsWith('/api/')) process.stderr.write(`  [trace] ${Date.now() % 100000} ${req.method} ${path}
`);
    // A video stream is media — the element asks for ranges for as long as it
    // plays, and the overlay check settles it on its own. The classification
    // is the one the page-side identity uses (request-class.mjs).
    const kind = classifyRequest(req.method, req.url ?? '/', ORIGIN_BASE);
    const videoStream = kind === 'media';
    // X3: the request's page-issued identity (request-identity.mjs), and
    // whether the browser fetched it for an image (outside the order).
    const order = parseOrder(req.headers[ORDER_HEADER]);
    const image = req.headers['sec-fetch-dest'] === 'image';
    // Recorded only (diagnostics): the request as this server saw it.
    const seen = path.startsWith('/api/') ? { order: req.headers[ORDER_HEADER] ?? null, method: req.method, path: path + new URL(req.url ?? '/', ORIGIN_BASE).search, kind, image, arrivedAt: performance.now(), answeredAt: null, status: null, outcome: 'pending' } : null;
    if (seen) {
      traffic.push(seen);
      res.__vqaSeen = seen;
      res.on('finish', () => { seen.status = res.statusCode; if (seen.outcome === 'answering') seen.outcome = 'answered'; });
      res.on('close', () => { if (!res.writableEnded && (seen.outcome === 'pending' || seen.outcome === 'answering')) seen.outcome = 'closed-unanswered'; });
    }
    if (!videoStream && path !== '/__blank') {
      network.inflight += 1;
      network.started += 1;
      let done = false;
      const finish = () => { if (!done) { done = true; network.inflight -= 1; } };
      res.on('finish', finish);
      res.on('close', finish);
      res.__vqaFinish = finish;
    }
    // A held answer whose request the page already abandoned (it navigated
    // away) is dropped: answering it would consume the next case's sequenced
    // fixtures.
    let abandoned = false;
    res.on('close', () => { if (!res.writableEnded) abandoned = true; });
    const arrivedIn = epoch;
    const answer = () => {
      if (seen) seen.answeredAt = performance.now();
      if (abandoned) { if (seen) seen.outcome = 'abandoned'; return; }
      if (arrivedIn !== epoch) { if (seen) seen.outcome = 'refused-epoch'; res.destroy(); return; }
      if (seen) seen.outcome = 'answering';
      try {
        handle(req, res);
      } catch (error) {
        process.stderr.write(`  visual-qa server error on ${req.url}: ${error}\n`);
        if (!res.headersSent) res.writeHead(500);
        res.end();
      }
    };
    // Under admission the server is the final document-isolation authority:
    // it is bound to the one page document admission accepted as current
    // (bindDocument), and identity-bearing traffic of any other document — a
    // document the harness left, whose requests can still be on their way and
    // carry the shared cookie jar's new epoch — is refused here, before the
    // fixtures, their sequence counters, the mutation state, the scheduler or
    // the acknowledgement see it. Recorded (traffic), not a harness fault:
    // leftover browser traffic is expected; it must only never count.
    if (requireIdentity && order && kind === 'schedulable' && order.docId !== boundDocument) {
      if (seen) { seen.outcome = boundDocument === null ? 'refused-unbound-document' : 'refused-other-document'; seen.currentEpochCookie = !staleDocument(req); }
      res.destroy();
      return;
    }
    // The epoch cookie (redundant under admission; the defence without it).
    if (responseOrder !== 'natural' && path.startsWith('/api/') && staleDocument(req)) { if (seen) seen.outcome = 'refused-stale-epoch'; res.destroy(); return; }
    if (responseOrder !== 'natural' && kind === 'schedulable') {
      if (order) {
        // One arrival per identity and epoch. A second one (a transport
        // replay) is refused here — before the fixtures, their sequence
        // counters or any mutation state can see it — and is a harness fault.
        const key = `${order.docId}.${order.seq}`;
        if (identities.has(key)) {
          faults.push(`duplicate request identity ${key} (${req.method} ${path}) in epoch ${epoch}: refused before the fixtures`);
          if (seen) seen.outcome = 'refused-duplicate';
          res.destroy();
          return;
        }
        // The bound document's numbers arrive strictly increasing (gaps are
        // requests cancelled or failed on the way): one arriving below the
        // highest already seen is out of the page's issue order — refused
        // before any state advances, and a harness fault.
        if (requireIdentity && order.seq <= highestSeq) {
          faults.push(`out-of-order request identity ${key} (${req.method} ${path}) after ${order.docId}.${highestSeq}: refused before the fixtures`);
          if (seen) seen.outcome = 'refused-out-of-order';
          res.destroy();
          return;
        }
        highestSeq = Math.max(highestSeq, order.seq);
        identities.set(key, performance.now());
        for (const listener of identityListeners) listener(key);
        scheduler.submit(answer, () => { if (seen) seen.outcome = 'dropped-reset'; res.destroy(); }, path);
        return;
      }
      // The qualified artifact image (request-class.mjs) is delivered as it
      // comes, outside the order: an evidence crop sits in a box of its own
      // size. Any other unnumbered image fails closed below.
      if (image && isQualifiedArtifactImage(req.url ?? '/', ORIGIN_BASE)) { answer(); return; }
      if (requireIdentity) {
        faults.push(`a schedulable request without a page-issued identity reached the server: ${req.method} ${path}`);
        if (seen) seen.outcome = 'refused-unnumbered';
        res.destroy();
        return;
      }
      if (req.method === 'GET') { scheduler.submit(answer, () => res.destroy(), path); return; }
    }
    answer();
  });

  function handle(req, res) {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    // A trailing slash is the same resource; the client builds some URLs that way.
    const raw = decodeURIComponent(url.pathname);
    const path = raw.length > 1 && raw.endsWith('/') ? raw.slice(0, -1) : raw;

    if (path.startsWith('/api/')) {
      const overrides = scenario();
      const logged = { method: req.method, path, search: url.search };
      requests.push(logged);
      // A mutation's JSON body is kept (bounded), so a journey can show the
      // operator's own work reached the backend — the zone they drew, named.
      if (req.method !== 'GET' && /json/.test(req.headers['content-type'] ?? '')) {
        let body = '';
        req.on('data', (chunk) => { if (body.length < 65536) body += chunk; });
        req.on('end', () => { logged.body = body; });
      }
      // Only a mutation flips an `{ after }`: a GET is a read the application
      // may make on its own (a prefetch, a poll), never the operator's act.
      if (req.method !== 'GET' && req.method !== 'HEAD') received.add(`${req.method} ${path}`);
      // An exact override wins over a prefix one, and the longest prefix wins
      // over a shorter one. Declaration order used to decide it, so overriding
      // `/api/cameras/{id}` silently answered `/api/cameras/{id}/scene` with a
      // camera — the state then failed to render for a reason that looked
      // nothing like its cause.
      // A key may name a method — `POST /api/cameras` — so a state can make a
      // mutation fail without making the listing beside it fail too. Without
      // that, the only way to reach a 409 on create would be to break the GET
      // the page needs in order to render the form at all.
      const match = Object.keys(overrides)
        .filter((key) => {
          const spaced = key.indexOf(' ');
          const method = spaced === -1 ? null : key.slice(0, spaced);
          const keyPath = spaced === -1 ? key : key.slice(spaced + 1);
          if (method && method !== req.method) return false;
          // A Track's details override must not answer its Faces panel's own
          // route (PoC S6) with the Track: only an exact key does.
          if (path !== keyPath && TRACK_FACES.test(path)) return false;
          return path === keyPath || path.startsWith(keyPath + '/');
        })
        // A method-qualified key is more specific than a bare one of the same
        // length, and a longer path beats a shorter one.
        .sort((a, b) => (b.includes(' ') ? 1 : 0) - (a.includes(' ') ? 1 : 0) || b.length - a.length)[0];
      let value = match ? overrides[match] : undefined;
      let counter = match;
      // X2 — the backend's own state, answered as the operator's requests make
      // it, never ahead of them:
      // `{ after: 'METHOD /path', before, then }` answers `before` until the
      // application has sent that request (an import, a scene save), and
      // `then` from it on, so what follows an operator's action appears only
      // if the action really reached the backend;
      // `{ query: [{ match: { param: value | true }, then }], otherwise }`
      // answers by the request's query string (`true` for a parameter that is
      // present): a cursor continuation, a Car refinement — the request the
      // operator caused, not the order requests happen to arrive in.
      // Either may hold any of the forms below, a sequence included, counted
      // per branch.
      // An `after` may hold another (save, then re-analyse): resolved in turn.
      while (value !== null && typeof value === 'object' && typeof value.after === 'string') {
        const flipped = received.has(value.after);
        counter = `${counter}#${flipped ? 'then' : 'before'}`;
        value = flipped ? value.then : value.before;
      }
      if (value !== null && typeof value === 'object' && Array.isArray(value.query)) {
        const index = value.query.findIndex((branch) => Object.entries(branch.match ?? {}).every(([param, want]) => (want === true ? url.searchParams.has(param) : url.searchParams.get(param) === String(want))));
        counter = `${counter}#q${index}`;
        value = index === -1 ? value.otherwise : value.query[index].then;
      }

      // `'fixture'` re-exposes the normal fixture for a path that a broader
      // override would otherwise have swallowed, so it deliberately answers
      // none of the branches below and falls through to fixture handling.
      if (value === 'unavailable') {
        res.writeHead(503, { 'content-type': 'application/problem+json' });
        res.end(JSON.stringify({ title: 'Service unavailable', detail: 'The upstream service did not respond.', code: 'upstream_unavailable' }));
        return;
      }
      if (value === 'hang') {
        if (res.__vqaSeen) res.__vqaSeen.outcome = 'held';
        hung.add(res);
        res.on('close', () => hung.delete(res));
        res.__vqaFinish?.();
        return;
      }
      // `{ sequence: [...] }` answers successive requests to the same path with
      // successive entries, the last one repeating. Cursor pagination is the
      // reason: page one has to succeed for there to be a continuation to fail,
      // and a single override cannot say "then". Each entry is any of the forms
      // below, so a sequence can mix a body with a status.
      // `{ status, body }` answers with a specific status, which is how a
      // state reaches a conflict rather than a generic failure.
      let resolved = value;
      if (value !== null && typeof value === 'object' && Array.isArray(value.sequence)) {
        const seen = sequenceCounts.get(counter) ?? 0;
        sequenceCounts.set(counter, seen + 1);
        resolved = value.sequence[Math.min(seen, value.sequence.length - 1)];
        if (resolved === 'unavailable') {
          res.writeHead(503, { 'content-type': 'application/problem+json' });
          res.end(JSON.stringify({ title: 'Service unavailable', detail: 'The upstream service did not respond.', code: 'upstream_unavailable' }));
          return;
        }
      }
      if (resolved !== null && typeof resolved === 'object' && typeof resolved.status === 'number') {
        res.writeHead(resolved.status, { 'content-type': 'application/problem+json' });
        res.end(JSON.stringify(resolved.body ?? {}));
        return;
      }
      if (resolved !== undefined && resolved !== 'fixture' && resolved !== value) {
        res.writeHead(200, { 'content-type': TYPES['.json'] });
        res.end(JSON.stringify(resolved));
        return;
      }
      if (value !== null && typeof value === 'object' && typeof value.status === 'number') {
        res.writeHead(value.status, { 'content-type': 'application/problem+json' });
        res.end(JSON.stringify(value.body ?? {}));
        return;
      }
      if (value !== undefined && value !== 'fixture') {
        res.writeHead(200, { 'content-type': TYPES['.json'] });
        res.end(JSON.stringify(value));
        return;
      }

      // A trajectory artefact, encoded from its JSON fixture on the way out.
      //
      // UI-5's visual QA had no served trajectory at all, so the rendered
      // matrix could never show raw path evidence underneath the analytical
      // overlays. The bytes are generated rather than committed: the repository
      // stays text-only, the fixture is readable in review, and the encoder
      // emits only what the browser's decoder accepts, so a fixture it refuses
      // is a real disagreement rather than the harness writing something the
      // worker never would.
      const trajectory = /^\/api\/artifacts\/([a-z0-9-]+)\/trajectory$/.exec(path);
      if (trajectory) {
        const source = join(fixtureDir, `trajectory_${trajectory[1]}.json`);
        if (existsSync(source)) {
          const { points } = JSON.parse(readFileSync(source, 'utf8'));
          const bytes = encodeTrajectory(points);
          res.writeHead(200, { 'content-type': 'application/octet-stream', 'content-length': bytes.length });
          res.end(bytes);
          return;
        }
      }

      // An Evidence Set crop: a subject crop cut from the footage the state
      // plays, at the Observation's own offset and normalised box, so the
      // strip shows what the worker would have stored rather than a stock
      // picture. Generated and cached at run time like the footage itself;
      // nothing binary is committed. An artifact the crop fixture does not
      // list answers 404, which is how an unreadable crop is modelled.
      const crop = /^\/api\/artifacts\/([a-z0-9-]+)\/content$/.exec(path);
      if (crop && existsSync(join(fixtureDir, 'crops.json'))) {
        const { crops } = JSON.parse(readFileSync(join(fixtureDir, 'crops.json'), 'utf8'));
        const spec = crops[crop[1]];
        const clip = footage?.();
        if (!spec || !clip || !existsSync(clip)) {
          res.writeHead(404, { 'content-type': 'application/problem+json' });
          res.end(JSON.stringify({ status: 404, code: 'artifact_not_found', detail: 'Artifact content was not found.' }));
          return;
        }
        const bytes = cropJpeg(clip, crop[1], spec);
        res.writeHead(200, { 'content-type': TYPES['.jpg'], 'content-length': bytes.length });
        res.end(bytes);
        return;
      }

      // Media served through the API route the client actually requests.
      if (path.endsWith('/content')) {
        const clip = footage?.();
        if (clip && existsSync(clip)) {
          const total = statSync(clip).size;
          // Chromium asks for ranges in several shapes, including the suffix
          // form `bytes=-N`. Clamp rather than trust: an out-of-range start
          // throws inside createReadStream and would take the harness down
          // mid-pass.
          const range = /** @type {string | undefined} */ (req.headers.range);
          const match = range && /^bytes=(\d*)-(\d*)$/.exec(range.trim());
          if (match) {
            const [, fromText, toText] = match;
            let start;
            let end;
            if (fromText === '') {
              const suffix = Math.min(Number(toText) || 0, total);
              start = Math.max(total - suffix, 0);
              end = total - 1;
            } else {
              start = Math.min(Number(fromText), total - 1);
              end = toText === '' ? total - 1 : Math.min(Number(toText), total - 1);
            }
            if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
              res.writeHead(416, { 'content-range': `bytes */${total}` }).end();
              return;
            }
            res.writeHead(206, {
              'content-type': TYPES['.webm'],
              'content-range': `bytes ${start}-${end}/${total}`,
              'accept-ranges': 'bytes',
              'content-length': end - start + 1,
            });
            createReadStream(clip, { start, end }).pipe(res);
            return;
          }
          res.writeHead(200, { 'content-type': TYPES['.webm'], 'content-length': total, 'accept-ranges': 'bytes' });
          createReadStream(clip).pipe(res);
          return;
        }
      }

      const file = join(fixtureDir, path.replace('/api/', '').replaceAll('/', '_') + '.json');
      if (existsSync(file)) {
        res.writeHead(200, { 'content-type': TYPES['.json'] });
        res.end(readFileSync(file));
        return;
      }
      // The review's Faces panel (PoC S6) asks every Track for its faces. The fixture world has no face
      // release, so the platform's own answer for that case stands in unless a state supplies a fixture.
      if (TRACK_FACES.test(path)) {
        res.writeHead(200, { 'content-type': TYPES['.json'] });
        res.end(JSON.stringify({
          label: 'Face candidates — not identification — Development',
          state: 'notConfigured', reason: null, identity: null, referenceThreshold: null, faces: [],
        }));
        return;
      }
      if (process.env.MAVI_VQA_DEBUG) process.stderr.write('  no fixture: ' + path + '\n');
      res.writeHead(404, { 'content-type': TYPES['.json'] });
      res.end('{}');
      return;
    }

    // Media referenced by evidence surfaces.
    if (path.startsWith('/content/')) {
      const file = join(fixtureDir, 'media', normalize(path.replace('/content/', '')));
      if (existsSync(file) && statSync(file).isFile()) {
        res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' });
        createReadStream(file).pipe(res);
        return;
      }
      if (process.env.MAVI_VQA_DEBUG) process.stderr.write('  no media: ' + path + '\n');
      res.writeHead(404).end();
      return;
    }

    // A same-origin document that boots nothing.
    //
    // Per-viewer storage belongs to the origin, so clearing it needs a page on
    // this origin — but every SPA route serves index.html, which starts the
    // application and issues its API requests. Doing that merely to reach
    // `localStorage` consumed the first entry of a sequenced override, so the
    // capture that followed began at the failure and `search-continuation-failed`
    // never had a first page to continue from.
    if (path === '/__blank') {
      res.writeHead(200, { 'content-type': TYPES['.html'], ...documentEpoch() });
      res.end('<!doctype html><title>blank</title>');
      return;
    }

    // Everything else is the SPA: real asset, or index.html for a route.
    const asset = join(distDir, normalize(path));
    if (path !== '/' && existsSync(asset) && statSync(asset).isFile()) {
      res.writeHead(200, { 'content-type': TYPES[extname(asset)] ?? 'application/octet-stream' });
      createReadStream(asset).pipe(res);
      return;
    }
    res.writeHead(200, { 'content-type': TYPES['.html'], ...documentEpoch() });
    // The text-spacing lane (X1, WCAG 1.4.12): the operator's overrides are a
    // stylesheet in the document's head, in force before the first paint — as
    // a user stylesheet would be — and read back from computed style by the
    // lane's environment check, never assumed.
    if (textSpacing()) {
      const html = readFileSync(join(distDir, 'index.html'), 'utf8');
      const style = '<style id="vqa-text-spacing">' + TEXT_SPACING_CSS + '</style>';
      res.end(html.includes('</head>') ? html.replace('</head>', style + '</head>') : style + html);
      return;
    }
    createReadStream(join(distDir, 'index.html')).pipe(res);
  }

  server.on('clientError', (_error, socket) => socket.destroy());

  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = /** @type {import('node:net').AddressInfo} */ (server.address());
      resolve({
        origin: `http://127.0.0.1:${port}`,
        releaseHung() {
          for (const res of hung) { try { res.destroy(); } catch { /* already gone */ } }
          hung.clear();
        },
        /**
         * Rewind every sequenced override. Without this the second viewport of
         * a paginated state would start where the first one left off and get
         * the failure instead of page one — which looks exactly like the state
         * failing at that width and is not.
         */
        resetSequences() {
          sequenceCounts.clear(); requests.length = 0; received.clear(); traffic.length = 0; identities.clear(); faults.length = 0;
          boundDocument = null; highestSeq = 0;
          // A pinned order's answers still queued belong to the scenario being
          // reset (a previous document's poll, say): answered after the reset
          // they would consume the next case's sequenced fixtures, which a
          // natural-order server answered before it. The generation is closed —
          // its timers cancelled, its queue and burst dropped (their requests
          // refused) — and the next case starts a fresh one.
          scheduler?.reset();
          epoch += 1;
        },
        /** X2: the API requests made since the last reset, oldest first. */
        requests: () => requests.map((r) => ({ ...r })),
        /**
         * Under a pinned order, the data requests scheduled since the last
         * reset in the order they arrived, each with its arrival time and when
         * it was answered (`performance.now()`, ms). A diagnostic.
         */
        scheduled: () => scheduler?.arrivals() ?? [],
        /** X3 (diagnostic): every `/api/` request since the last reset, in arrival order. */
        traffic: () => traffic.map((r) => ({ ...r })),
        /**
         * X3 admission's acknowledgement: whether this exact identity
         * (`<docId>.<seq>`) has arrived in the current epoch, and a listener
         * told of each one as it does. Never a count of arrivals.
         */
        hasIdentity: (key) => identities.has(key),
        /**
         * X3 admission binds the server to the page document it accepted as
         * current, before that document's first request is released, and
         * clears it at the end of the window (and at every reset).
         */
        bindDocument(docId) { if (boundDocument !== docId) { boundDocument = docId; highestSeq = 0; } },
        unbindDocument() { boundDocument = null; highestSeq = 0; },
        boundDocument: () => boundDocument,
        onIdentity(listener) { identityListeners.add(listener); return () => identityListeners.delete(listener); },
        /** Harness faults the server refused requests for since the last reset (duplicates, unnumbered). */
        faults: () => faults.slice(),
        /** In-flight and started request counts, for the settle loop. */
        // `hung`: requests held open on purpose (a held loading state) — each is a
        // query the page reports as fetching for as long as the state lasts.
        network: () => ({ ...network, hung: hung.size }),
        close: () => new Promise((done) => { for (const res of hung) { try { res.destroy(); } catch { /* gone */ } } server.close(done); }),
      });
    });
  });
}

/** Crops already cut, per footage condition and artifact. */
const cropCache = new Map();

function cropJpeg(clip, artifactId, { offsetMs, boundingBox: box }) {
  const key = `${clip}|${artifactId}`;
  const cached = cropCache.get(key);
  if (cached) return cached;
  const target = join(dirname(clip), `crop-${basename(clip, '.webm')}-${artifactId}.jpg`);
  if (!existsSync(target)) {
    const n = (value) => value.toFixed(4);
    execFileSync('ffmpeg', [
      '-hide_banner', '-loglevel', 'error', '-y',
      '-ss', (offsetMs / 1000).toFixed(3), '-i', clip, '-frames:v', '1',
      '-vf', `crop=iw*${n(box.width)}:ih*${n(box.height)}:iw*${n(box.x)}:ih*${n(box.y)}`,
      '-q:v', '4', target,
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
  }
  const bytes = readFileSync(target);
  cropCache.set(key, bytes);
  return bytes;
}
