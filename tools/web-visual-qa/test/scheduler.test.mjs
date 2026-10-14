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
  const scheduler = createResponseScheduler({ order, setTimer: clock.setTimer, clearTimer: clock.clearTimer });
  const answered = []; const dropped = [];
  const request = (name) => scheduler.submit(() => answered.push([name, clock.now()]), () => dropped.push(name));
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
