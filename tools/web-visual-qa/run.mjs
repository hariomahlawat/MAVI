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
import { FOCUS_ASSERTIONS, PAGE_ASSERTIONS, TARGET_SIZE_REPORT } from './assertions.mjs';
import { ensureFootage } from './footage.mjs';
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
let current = {};
let footage = 'saturated';
const { origin, close } = await startServer({
  distDir: join(WEB, 'dist'),
  fixtureDir: join(HERE, 'fixtures'),
  scenario: () => current,
  footage: () => ensureFootage(MEDIA, footage),
});

const browser = await launch();
const findings = [];
let checks = 0;

try {
  for (const state of states) {
    for (const viewport of widths) {
      current = state.api ?? {};
      footage = state.footage ?? 'saturated';
      await browser.viewport(viewport.width, viewport.height);
      await browser.goto(origin + state.path);
      // Let the query client settle and any media element lay itself out.
      await browser.evaluate('new Promise((r) => setTimeout(r, ' + (state.settleMs ?? 700) + '))');
      // A state may drive the page into the condition it wants to be looked at
      // in — seeking a player to where the overlay is actually drawn, say.
      if (state.prepare) {
        await browser.evaluate(state.prepare);
        await browser.evaluate('new Promise((r) => setTimeout(r, 600))');
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

      const page = await browser.evaluate(PAGE_ASSERTIONS);
      const focus = await browser.evaluate(FOCUS_ASSERTIONS);
      const small = await browser.evaluate(TARGET_SIZE_REPORT);
      checks += 1;

      const where = `${state.name} @ ${viewport.label}`;
      for (const problem of page.problems) findings.push(`${where}: ${problem}`);
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

      process.stdout.write(`  ${page.problems.length + focus.problems.length ? 'FAIL' : ' ok '}  ${where}\n`);
    }
  }
} finally {
  await browser.close();
  await close();
}

process.stdout.write(`\n${checks} state/viewport combinations checked; captures in ${OUT}\n`);
if (findings.length) {
  process.stdout.write(`\n${findings.length} finding(s):\n` + findings.map((f) => '  - ' + f).join('\n') + '\n');
  if (!flag('keep')) process.exitCode = 1;
} else {
  process.stdout.write('No automated findings. Section 26 still requires a human pass over the captures.\n');
}
