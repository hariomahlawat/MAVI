/**
 * A minimal Chrome DevTools Protocol client.
 *
 * Deliberately dependency-free. The repository has no browser-test framework,
 * and adding one would put a post-install browser download into a product whose
 * development setup runs `npm ci --offline` from a canonical cache (ADR-003).
 * Node 22 ships a global WebSocket, and Chromium is already a Development
 * prerequisite, so the harness needs neither.
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/** Chromium locations, most specific first. MAVI_CHROMIUM overrides all. */
const CANDIDATES = [
  process.env.MAVI_CHROMIUM,
  process.env.PLAYWRIGHT_BROWSERS_PATH && join(process.env.PLAYWRIGHT_BROWSERS_PATH, 'chromium-1194/chrome-linux/chrome'),
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/usr/bin/google-chrome',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].filter(Boolean);

function findChromium() {
  const found = CANDIDATES.find((p) => existsSync(p));
  if (!found) {
    throw new Error(
      'No Chromium found. Set MAVI_CHROMIUM to a Chrome, Chromium or Edge binary.\n' +
      'Tried:\n  ' + CANDIDATES.join('\n  '),
    );
  }
  return found;
}

export async function launch() {
  const binary = findChromium();
  const profile = mkdtempSync(join(tmpdir(), 'mavi-visual-qa-'));
  const child = spawn(binary, [
    '--headless=new',
    '--remote-debugging-port=0',
    `--user-data-dir=${profile}`,
    '--no-sandbox',
    '--disable-gpu',
    '--hide-scrollbars',
    '--force-color-profile=srgb',
    '--disable-lcd-text',
  ], { stdio: ['ignore', 'ignore', 'pipe'] });

  const wsUrl = await new Promise((resolve, reject) => {
    let buffer = '';
    const timer = setTimeout(() => reject(new Error('Chromium did not report a DevTools endpoint within 30s')), 30_000);
    child.stderr.on('data', (chunk) => {
      buffer += chunk;
      const match = buffer.match(/ws:\/\/[^\s]+/);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
    child.on('exit', (code) => { clearTimeout(timer); reject(new Error(`Chromium exited with ${code}`)); });
  });

  const socket = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', () => reject(new Error('Could not connect to Chromium')), { once: true });
  });

  let nextId = 0;
  const pending = new Map();
  const listeners = new Set();
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.id !== undefined) {
      const entry = pending.get(message.id);
      if (!entry) return;
      pending.delete(message.id);
      message.error ? entry.reject(new Error(`${message.method}: ${message.error.message}`)) : entry.resolve(message.result);
      return;
    }
    for (const listener of listeners) listener(message);
  });

  function send(method, params = {}, sessionId) {
    const id = ++nextId;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject, method });
      socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }

  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });

  const call = (method, params) => send(method, params, sessionId);
  await call('Page.enable');
  await call('Runtime.enable');
  await call('Log.enable');

  /**
   * Uncaught exceptions and console errors, kept apart. A state that induces a
   * 503 to exercise the unavailable path logs a resource error by design; an
   * uncaught exception is never by design.
   */
  let problems = [];
  let resourceErrors = [];
  listeners.add((message) => {
    if (message.sessionId !== sessionId) return;
    if (message.method === 'Runtime.exceptionThrown') {
      problems.push(message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text);
    }
    if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
      const entry = message.params.entry;
      (entry.source === 'network' ? resourceErrors : problems).push(entry.text + (entry.url ? ' — ' + entry.url : ''));
    }
  });

  return {
    async viewport(width, height) {
      await call('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
    },
    async goto(url) {
      problems = [];
      resourceErrors = [];
      await call('Page.navigate', { url });
      await new Promise((resolve) => {
        const onLoad = (message) => {
          if (message.sessionId === sessionId && message.method === 'Page.loadEventFired') {
            listeners.delete(onLoad);
            resolve();
          }
        };
        listeners.add(onLoad);
        setTimeout(() => { listeners.delete(onLoad); resolve(); }, 15_000);
      });
    },
    async evaluate(expression) {
      const { result, exceptionDetails } = await call('Runtime.evaluate', {
        expression, awaitPromise: true, returnByValue: true,
      });
      if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
      return result.value;
    },
    async screenshot() {
      const { data } = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      return Buffer.from(data, 'base64');
    },
    problems: () => problems.slice(),
    resourceErrors: () => resourceErrors.slice(),
    async close() {
      try { socket.close(); } catch { /* already gone */ }
      // Wait for the process to go before removing its profile: Chromium is
      // still writing into it as it shuts down, and rmSync would race.
      await new Promise((resolve) => {
        if (child.exitCode !== null) { resolve(); return; }
        child.once('exit', resolve);
        child.kill();
        setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 5_000);
      });
      try {
        rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
      } catch {
        // A leftover temp profile is untidy, not a failed QA pass.
      }
    },
  };
}
