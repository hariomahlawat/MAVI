/**
 * The run end to end (cold review, item 1): a state the harness cannot
 * establish is a harness fault at every tier — exit 2, recorded with its stage
 * and reason, its capture kept but labelled invalid and left out of the valid
 * count — and a later case that succeeds does not erase it.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { e2eIt } from './browser.mjs';

const RUN = fileURLToPath(new URL('../run.mjs', import.meta.url));
const REGISTERED = new URL('../states.mjs', import.meta.url).href;

let dir;
before(() => { dir = mkdtempSync(join(tmpdir(), 'mavi-vqa-run-')); });
after(() => { rmSync(dir, { recursive: true, force: true }); });

describe('a held request is released only once its document is gone', () => {
  const e2e = e2eIt(it);
  const RUN = fileURLToPath(new URL('../run.mjs', import.meta.url));
  let out;
  before(() => { out = mkdtempSync(join(tmpdir(), 'mavi-vqa-order-')); });
  after(() => { rmSync(out, { recursive: true, force: true }); });

  e2e('reaches a degraded Ledger right after the loading Ledger that held its request, on one lane', () => {
    // The loading state holds /api/videos; the degraded state answers each
    // row's status once and then fails (a sequenced fixture). Released while
    // the loading page was alive, its retry consumed the first answer, and
    // the degraded state was never reached: an order a sharded sweep runs.
    const run = spawnSync(process.execPath, [RUN, '--states', 'processing-queue-loading,processing-queue-row-degraded', '--tiers', 'A', '--widths', '1366', '--zoom', 'none', '--workers', '1'], {
      env: { ...process.env, MAVI_VQA_OUT: out }, encoding: 'utf8', timeout: 180_000,
    });
    assert.equal(run.error, undefined, 'the run hung');
    assert.equal(run.status, 0, run.stdout + run.stderr);
    const results = JSON.parse(readFileSync(join(out, 'results.json'), 'utf8'));
    assert.deepEqual(results.executions.notReached, []);
    assert.equal(results.cases.filter((c) => c.valid).length, 2);
  });
});

describe('a state the harness cannot reach', () => {
  const e2e = e2eIt(it);
  e2e('fails the run with a harness fault at Tier C, and a later success does not erase it', () => {
    const module = join(dir, 'states.mjs');
    // The registered states plus one whose preparation can never succeed,
    // listed first so the case that follows it succeeds after the failure.
    writeFileSync(module, `export * from ${JSON.stringify(REGISTERED)};
import { STATES as REGISTERED } from ${JSON.stringify(REGISTERED)};
export const STATES = [
  { name: 'test-unreachable', path: '/videos', fullWidth: true, archetype: 'ledger', prepare: '(() => false)()' },
  ...REGISTERED.filter((state) => state.name === 'videos'),
];
`);
    const out = join(dir, 'captures');
    const run = spawnSync(process.execPath, [RUN, '--states', 'test-unreachable,videos', '--tiers', 'C', '--widths', '390', '--workers', '1'], {
      env: { ...process.env, MAVI_VQA_STATES_MODULE: module, MAVI_VQA_OUT: out },
      encoding: 'utf8',
      timeout: 120_000,
    });
    assert.equal(run.error, undefined, 'the run hung');
    assert.equal(run.status, 2, run.stdout + run.stderr);
    const results = JSON.parse(readFileSync(join(out, 'results.json'), 'utf8'));

    // Machine-readable: state, anchor, tier, stage and reason.
    assert.deepEqual(results.executions.notReached, [{
      state: 'test-unreachable', viewport: '390x844', tier: 'C', stage: 'preparation', reason: 'preparation reported that the state was not reached',
    }]);
    assert.ok(results.harnessErrors.some((e) => /^test-unreachable @ 390x844 \(Tier C\): the declared state was not reached at preparation/.test(e)));

    // A run under a states override is labelled and never a full sweep.
    assert.equal(results.statesModule, module);
    assert.equal(results.fullSweep, false);

    // Not a finding, so no manifest severity can soften it.
    assert.ok(!results.findingsList.some((f) => f.state === 'test-unreachable' && /state/.test(f.rule)));

    // The capture is kept for diagnosis, labelled, and not counted as valid.
    const unreached = results.cases.find((c) => c.state === 'test-unreachable');
    assert.equal(unreached.valid, false);
    assert.equal(unreached.capture, 'test-unreachable--390x844--UNREACHED.png');
    assert.ok(existsSync(join(out, unreached.capture)));
    assert.equal(unreached.perf.cls.status, 'failed');

    // The later case succeeded and is the only valid capture.
    const videos = results.cases.find((c) => c.state === 'videos');
    assert.equal(videos.valid, true);
    assert.equal(results.executions.validCaptures, 1);
    assert.equal(results.executions.byTier.C.invalid, 1);
  });
});
