// The pinned-order (`forward`) scheduler answers in the order requests reach
// it, one at a time, a spacing apart, and is generation-clean: a reset leaves
// nothing of the previous case — no queued answer, no pump timer — that could
// shift the next case's order or timing. Run on a virtual clock, so timing is
// exact. (Its input order is the page's issue order: admission.mjs.)
import { strict as assert } from 'node:assert';
import { describe, it } from 'node:test';
import { RESPONSE_SPACING_MS, createResponseScheduler } from '../server.mjs';
import { unitBlock } from './browser.mjs';

/**
 * A virtual clock: timers run only when advanced, in due order. `delay(ms, n)`
 * makes the n-th timer of that duration run late (a busy event loop);
 * `skipTo(t)` moves time on WITHOUT running the timers that fall due, and
 * `runDue()` then runs them, late, at the current time. With
 * `honourClears: false` a cleared timer still runs (a callback that cannot be
 * withdrawn), so a test can prove a stale callback is harmless by itself.
 */
function virtualClock({ delay = () => 0, honourClears = true } = {}) {
  let now = 0; let nextId = 1;
  const timers = new Map();
  const counts = new Map();
  const nextDue = (t) => [...timers.entries()].filter(([, x]) => x.at <= t).sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
  return {
    now: () => now,
    setTimer: (fn, ms) => {
      const id = nextId++;
      const n = counts.get(ms) ?? 0; counts.set(ms, n + 1);
      timers.set(id, { at: now + ms + delay(ms, n), fn });
      return id;
    },
    clearTimer: (id) => { if (honourClears) timers.delete(id); },
    pendingTimers: () => timers.size,
    advanceTo(t) {
      for (;;) {
        const due = nextDue(t);
        if (!due) break;
        timers.delete(due[0]); now = Math.max(now, due[1].at); due[1].fn();
      }
      now = Math.max(now, t);
    },
    skipTo(t) { now = Math.max(now, t); },
    runDue() {
      for (;;) {
        const due = nextDue(now);
        if (!due) break;
        timers.delete(due[0]); due[1].fn();
      }
    },
  };
}

function rig(clockOptions) {
  const clock = virtualClock(clockOptions);
  const scheduler = createResponseScheduler({ setTimer: clock.setTimer, clearTimer: clock.clearTimer, now: clock.now });
  const answered = []; const dropped = [];
  const request = (name) => scheduler.submit(() => answered.push([name, clock.now()]), () => dropped.push(name), name);
  return { clock, scheduler, answered, dropped, request };
}

/** The next case: requests at the given offsets from `start`; answers relative to `start`. */
function nextCase(r, start, plan) {
  for (const [name, at] of plan) { r.clock.advanceTo(start + at); r.request(name); }
  r.clock.advanceTo(start + 5000);
  return r.answered.filter(([name]) => name.startsWith('B')).map(([name, t]) => [name, t - start]);
}

const CASE_B = [['B1', 0], ['B2', 10], ['B3', 30]];

describe('the forward scheduler', unitBlock(), () => {
  it('answers in submission order, the first at once, each next a spacing after the previous send', () => {
    const r = rig();
    r.request('a'); r.clock.advanceTo(5); r.request('b'); r.clock.advanceTo(300); r.request('c'); r.clock.advanceTo(2000);
    assert.deepEqual(r.answered, [['a', 0], ['b', RESPONSE_SPACING_MS], ['c', 300]]);
    assert.deepEqual(r.scheduler.pending(), { queued: 0, timers: 0 });
  });

  it('a late timer never brings the next answer closer: spacing is measured from each send', () => {
    const r = rig({ delay: (ms, n) => (n === 0 ? 70 : 0) });
    ['a', 'b', 'c'].forEach((name) => r.request(name));
    r.clock.advanceTo(2000);
    assert.deepEqual(r.answered, [['a', 0], ['b', RESPONSE_SPACING_MS + 70], ['c', 2 * RESPONSE_SPACING_MS + 70]]);
  });

  it('over 2000 seeded arrival patterns: every request answered exactly once, in submission order, sends at least a spacing apart, nothing left pending', () => {
    let seed = 20261016;
    const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
    for (let n = 0; n < 2000; n += 1) {
      const delays = Array.from({ length: 10 }, () => [0, 0, 1, 30, 200][Math.floor(rand() * 5)]);
      const r = rig({ delay: (ms, k) => delays[k] ?? 0 });
      const plan = []; let at = 0;
      for (let i = 0, count = 1 + Math.floor(rand() * 8); i < count; i += 1) { at += [0, 1, 5, 99, 150, 400][Math.floor(rand() * 6)]; plan.push([`r${i}`, at]); }
      for (const [name, t] of plan) { r.clock.advanceTo(t); r.request(name); }
      r.clock.advanceTo(at + 20000);
      const context = JSON.stringify({ plan, delays, answered: r.answered });
      assert.deepEqual(r.answered.map(([name]) => name), plan.map(([name]) => name), context);
      for (let i = 1; i < r.answered.length; i += 1) assert.ok(r.answered[i][1] - r.answered[i - 1][1] >= RESPONSE_SPACING_MS, context);
      assert.deepEqual(r.scheduler.pending(), { queued: 0, timers: 0 }, context);
      assert.equal(r.clock.pendingTimers(), 0, context);
    }
  });
});

describe('the forward scheduler is generation-clean', unitBlock(), () => {
  it('a reset mid-queue cancels the pump and drops the queue; the next case is answered as on a fresh scheduler', () => {
    const expected = nextCase(rig(), 0, CASE_B);
    assert.deepEqual(expected, [['B1', 0], ['B2', RESPONSE_SPACING_MS], ['B3', 2 * RESPONSE_SPACING_MS]]);
    const r = rig();
    ['A1', 'A2', 'A3', 'A4'].forEach((name) => r.request(name));
    r.clock.advanceTo(50); // A1 sent at 0; A2..A4 queued; the pump's timer is due at 120
    r.scheduler.reset();
    assert.deepEqual(r.scheduler.pending(), { queued: 0, timers: 0 });
    assert.equal(r.clock.pendingTimers(), 0, 'the previous generation left a timer');
    assert.deepEqual(r.dropped, ['A2', 'A3', 'A4']);
    assert.deepEqual(nextCase(r, 60, CASE_B), expected, 'the previous case shifted the next one');
    assert.deepEqual(r.answered.filter(([n]) => n.startsWith('A')), [['A1', 0]]);
  });

  it('a stale pump callback that runs anyway (its clear withdrawn) has no effect on the next generation', () => {
    const expected = nextCase(rig(), 0, CASE_B);
    const r = rig({ honourClears: false });
    ['A1', 'A2'].forEach((name) => r.request(name));
    r.clock.skipTo(50);
    r.scheduler.reset();
    r.clock.runDue();
    assert.deepEqual(nextCase(r, 60, CASE_B), expected);
    assert.deepEqual(r.dropped, ['A2']);
  });
});
