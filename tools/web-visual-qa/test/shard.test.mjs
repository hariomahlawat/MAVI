/**
 * Sharding the sweep (CI): a deterministic partition of the plan into shards
 * that each run their cases alone, and an aggregate that proves the plan ran
 * exactly once and applies the sweep-wide checks a shard cannot. The
 * aggregate's verdict must be the one an unsharded run gives: the same
 * cross-case function (engine.sweepChecks) serves both.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
// These runs count cases of the plan's anchors: the X1 text-spacing lane (its
// own tests in a11y.test.mjs) is left out so the counts stay the anchors'.
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { caseKey, createLedger, partitionCases, planCases, sweepChecks } from '../engine.mjs';
import { RULES } from '../manifest.mjs';
import { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf, ZOOM } from '../states.mjs';
import { e2eIt, testGroup, unitBlock } from './browser.mjs';

const PAIRS = [['cameras-loading', 'cameras'], ['videos-loading', 'videos'], ['processing-queue-loading', 'processing-queue']];
const plan = () => planCases({ states: STATES, anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf, zoom: ZOOM });

describe('partitioning the plan into shards', unitBlock(), () => {
  it('assigns every planned case to exactly one of n shards, deterministically', () => {
    const { cases } = plan();
    for (const count of [1, 3, 4, 7]) {
      const seen = new Map();
      for (let index = 0; index < count; index += 1) {
        const shard = partitionCases(cases, { index, count, pairs: PAIRS });
        assert.deepEqual(shard.planned, cases.map(caseKey));
        for (const key of shard.selectedKeys) seen.set(key, (seen.get(key) ?? 0) + 1);
        // The same call gives the same shard.
        assert.deepEqual(partitionCases(cases, { index, count, pairs: PAIRS }).selectedKeys, shard.selectedKeys);
      }
      assert.equal(seen.size, cases.length, `n=${count}: every case selected`);
      assert.ok([...seen.values()].every((n) => n === 1), `n=${count}: no case selected twice`);
    }
  });

  it('keeps a state\'s cases together, a loading pair in one shard, and the shards within a few per cent of each other', () => {
    const { cases } = plan();
    const count = 4;
    const sizes = [];
    const shardOfState = new Map();
    for (let index = 0; index < count; index += 1) {
      const { selected } = partitionCases(cases, { index, count, pairs: PAIRS });
      sizes.push(selected.length);
      for (const c of selected) {
        const was = shardOfState.get(c.state.name);
        assert.ok(was === undefined || was === index, `${c.state.name} is split across shards ${was} and ${index}`);
        shardOfState.set(c.state.name, index);
      }
    }
    for (const [a, b] of PAIRS) assert.equal(shardOfState.get(a), shardOfState.get(b), `${a} and ${b} are in different shards`);
    const mean = cases.length / count;
    for (const size of sizes) assert.ok(Math.abs(size - mean) / mean < 0.15, `shard sizes ${sizes} are not balanced around ${mean}`);
  });

  it('refuses a shard outside 0..n-1 and a count below one', () => {
    const { cases } = plan();
    assert.throws(() => partitionCases(cases, { index: 4, count: 4 }), /shard index must be 0\.\.3/);
    assert.throws(() => partitionCases(cases, { index: 0, count: 0 }), /shard count must be a positive integer/);
    assert.throws(() => partitionCases(cases, { index: -1, count: 2 }), /shard index must be 0\.\.1/);
  });

  it('names the test groups deterministically and places every end-to-end test in exactly one', () => {
    const saved = process.env.MAVI_VQA_TEST_GROUP;
    try {
      delete process.env.MAVI_VQA_TEST_GROUP;
      assert.equal(testGroup().kind, 'all');
      process.env.MAVI_VQA_TEST_GROUP = 'unit';
      assert.equal(testGroup().unit, true);
      assert.equal(testGroup().e2e(0), false);
      const where = new Map();
      for (let i = 0; i < 3; i += 1) {
        process.env.MAVI_VQA_TEST_GROUP = `e2e-${i}/3`;
        const group = testGroup();
        assert.equal(group.unit, false);
        for (let ordinal = 0; ordinal < 14; ordinal += 1) if (group.e2e(ordinal)) where.set(ordinal, [...(where.get(ordinal) ?? []), i]);
      }
      for (let ordinal = 0; ordinal < 14; ordinal += 1) assert.deepEqual(where.get(ordinal), [ordinal % 3]);
      process.env.MAVI_VQA_TEST_GROUP = 'e2e-3/3';
      assert.throws(() => testGroup(), /0 <= i < n/);
    } finally {
      if (saved === undefined) delete process.env.MAVI_VQA_TEST_GROUP; else process.env.MAVI_VQA_TEST_GROUP = saved;
    }
  });
});

describe('the sweep-wide checks over a union of results', unitBlock(), () => {
  const result = (state, viewport, tier, extra = {}) => ({ state, viewport, tier, kind: 'anchor', attempt: 1, reached: true, valid: true, surface: 'videos', ...extra });
  it('faults a case that never ran and one that was not reached, whatever shard it came from', () => {
    const ledger = createLedger(RULES);
    const cases = [{ key: 'a' }, { key: 'b' }, { key: 'c' }];
    const results = [result('videos', '1366x768', 'A'), result('videos', '390x844', 'C', { reached: false, valid: false, unreached: { stage: 'preparation', reason: 'no' } })];
    const { faults } = sweepChecks({ results, cases, errored: [], ledger, surfaces: [], fullSweep: false });
    assert.ok(faults.some((f) => /1 of 3 scheduled case\(s\) never ran/.test(f)), faults.join('\n'));
    assert.ok(faults.some((f) => /videos @ 390x844 \(Tier C\): the declared state was not reached at preparation: no/.test(f)), faults.join('\n'));
  });

  it('compares a loading Ledger with its table across shards, and records the shift through the ledger', () => {
    const ledger = createLedger(RULES);
    const results = [
      result('videos-loading', '1366x768', 'A', { workspace: { firstRowTop: 100 } }),
      result('videos', '1366x768', 'A', { workspace: { firstRowTop: 108 } }),
    ];
    const { faults } = sweepChecks({ results, cases: [{}, {}], errored: [], ledger, surfaces: [], loadingPairs: PAIRS, fullSweep: false });
    assert.deepEqual(faults, []);
    assert.equal(ledger.findings.length, 1);
    assert.match(ledger.findings[0].message, /first skeleton row at 100px, first videos row at 108px/);
    assert.equal(ledger.coverage['ledger.loading-geometry'].A.evaluated, 1);
  });

  it('applies the full-sweep obligations only when every shard ran a complete selection', () => {
    const ledger = createLedger(RULES);
    const results = [result('videos', '1366x768', 'A')];
    const partial = sweepChecks({ results, cases: [{}], errored: [], ledger, surfaces: ['videos'], fullSweep: false });
    assert.deepEqual(partial.faults, []);
    const full = sweepChecks({ results, cases: [{}], errored: [], ledger, surfaces: ['videos'], fullSweep: true });
    assert.ok(full.faults.some((f) => /a11y.zoom-200: the full sweep has no valid 200% zoom capture of videos/.test(f)), full.faults.join('\n'));
  });
});

describe('shards and their aggregate, end to end', () => {
  const e2e = e2eIt(it);
  const RUN = fileURLToPath(new URL('../run.mjs', import.meta.url));
  const AGGREGATE = fileURLToPath(new URL('../aggregate.mjs', import.meta.url));
  let dir;
  before(() => { dir = mkdtempSync(join(tmpdir(), 'mavi-vqa-shard-')); });
  after(() => { rmSync(dir, { recursive: true, force: true }); });
  const runShard = (index, count, out, extra = []) => spawnSync(process.execPath, [RUN, '--states', 'videos,videos-loading', '--tiers', 'C', '--widths', '390', '--workers', '1', '--text-spacing', 'none', '--shard', `${index}/${count}`, ...extra], {
    env: { ...process.env, MAVI_VQA_OUT: out }, encoding: 'utf8', timeout: 180_000,
  });
  const aggregate = (out, files) => spawnSync(process.execPath, [AGGREGATE, '--out', out, ...files], { encoding: 'utf8', timeout: 60_000 });

  e2e('keeps a loading pair in one shard, refuses an empty shard, and faults an aggregate missing a shard', () => {
    const outs = [join(dir, 's0'), join(dir, 's1')];
    const runs = outs.map((out, index) => runShard(index, 2, out));
    // The pair lands in one shard; the other selects nothing and is refused
    // (exit 2) rather than reporting an empty success.
    const statuses = runs.map((r) => r.status).sort();
    assert.deepEqual(statuses, [0, 2], runs.map((r) => r.stdout + r.stderr).join('\n'));
    const empty = runs.find((r) => r.status === 2);
    assert.match(empty.stderr, /selects no case of 2/);
    const ran = outs[runs.findIndex((r) => r.status === 0)];
    const shard = JSON.parse(readFileSync(join(ran, 'results.json'), 'utf8'));
    assert.equal(shard.fullSweep, false);
    assert.equal(shard.shard.planned.length, 2);
    assert.equal(shard.shard.selected.length, 2);
    // One shard of two is not the plan: the aggregate faults, never passes.
    const only = aggregate(join(dir, 'agg-one'), [join(ran, 'results.json')]);
    assert.equal(only.status, 2, only.stdout + only.stderr);
    assert.match(only.stdout, /shard indices \[(0|1)\] are not 0\.\.1 each exactly once/);
  });

  e2e('aggregates a two-state, two-shard plan: both cases exactly once, no fault, the sweep-wide checks applied', () => {
    // Two states with no pairing, so each shard holds one.
    const run = (index, out) => spawnSync(process.execPath, [RUN, '--states', 'videos,cameras', '--tiers', 'C', '--widths', '390', '--workers', '1', '--text-spacing', 'none', '--shard', `${index}/2`], {
      env: { ...process.env, MAVI_VQA_OUT: out }, encoding: 'utf8', timeout: 180_000,
    });
    const outs = [join(dir, 'p0'), join(dir, 'p1')];
    const runs = outs.map((out, index) => run(index, out));
    for (const r of runs) assert.equal(r.status, 0, r.stdout + r.stderr);
    const files = outs.map((out) => join(out, 'results.json'));
    const agg = aggregate(join(dir, 'agg'), files);
    assert.equal(agg.status, 0, agg.stdout + agg.stderr);
    const results = JSON.parse(readFileSync(join(dir, 'agg', 'results.json'), 'utf8'));
    assert.equal(results.fullSweep, false);
    assert.equal(results.executions.planned, 2);
    assert.equal(results.executions.validCaptures, 2);
    assert.deepEqual(results.harnessErrors, []);
    assert.equal(results.cases.length, 2);
    // A shard counted twice, a shard's plan tampered with, a case removed: each a harness fault.
    const twice = aggregate(join(dir, 'agg-twice'), [files[0], files[0]]);
    assert.equal(twice.status, 2);
    assert.match(twice.stdout, /not 0\.\.1 each exactly once/);
    const tampered = JSON.parse(readFileSync(files[1], 'utf8'));
    tampered.shard.planned = tampered.shard.planned.slice(0, 1);
    writeFileSync(join(dir, 'tampered.json'), JSON.stringify(tampered));
    const disagree = aggregate(join(dir, 'agg-tampered'), [files[0], join(dir, 'tampered.json')]);
    assert.equal(disagree.status, 2);
    assert.match(disagree.stdout, /planned case list differs/);
    const lost = JSON.parse(readFileSync(files[1], 'utf8'));
    lost.cases = [];
    writeFileSync(join(dir, 'lost.json'), JSON.stringify(lost));
    const missing = aggregate(join(dir, 'agg-lost'), [files[0], join(dir, 'lost.json')]);
    assert.equal(missing.status, 2);
    assert.match(missing.stdout, /ran 0 time\(s\), not exactly once/);
    assert.ok(existsSync(join(dir, 'agg-lost', 'results.json')));
  });
});
