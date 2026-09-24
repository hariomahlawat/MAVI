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
 */
export function startServer({ distDir, fixtureDir, scenario, footage }) {
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
  const server = createServer((req, res) => {
    try {
      handle(req, res);
    } catch (error) {
      process.stderr.write(`  visual-qa server error on ${req.url}: ${error}\n`);
      if (!res.headersSent) res.writeHead(500);
      res.end();
    }
  });

  function handle(req, res) {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    // A trailing slash is the same resource; the client builds some URLs that way.
    const raw = decodeURIComponent(url.pathname);
    const path = raw.length > 1 && raw.endsWith('/') ? raw.slice(0, -1) : raw;

    if (path.startsWith('/api/')) {
      const overrides = scenario();
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
          return path === keyPath || path.startsWith(keyPath + '/');
        })
        // A method-qualified key is more specific than a bare one of the same
        // length, and a longer path beats a shorter one.
        .sort((a, b) => (b.includes(' ') ? 1 : 0) - (a.includes(' ') ? 1 : 0) || b.length - a.length)[0];
      const value = match ? overrides[match] : undefined;

      // `'fixture'` re-exposes the normal fixture for a path that a broader
      // override would otherwise have swallowed, so it deliberately answers
      // none of the branches below and falls through to fixture handling.
      if (value === 'unavailable') {
        res.writeHead(503, { 'content-type': 'application/problem+json' });
        res.end(JSON.stringify({ title: 'Service unavailable', detail: 'The upstream service did not respond.', code: 'upstream_unavailable' }));
        return;
      }
      if (value === 'hang') { hung.add(res); res.on('close', () => hung.delete(res)); return; }
      // `{ sequence: [...] }` answers successive requests to the same path with
      // successive entries, the last one repeating. Cursor pagination is the
      // reason: page one has to succeed for there to be a continuation to fail,
      // and a single override cannot say "then". Each entry is any of the forms
      // below, so a sequence can mix a body with a status.
      // `{ status, body }` answers with a specific status, which is how a
      // state reaches a conflict rather than a generic failure.
      let resolved = value;
      if (value !== null && typeof value === 'object' && Array.isArray(value.sequence)) {
        const seen = sequenceCounts.get(match) ?? 0;
        sequenceCounts.set(match, seen + 1);
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
      res.writeHead(200, { 'content-type': TYPES['.html'] });
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
    res.writeHead(200, { 'content-type': TYPES['.html'] });
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
        resetSequences() { sequenceCounts.clear(); },
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
