#!/usr/bin/env node
/**
 * MAVI visual-QA pass (section 26 of the UI/UX design specification).
 *
 *   node tools/web-visual-qa/run.mjs [--states a,b] [--widths 1366,2560] [--keep]
 *
 * Builds nothing: run `npm run build` in src/web/mavi-web first, or pass
 * --build. Screenshots are written to a scratch directory and are working
 * artefacts — section 26 forbids committing them, and .gitignore enforces it.
 *
 * Exit code 1 means an automated assertion failed. A clean exit is necessary
 * but not sufficient: the standard requires a person to look at the captures.
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { launch } from './cdp.mjs';
import { startServer } from './server.mjs';
import { FOCUS_ASSERTIONS, OVERLAY_READY, PAGE_ASSERTIONS, TARGET_SIZE_REPORT } from './assertions.mjs';
import { CONDITIONS, ensureFootage } from './footage.mjs';
import { STATES, WIDTHS } from './states.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, '..', '..', 'src', 'web', 'mavi-web');
const OUT = join(HERE, '.captures');

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index === -1 ? fallback : process.argv[index + 1];
}
const flag = (name) => process.argv.includes(`--${name}`);

const widths = String(arg('widths', WIDTHS.map((w) => w.width).join(',')))
  .split(',').map(Number)
  .map((w) => WIDTHS.find((entry) => entry.width === w) ?? { width: w, height: 900, label: String(w) });

const onlyStates = arg('states', null)?.split(',');
const states = STATES.filter((s) => !onlyStates || onlyStates.includes(s.name));

if (flag('build')) {
  process.stdout.write('building frontend…\n');
  execFileSync('npm', ['run', 'build'], { cwd: WEB, stdio: 'inherit' });
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

const MEDIA = join(OUT, 'media');
// Generate every clip before the browser starts. ffmpeg is invoked
// synchronously, so encoding on first request would block the event loop
// serving that request — and a media element that times out mid-load sits at
// readyState 1 while everything else looks fine.
const needed = new Set(STATES.map((state) => state.footage ?? 'saturated'));
for (const condition of needed) {
  if (!CONDITIONS[condition]) throw new Error(`unknown footage condition in states.mjs: ${condition}`);
  process.stdout.write(`  preparing ${condition} footage…\r`);
  ensureFootage(MEDIA, condition);
}
process.stdout.write(`  ${needed.size} footage condition(s) ready\n`);
let current = {};
let footage = 'saturated';
const { origin, close, releaseHung } = await startServer({
  distDir: join(WEB, 'dist'),
  fixtureDir: join(HERE, 'fixtures'),
  scenario: () => current,
  footage: () => ensureFootage(MEDIA, footage),
});

const browser = await launch();
const findings = [];
const knownSeen = [];
let checks = 0;

try {
  for (const state of states) {
    for (const viewport of widths) {
      current = state.api ?? {};
      footage = state.footage ?? 'saturated';
      await browser.viewport(viewport.width, viewport.height);
      // Tear the previous document down first. Chromium holds media decoders
      // across same-origin navigations, and after eighty-odd states a player
      // that loaded fine in isolation sits at readyState 1 for want of a free
      // decoder — which looks exactly like a product defect and is not one.
      await browser.goto('about:blank');
      await browser.goto(origin + state.path);
      // Let the query client settle and any media element lay itself out.
      await browser.evaluate('new Promise((r) => setTimeout(r, ' + (state.settleMs ?? 700) + '))');
      // A state may drive the page into the condition it wants to be looked at
      // in — seeking a player to where the overlay is actually drawn, say. The
      // result is not decorative: a renamed control or a clip that will not
      // decode would otherwise leave the harness photographing a blank first
      // frame and reporting the footage condition as passing.
      const where = `${state.name} @ ${viewport.label}`;
      const before = findings.length;

      let prepared = true;
      if (state.prepare) {
        prepared = Boolean(await browser.evaluate(state.prepare));
        await browser.evaluate('new Promise((r) => setTimeout(r, 600))');
        if (!prepared) findings.push(`${where}: prepare step did not run — the state was never reached`);
      }

      // A state must prove it reached the condition it claims. Without this a
      // slow retry silently turns the "unavailable" pass into a loading pass.
      if (state.expectText) {
        const seen = await browser.evaluate('document.body.innerText');
        for (const needle of [].concat(state.expectText)) {
          if (!seen.includes(needle)) findings.push(`${state.name} @ ${viewport.label}: never reached its state — expected text "${needle}"`);
        }
      }
      if (state.forbidText) {
        const seen = await browser.evaluate('document.body.innerText');
        for (const needle of [].concat(state.forbidText)) {
          if (seen.includes(needle)) findings.push(`${state.name} @ ${viewport.label}: showed "${needle}", which this state must never show`);
        }
      }

      // An overlay state must prove the overlay is actually on screen, with a
      // decoded frame under it, before its capture means anything.
      if (state.requireOverlay && prepared) {
        // Decoding and seeking take as long as they take; wait for the
        // condition rather than guessing a settle time, and fail only when it
        // genuinely never arrives.
        // Decoding and seeking take as long as they take, and a clip is
        // generated on its first use, so a seek can land before the media has
        // loaded. Re-run the preparation on each attempt rather than guessing a
        // settle time, and fail only when the condition genuinely never comes.
        let overlay = { ok: false, why: 'not checked' };
        for (let attempt = 0; attempt < 25; attempt += 1) {
          overlay = await browser.evaluate(OVERLAY_READY);
          if (overlay.ok) break;
          if (state.prepare) await browser.evaluate(state.prepare);
          await browser.evaluate('new Promise((r) => setTimeout(r, 500))');
        }
        if (!overlay.ok) findings.push(`${where}: overlay not ready for capture — ${overlay.why}`);
      }

      const page = await browser.evaluate(PAGE_ASSERTIONS);
      const focus = await browser.evaluate(FOCUS_ASSERTIONS);
      const small = await browser.evaluate(TARGET_SIZE_REPORT);
      checks += 1;

      // Known transitional defects (section 34.1) are recorded, not repaired
      // here: each belongs to the UI-n PR that owns that surface. Anything not
      // on the list is a finding.
      const known = (state.knownIssues ?? []).map((k) => new RegExp(k));
      const isKnown = (problem) => known.some((k) => k.test(problem));
      for (const problem of page.problems) {
        if (isKnown(problem)) { knownSeen.push(`${where}: ${problem}`); continue; }
        findings.push(`${where}: ${problem}`);
      }
      for (const problem of focus.problems) findings.push(`${where}: ${problem}`);
      for (const problem of browser.problems()) findings.push(`${where}: uncaught page error: ${problem}`);
      // A resource error is a finding only where the state did not ask for one.
      if (!state.api || !Object.values(state.api).includes('unavailable')) {
        for (const problem of browser.resourceErrors()) findings.push(`${where}: resource error: ${problem}`);
      }

      // Width discipline, checked only at the ultra-wide acceptance width where
      // the cap actually bites.
      if (viewport.width >= 2400 && page.pageWidth !== null) {
        if (state.fullWidth && page.pageWidth < viewport.width - 400) {
          findings.push(`${where}: declares full width but rendered ${page.pageWidth}px inside a ${viewport.width}px viewport`);
        }
        if (!state.fullWidth && page.pageWidth > 1700) {
          findings.push(`${where}: is not a full-width surface but rendered ${page.pageWidth}px — UI-1 must not widen it`);
        }
        if (state.fullWidth !== null && page.declaresFullWidth !== null && page.declaresFullWidth !== state.fullWidth) {
          findings.push(`${where}: expected page--full=${state.fullWidth}, found ${page.declaresFullWidth}`);
        }
      }

      writeFileSync(join(OUT, `${state.name}--${viewport.label}.png`), await browser.screenshot());
      const summary = { state: state.name, viewport: viewport.label, pageWidth: page.pageWidth, focusChecked: focus.checked, smallTargets: small };
      writeFileSync(join(OUT, `${state.name}--${viewport.label}.json`), JSON.stringify(summary, null, 2));

      // Let go of anything this state deliberately left hanging before the
      // next one needs the connection.
      releaseHung();

      process.stdout.write(`  ${findings.length > before ? 'FAIL' : ' ok '}  ${where}\n`);
    }
  }
} finally {
  await browser.close();
  await close();
}

process.stdout.write(`\n${checks} state/viewport combinations checked; captures in ${OUT}\n`);
if (knownSeen.length) {
  process.stdout.write(`${knownSeen.length} known transitional defect(s) seen (section 34.1, owned by a later UI PR):\n` +
    [...new Set(knownSeen.map((k) => k.replace(/ @ \S+/, '')))].map((k) => '  - ' + k).join('\n') + '\n');
}
if (findings.length) {
  process.stdout.write(`\n${findings.length} finding(s):\n` + findings.map((f) => '  - ' + f).join('\n') + '\n');
  if (!flag('keep')) process.exitCode = 1;
} else {
  process.stdout.write('No automated findings. Section 26 still requires a human pass over the captures.\n');
}
