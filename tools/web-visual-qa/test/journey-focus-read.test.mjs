// S6/X3 audit of the journey runner's focus read (b8cfaa05): the one
// re-observation it allows is a bounded recovery from the page replacing the
// focused node while it is read, never a retry of a judgement. These tests
// drive the real operator against a scripted browser that logs every call,
// so what the operator does — and does not do — is observed directly.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { HarnessError } from '../engine.mjs';
import { createOperator, JourneyFailure, readFocus } from '../journeys.mjs';

const STALE = 'Could not find node with given id';
const control = (name, extra = {}) => ({ route: '/search', description: `button "${name}"`, tag: 'button', problems: [], name: undefined, ...extra, axName: name });
const BODY = { route: '/search', description: '<body>', onBody: true, problems: ['focus is on the document, not on a control (lost)'] };

/**
 * A browser whose focus reads follow a script: each entry is what one
 * journeyFocusState evaluation returns, and for a control, what the
 * accessibility read then does (`stale` throws CDP's missing-node error).
 */
function scripted(reads) {
  const calls = [];
  const queue = [...reads];
  return {
    calls,
    async evaluate(expression) {
      if (expression.includes('function journeyFocusState')) {
        calls.push('read-focus');
        const next = queue.shift();
        assert.ok(next, 'the operator read focus more often than the script allows');
        this.pendingAx = next;
        const { axName, stale, axError, ...state } = next;
        return { ...state };
      }
      if (expression.includes('__vqaJourneyGuard')) { calls.push('guards'); return { pointer: [], synthetic: [], document: 1 }; }
      if (expression.startsWith('Boolean(document.querySelector(')) { calls.push('transient?'); return false; }
      calls.push(`evaluate:${expression.slice(0, 40)}`);
      return null;
    },
    async axNames(selector) {
      calls.push(`ax:${selector}`);
      const { axName, stale, axError } = this.pendingAx;
      if (stale) throw new Error(STALE);
      if (axError) throw new Error(axError);
      return [{ name: axName, role: 'button' }];
    },
    async press(key) { calls.push(`press:${key}`); },
    async cdp(method) { calls.push(`cdp:${method}`); return {}; },
  };
}

const server = { requests: () => [], network: () => ({ inflight: 0 }) };
function operator(browser) {
  const { op, steps } = createOperator({ browser, server, journeyId: 'audit', viewport: { label: '1024x768' }, documentIndex: 1, limits: { timeoutMs: 500 } });
  return { op, steps };
}
// Everything the operator sent that acts on the page, rather than reading it.
const actions = (calls) => calls.filter((c) => c.startsWith('press:') || c.startsWith('cdp:') || c.startsWith('evaluate:'));

describe('the journey focus read (b8cfaa05 audit)', () => {
  it('reads again only when the page replaced the tagged node during the read', async () => {
    const browser = scripted([{ ...control('Load more'), stale: true }, control('Loading more…')]);
    const state = await readFocus(browser);
    assert.deepEqual(browser.calls, ['read-focus', 'ax:[data-vqa-journey-focus]', 'read-focus', 'ax:[data-vqa-journey-focus]']);
    assert.equal(state.name, 'Loading more…');
    assert.match(state.reobserved, /replaced while it was read/);
  });

  it('does not read again for any other failure of the read: it stands as it is', async () => {
    const browser = scripted([{ ...control('Load more'), axError: 'Target closed' }, control('never read')]);
    await assert.rejects(readFocus(browser), /Target closed/);
    assert.deepEqual(browser.calls, ['read-focus', 'ax:[data-vqa-journey-focus]']);
  });

  it('reads again at most once: a second replacement is a harness fault', async () => {
    const browser = scripted([{ ...control('A'), stale: true }, { ...control('B'), stale: true }, control('never read')]);
    await assert.rejects(readFocus(browser), (error) => error instanceof HarnessError && /twice running/.test(error.message));
    assert.equal(browser.calls.filter((c) => c === 'read-focus').length, 2);
  });

  it('sends no key and applies no focus to recover: the re-read only reads', async () => {
    const browser = scripted([control('Load more'), { ...control('Load more'), stale: true }, control('Loading more…')]);
    const { op } = operator(browser);
    await op.press('Enter', { expectFocus: { name: /Load/ } });
    assert.deepEqual(actions(browser.calls), ['press:Enter'], 'one key, the journey\'s own; nothing else acted');
    // journeyFocusState itself observes and tags; it never moves focus.
    const { journeyFocusState } = await import('../journeys.mjs');
    assert.doesNotMatch(journeyFocusState.toString(), /\.focus\(|\.blur\(|dispatchEvent|\.click\(/);
  });

  it('fails focus that moves to the wrong control immediately, without reading again', async () => {
    const browser = scripted([control('Load more'), control('Clear filters')]);
    const { op, steps } = operator(browser);
    await assert.rejects(op.press('Enter', { expectFocus: { name: 'Load more' } }), JourneyFailure);
    assert.equal(browser.calls.filter((c) => c === 'read-focus').length, 2, 'one read before the key, one after: no second look');
    assert.equal(steps.at(-1).pass, false);
    assert.match(steps.at(-1).observed, /focus landed on button "Clear filters"/);
  });

  it('fails focus that is absent after the redraw', async () => {
    const browser = scripted([control('Load more'), { ...control('Load more'), stale: true }, BODY]);
    const { op, steps } = operator(browser);
    await assert.rejects(op.press('Enter', { expectFocus: { name: /Load/ } }), JourneyFailure);
    assert.match(steps.at(-1).observed, /focus is on the document, not on a control \(lost\)/);
    assert.equal(steps.at(-1).focusAfter, '<body> (read again after a redraw)');
  });

  it('fails a redraw that leaves focus on the wrong control, naming the control it found', async () => {
    const browser = scripted([control('Load more'), { ...control('Load more'), stale: true }, control('Clear filters')]);
    const { op, steps } = operator(browser);
    await assert.rejects(op.press('Enter', { expectFocus: { name: /Load/ } }), JourneyFailure);
    assert.match(steps.at(-1).observed, /focus landed on button "Clear filters" \(read again after a redraw\)/);
  });

  it('records the target observed after the redraw, and says it was read again', async () => {
    const browser = scripted([control('Load more'), { ...control('Load more'), stale: true }, control('Loading more…')]);
    const { op, steps } = operator(browser);
    await op.press('Enter', { expectFocus: { name: /Load/ } });
    const [step] = steps;
    assert.equal(step.pass, true);
    assert.equal(step.focusBefore, 'button "Load more"');
    assert.equal(step.focusAfter, 'button "Loading more…" (read again after a redraw)', 'the post-redraw target, never the replaced one');
  });
});
