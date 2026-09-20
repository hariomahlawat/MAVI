/**
 * Static host for the built frontend plus canned API responses.
 *
 * The visual-QA pass runs against the real production bundle rather than the
 * dev server: the bundle is what operators get, and serving `dist` avoids the
 * dev server's module URLs colliding with the `/api/` prefix the fixtures
 * answer on. Nothing here requires the application to be altered to make
 * inspection easier (section 26).
 */
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';

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
      const match = Object.keys(overrides).find((key) => path === key || path.startsWith(key + '/'));
      const value = match ? overrides[match] : undefined;

      if (value === 'unavailable') {
        res.writeHead(503, { 'content-type': 'application/problem+json' });
        res.end(JSON.stringify({ title: 'Service unavailable', detail: 'The upstream service did not respond.', code: 'upstream_unavailable' }));
        return;
      }
      if (value === 'hang') return; // deliberately never answers, to hold the loading state
      if (value !== undefined) {
        res.writeHead(200, { 'content-type': TYPES['.json'] });
        res.end(JSON.stringify(value));
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
      resolve({ origin: `http://127.0.0.1:${port}`, close: () => new Promise((done) => server.close(done)) });
    });
  });
}
