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
  // An explicit override is used or refused, never silently replaced by
  // whichever browser happens to be installed.
  const override = process.env.MAVI_CHROMIUM;
  if (override) {
    if (!existsSync(override)) throw new Error(`MAVI_CHROMIUM is set to ${override}, which does not exist.`);
    return override;
  }
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

  // Until the browser is fully up the caller has no browser object to close,
  // so a failure on the way owns the cleanup: the process and its profile go
  // here, or they would keep the harness alive past the fault it reports.
  try {
    return await connect(child, profile);
  } catch (error) {
    await new Promise((resolve) => {
      if (child.exitCode !== null || child.signalCode !== null) { resolve(); return; }
      child.once('exit', resolve);
      try { child.kill('SIGKILL'); } catch { resolve(); }
      setTimeout(resolve, 5_000).unref();
    });
    try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }); } catch { /* untidy, not fatal */ }
    throw error;
  }
}

async function connect(child, profile) {
  const wsUrl = await new Promise((resolve, reject) => {
    let buffer = '';
    const timer = setTimeout(() => reject(new Error('Chromium did not report a DevTools endpoint within 30s')), 30_000);
    child.stderr.on('data', (chunk) => {
      buffer += chunk;
      const match = buffer.match(/ws:\/\/[^\s]+/);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
    child.on('exit', (code) => { clearTimeout(timer); reject(new Error(`Chromium exited with ${code}`)); });
    // A binary that cannot be started at all (a directory, no permission).
    child.on('error', (error) => { clearTimeout(timer); reject(new Error(`Chromium could not be started: ${error.message}`)); });
  });

  const socket = new WebSocket(wsUrl);
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Chromium accepted no DevTools connection within 30s')), 30_000);
      socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Could not connect to Chromium')); }, { once: true });
    });
  } catch (error) {
    try { socket.close(); } catch { /* never opened */ }
    throw error;
  }

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

  /** No call waits forever: a hung page or a crashed browser fails the case. */
  const CALL_TIMEOUT_MS = 30_000;
  function send(method, params = {}, sessionId) {
    const id = ++nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`${method}: no answer from Chromium within ${CALL_TIMEOUT_MS}ms`));
      }, CALL_TIMEOUT_MS);
      pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
        method,
      });
      socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
  socket.addEventListener('close', () => {
    for (const [id, entry] of pending) { pending.delete(id); entry.reject(new Error(`${entry.method}: Chromium closed the connection`)); }
  });

  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });

  const call = (method, params) => send(method, params, sessionId);
  await call('Page.enable');
  await call('Runtime.enable');
  await call('Log.enable');
  await call('DOM.enable');
  await call('CSS.enable');
  // Each case starts from the network as well as from a blank document: with
  // the cache on, a request a previous case held open (a loading state) kept
  // its cache entry locked, and the next case's request for the same URL
  // waited behind it.
  await call('Network.enable');
  await call('Network.setCacheDisabled', { cacheDisabled: true });

  /**
   * Uncaught exceptions and console errors, kept apart. A state that induces a
   * 503 to exercise the unavailable path logs a resource error by design; an
   * uncaught exception is never by design.
   */
  let problems = [];
  let resourceErrors = [];
  listeners.add((message) => {
    if (message.sessionId !== sessionId) return;
    // A native dialog would halt the page and every call after it, so none is
    // left open. Only `beforeunload` — the "Leave site?" a dirty editor raises
    // as the harness leaves the page — is accepted. Any other (`alert`,
    // `confirm`, `prompt`) is a native dialog §15 forbids: it is dismissed —
    // never answered yes on the operator's behalf — and reported as a page
    // problem, so the regression fails the state instead of passing it.
    if (message.method === 'Page.javascriptDialogOpening') {
      const { type, message: text } = message.params;
      if (type !== 'beforeunload') problems.push(`a native ${type} dialog opened ("${String(text ?? '').slice(0, 80)}"): §15 forbids native dialogs`);
      call('Page.handleJavaScriptDialog', { accept: type === 'beforeunload' }).catch(() => {});
      return;
    }
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
      const { data } = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false, optimizeForSpeed: true });
      return Buffer.from(data, 'base64');
    },
    /** A script run in every new document before any of the page's own. */
    async addInitScript(source) {
      await call('Page.addScriptToEvaluateOnNewDocument', { source });
    },
    /**
     * The platform fonts the browser actually used to render the text inside
     * the first element matching `selector` (CSS.getPlatformFontsForNode):
     * glyph-level evidence, not the declared font-family stack.
     */
    async platformFonts(selector) {
      const { root } = await call('DOM.getDocument', { depth: 0 });
      const { nodeId } = await call('DOM.querySelector', { nodeId: root.nodeId, selector });
      if (!nodeId) return null;
      const { fonts } = await call('CSS.getPlatformFontsForNode', { nodeId });
      return fonts.map((font) => ({ family: font.familyName, postScriptName: font.postScriptName, glyphs: font.glyphCount, custom: font.isCustomFont }));
    },
    /** A real key press through the input pipeline, as an operator makes it. */
    async press(key, code = key) {
      const keyCode = { Escape: 27, Tab: 9, Enter: 13 }[key] ?? 0;
      await call('Input.dispatchKeyEvent', { type: 'keyDown', key, code, windowsVirtualKeyCode: keyCode });
      await call('Input.dispatchKeyEvent', { type: 'keyUp', key, code, windowsVirtualKeyCode: keyCode });
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
        setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 5_000).unref();
      });
      try {
        rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
      } catch {
        // A leftover temp profile is untidy, not a failed QA pass.
      }
    },
  };
}
