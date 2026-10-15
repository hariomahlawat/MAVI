// The pinned-order scheduler is generation-clean (owner review, 2026-10-14): a
// reset leaves nothing of the previous case — no queued answer, no burst being
// gathered, no pump or gather timer — that could shift the next case's order,
// grouping or timing. Run on a virtual clock, so timing is exact.
import { strict as assert } from 'node:assert';
import { describe, it } from 'node:test';
import { BURST_GATHER_MS, RESPONSE_SPACING_MS, createResponseScheduler } from '../server.mjs';
import { unitBlock } from './browser.mjs';

/** A virtual clock: timers run only when advanced, in due order. */
function virtualClock() {
  let now = 0; let nextId = 1;
  const timers = new Map();
  return {
    now: () => now,
    setTimer: (fn, ms) => { const id = nextId++; timers.set(id, { at: now + ms, fn }); return id; },
    clearTimer: (id) => { timers.delete(id); },
    pendingTimers: () => timers.size,
    advanceTo(t) {
      for (;;) {
        const due = [...timers.entries()].filter(([, x]) => x.at <= t).sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
        if (!due) break;
        timers.delete(due[0]); now = due[1].at; due[1].fn();
      }
      now = t;
    },
  };
}

function rig(order) {
  const clock = virtualClock();
  const scheduler = createResponseScheduler({ order, setTimer: clock.setTimer, clearTimer: clock.clearTimer, now: clock.now });
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

describe('the pinned-order scheduler is generation-clean', unitBlock(), () => {
  it('forward: a reset mid-queue cancels the pump; the next case is answered as on a fresh server', () => {
    const fresh = rig('forward');
    const expected = nextCase(fresh, 0, CASE_B);
    assert.deepEqual(expected, [['B1', 0], ['B2', RESPONSE_SPACING_MS], ['B3', 2 * RESPONSE_SPACING_MS]]);

    const r = rig('forward');
    ['A1', 'A2', 'A3', 'A4'].forEach((name) => r.request(name));
    r.clock.advanceTo(50); // A1 sent at 0; A2..A4 queued; the pump's timer is due at 120
    r.scheduler.reset();
    assert.deepEqual(r.scheduler.pending(), { queued: 0, gathering: 0, timers: 0 });
    assert.equal(r.clock.pendingTimers(), 0, 'the previous generation left a timer');
    assert.deepEqual(r.dropped, ['A2', 'A3', 'A4']);
    assert.deepEqual(nextCase(r, 60, CASE_B), expected, 'the previous case shifted the next one');
    assert.deepEqual(r.answered.filter(([n]) => n.startsWith('A')), [['A1', 0]]);
  });

  it('reverse: a reset while a burst is gathering cancels it; the next case groups and orders as on a fresh server', () => {
    const fresh = rig('reverse');
    const expected = nextCase(fresh, 0, CASE_B);
    assert.deepEqual(expected, [['B3', BURST_GATHER_MS], ['B2', BURST_GATHER_MS + RESPONSE_SPACING_MS], ['B1', BURST_GATHER_MS + 2 * RESPONSE_SPACING_MS]]);

    const r = rig('reverse');
    r.request('A1'); r.clock.advanceTo(20); r.request('A2');
    r.clock.advanceTo(30); // the burst's gather timer is due at 100: it would take B1, B2 into A's burst
    r.scheduler.reset();
    assert.deepEqual(r.scheduler.pending(), { queued: 0, gathering: 0, timers: 0 });
    assert.equal(r.clock.pendingTimers(), 0);
    assert.deepEqual(r.dropped, ['A1', 'A2']);
    assert.deepEqual(nextCase(r, 40, CASE_B), expected);
    assert.deepEqual(r.answered.filter(([n]) => n.startsWith('A')), []);
  });

  it('reverse: a reset while a released burst is still being sent drops its remainder and its spacing', () => {
    const fresh = rig('reverse');
    const expected = nextCase(fresh, 0, CASE_B);
    const r = rig('reverse');
    ['A1', 'A2', 'A3'].forEach((name) => r.request(name));
    r.clock.advanceTo(BURST_GATHER_MS + 10); // A3 sent at 100; A2, A1 queued
    r.scheduler.reset();
    assert.deepEqual(r.dropped, ['A2', 'A1']);
    assert.equal(r.clock.pendingTimers(), 0);
    assert.deepEqual(nextCase(r, BURST_GATHER_MS + 20, CASE_B), expected);
  });

  it('refuses an order it does not pin', () => {
    assert.throws(() => createResponseScheduler({ order: 'natural' }), /forward or reverse/);
  });
});

/**
 * The frozen `reverse` rule (server.mjs, RESPONSE_ORDERS; review record
 * 2026-10-13-x3, "Gate and harness"), computed independently of the scheduler:
 * a burst opens at the first request not already in one and takes every
 * request that arrives less than gatherMs after that one; bursts are released
 * when their window closes, each in reverse arrival order; answers go one at a
 * time, each no sooner than the burst's release and spacingMs after the
 * previous answer. `forward` is the same with every request its own burst,
 * released on arrival.
 */
function model(order, plan) {
  const bursts = [];
  for (const [name, at] of plan) {
    const open = bursts.at(-1);
    if (order === 'reverse' && open && at < open.at + BURST_GATHER_MS) open.names.push(name);
    else bursts.push({ at, names: [name] });
  }
  const answers = []; let last = -Infinity;
  for (const b of bursts) {
    const release = order === 'reverse' ? b.at + BURST_GATHER_MS : b.at;
    for (const name of order === 'reverse' ? [...b.names].reverse() : b.names) {
      last = Math.max(release, last + RESPONSE_SPACING_MS);
      answers.push([name, last]);
    }
  }
  return { answers, groups: plan.map(([name]) => bursts.findIndex((b) => b.names.includes(name))) };
}

function play(order, plan) {
  const r = rig(order);
  for (const [name, at] of plan) { r.clock.advanceTo(at); r.request(name); }
  r.clock.advanceTo((plan.at(-1)?.[1] ?? 0) + BURST_GATHER_MS + (plan.length + 1) * RESPONSE_SPACING_MS);
  return r;
}

describe('a pinned order answers every request, grouped by arrival (CI 38601805584)', unitBlock(), () => {
  // Arrival spreads of the page's three concurrent requests measured at the
  // server under CPU load (the reverse real-browser test's page): split bursts,
  // not stranded requests.
  const OBSERVED = [
    { plan: [['first', 0], ['second', 1], ['third', 1]], order: ['third', 'second', 'first'] },
    { plan: [['first', 0], ['second', 0], ['third', 124]], order: ['second', 'first', 'third'] },
    { plan: [['first', 0], ['second', 29], ['third', 207]], order: ['second', 'first', 'third'] },
    { plan: [['first', 0], ['second', 24], ['third', 114]], order: ['second', 'first', 'third'] },
    { plan: [['first', 0], ['second', 73], ['third', 151]], order: ['second', 'first', 'third'] },
    { plan: [['first', 0], ['second', 162], ['third', 336]], order: ['first', 'second', 'third'] },
    { plan: [['first', 0], ['second', 110], ['third', 115]], order: ['first', 'third', 'second'] },
  ];
  for (const { plan, order } of OBSERVED) {
    it(`reverse, arrivals at ${plan.map(([, at]) => at).join('/')} ms: ${order.join(',')}, each answered once`, () => {
      const r = play('reverse', plan);
      assert.deepEqual(r.answered.map(([name]) => name), order);
      assert.deepEqual(r.answered, model('reverse', plan).answers);
      assert.deepEqual(r.dropped, []);
      assert.deepEqual(r.scheduler.pending(), { queued: 0, gathering: 0, timers: 0 });
      assert.equal(r.clock.pendingTimers(), 0);
    });
  }

  it('a burst boundary is exact: a request arriving gatherMs after the burst opened starts the next one', () => {
    const r = play('reverse', [['a', 0], ['b', BURST_GATHER_MS - 1], ['c', BURST_GATHER_MS]]);
    assert.deepEqual(r.answered.map(([name]) => name), ['b', 'a', 'c']);
    assert.deepEqual(r.scheduler.arrivals().map(({ label, group }) => ({ label, group })), [{ label: 'a', group: 0 }, { label: 'b', group: 0 }, { label: 'c', group: 1 }]);
  });

  it('over 2000 seeded arrival patterns, both orders: every request answered exactly once, as the rule defines, nothing left pending', () => {
    let seed = 20261015;
    const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
    for (let n = 0; n < 2000; n += 1) {
      const order = n % 2 ? 'forward' : 'reverse';
      const plan = []; let at = Math.floor(rand() * 50);
      const count = 1 + Math.floor(rand() * 8);
      for (let i = 0; i < count; i += 1) {
        // Gaps from bunched to well past the window and the spacing.
        at += [0, 1, 5, 30, 99, 100, 101, 150, 400][Math.floor(rand() * 9)];
        plan.push([`r${i}`, at]);
      }
      const r = play(order, plan);
      const expected = model(order, plan);
      const context = JSON.stringify({ order, plan, answered: r.answered });
      assert.deepEqual(r.answered, expected.answers, context);
      assert.deepEqual([...r.answered.map(([name]) => name)].sort(), plan.map(([name]) => name).sort(), context);
      // The diagnostic the real-browser tests read is the scheduler's truth.
      const arrivals = r.scheduler.arrivals();
      assert.deepEqual(arrivals.map((a) => a.group), expected.groups, context);
      assert.deepEqual(arrivals.map((a) => [a.label, a.at]), plan, context);
      assert.deepEqual(arrivals.map((a) => [a.label, a.answeredAt]).sort((x, y) => x[1] - y[1]), expected.answers, context);
      assert.deepEqual(r.dropped, [], context);
      assert.deepEqual(r.scheduler.pending(), { queued: 0, gathering: 0, timers: 0 }, context);
      assert.equal(r.clock.pendingTimers(), 0, context);
    }
  });
});
