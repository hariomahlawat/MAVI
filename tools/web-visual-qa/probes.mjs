/**
 * X1 probes that act on the page through the input pipeline (cdp.mjs press,
 * mouseMove), so the harness's own tests can drive them against a fixture as
 * run.mjs drives them against the product. Each returns findings for one
 * rule, what it judged, and a `measured` record; none sleeps for a guessed
 * time — every wait is a bounded poll of the page's own state.
 */
import { toExpression } from './assertions.mjs';
import { a11yShortcutsAfter, a11yShortcutsBefore, a11yTooltipFocus, a11yTooltipPoint, a11yTooltipState, a11yTooltipTargets } from './a11y.mjs';

const tick = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * a11y.hover-content (WCAG 1.4.13): every custom tooltip of the page — the
 * `.tooltip-anchor` with its `[role="tooltip"]` — driven: focus its trigger
 * (shown, and still shown once the delay has passed again), Escape (hidden,
 * focus unmoved — not pressed on a trigger inside an open overlay, whose
 * Escape the exit probe judges), then the pointer onto the trigger (shown),
 * onto the tooltip itself (still shown: hoverable), away (hidden). The delay
 * is the page's motion token (`--dur`), read from the stylesheet.
 */
export async function probeHoverContent(browser) {
  const targets = await browser.evaluate(toExpression(a11yTooltipTargets));
  const delayMs = Number(await browser.evaluate(`(() => { const raw = getComputedStyle(document.documentElement).getPropertyValue('--dur').trim(); const n = parseFloat(raw); return raw.endsWith('ms') ? n : raw.endsWith('s') ? n * 1000 : 120; })()`)) || 120;
  const state = (id) => browser.evaluate(toExpression(a11yTooltipState, id));
  const settleTip = async (id, want) => {
    const started = Date.now();
    let last = null;
    while (Date.now() - started < delayMs * 4 + 500) {
      last = await state(id);
      if (last.gone || want(last)) return last;
      await tick(Math.min(50, delayMs));
    }
    return last;
  };
  const hold = async (id) => {
    const started = Date.now();
    let last = null;
    while (Date.now() - started < delayMs * 2 + 100) {
      last = await state(id);
      if (!last.shown) return last;
      await tick(Math.min(50, delayMs));
    }
    return last;
  };
  // "Away" is a point on neither the trigger nor its tooltip: the corner of
  // the viewport farthest from the trigger.
  const away = async (target) => {
    const [vw, vh] = await browser.evaluate('[document.documentElement.clientWidth, document.documentElement.clientHeight]');
    await browser.mouseMove(target.x < vw / 2 ? vw - 2 : 2, target.y < vh / 2 ? vh - 2 : 2);
  };
  const findings = [];
  let judged = 0; let escapeSkipped = 0;
  for (const target of targets) {
    judged += 1;
    const problems = [];
    const focused = await browser.evaluate(toExpression(a11yTooltipFocus, target.id));
    if (!focused) problems.push('its trigger refused focus');
    else {
      let s = await settleTip(target.id, (x) => x.shown);
      if (s.gone) problems.push('the tooltip left the document on focus');
      else if (!s.shown) problems.push('not shown on focus');
      else {
        s = await hold(target.id);
        if (!s.shown) problems.push('shown on focus, then hidden while focus stayed');
        if (!s.describes) problems.push("the tooltip is not the trigger's description (aria-describedby)");
        if (target.inOverlay) escapeSkipped += 1;
        else {
          const focusBefore = s.focus;
          await browser.press('Escape');
          s = await settleTip(target.id, (x) => !x.shown);
          if (s.shown) problems.push('Escape did not dismiss it');
          if (s.focus !== focusBefore) problems.push('Escape moved focus from ' + focusBefore + ' to ' + (s.focus ?? 'nothing'));
        }
      }
      await browser.evaluate('(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); return true; })()');
      await settleTip(target.id, (x) => !x.shown);
    }
    // Where the trigger is now: focusing it may have scrolled its frame.
    const point = (await browser.evaluate(toExpression(a11yTooltipPoint, target.id))) ?? target;
    await browser.mouseMove(point.x, point.y);
    let s = await settleTip(target.id, (x) => x.shown);
    if (s.gone) problems.push('the tooltip left the document on hover');
    else if (!s.shown) problems.push('not shown on hover');
    else {
      await browser.mouseMove(s.box.x + s.box.width / 2, s.box.y + s.box.height / 2);
      s = await hold(target.id);
      if (!s.shown) problems.push('hidden when the pointer moved onto it (not hoverable)');
      await away(target);
      s = await settleTip(target.id, (x) => !x.shown);
      if (s.shown) problems.push('still shown after the pointer left');
    }
    if (problems.length) findings.push(`${target.description}: ${problems.join('; ')}`);
  }
  if (targets.length) await away(targets[targets.length - 1]);
  return { findings, judged, measured: { judged, escapeSkipped, delayMs } };
}

/**
 * a11y.shortcuts-in-text-entry (§23, WCAG 2.1.4): the first text-entry
 * control focused and the shell's "?" (and, on the Scene Editor, Delete)
 * pressed as real keys; the page then says whether a shortcut acted and
 * whether the key reached the field. The field is put back as it was.
 */
export async function probeShortcuts(browser) {
  const before = await browser.evaluate(toExpression(a11yShortcutsBefore));
  if (!before.field) return { findings: [], evaluated: [], measured: { field: null, refused: before.refused ?? null } };
  await browser.press('?', 'Slash', { shift: true });
  if (before.sceneEditor) await browser.press('Delete', 'Delete');
  // The key reaches the field through the page's own event handling, which
  // may re-render it: wait, bounded, for the value to carry it (or for the
  // shortcut to have acted), then judge.
  const started = Date.now();
  while (Date.now() - started < 1500) {
    const carried = await browser.evaluate(`(() => { const f = window.__vqaShortcutField; const v = f && ('value' in f ? f.value : f.textContent); return (typeof v === 'string' && v.includes('?')) || document.querySelectorAll('[role="dialog"]').length > ${before.dialogs}; })()`);
    if (carried) break;
    await tick(50);
  }
  const after = await browser.evaluate(toExpression(a11yShortcutsAfter, before));
  // A sheet the shortcut wrongly opened is closed, so later probes see the state.
  if (after.findings.some((f) => /opened an overlay/.test(f.message))) await browser.press('Escape');
  return { findings: after.findings, evaluated: after.evaluated, measured: { field: before.field, findings: after.findings.length } };
}
