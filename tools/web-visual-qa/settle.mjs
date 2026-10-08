/**
 * Deterministic settling and the P1 performance observations (register V3,
 * P1; specification §26, §38).
 *
 * A capture is taken only when the page has *shown* it reached its declared
 * state, never because some time has passed. The probe below is the page's
 * half of that test; `run.mjs` adds the fixture server's half (no data
 * request in flight, none started since the last probe) and requires both to
 * hold on consecutive probes, with a bounded timeout that refuses the capture.
 *
 * The performance observers are installed before any page script runs and
 * are passive: they read what the browser reports and change nothing.
 */

/** Presentations that mean "content is still on its way" (§14.1, §37.1). */
export const TRANSIENT = '.loading-state, .skeleton, .state-row--loading, .evidence-placeholder--pending';

/**
 * Installed on every new document (Page.addScriptToEvaluateOnNewDocument).
 *
 * - counts DOM mutations, so a probe can tell a page that is still changing
 *   from one that has stopped;
 * - records when a loading presentation first appears and when the last one
 *   goes, which bounds the loading-to-content transition CLS is scoped to;
 * - buffers layout-shift and long-task entries where the browser supports
 *   them, and records whether it does.
 */
function installObservers(transient) {
  const vqa = {
    mutations: 0,
    loadingSeenAt: null,
    loadingGoneAt: null,
    loadingPresent: false,
    shifts: [],
    longTasks: [],
    marks: {},
    supports: {
      layoutShift: typeof PerformanceObserver !== 'undefined'
        && (PerformanceObserver.supportedEntryTypes || []).includes('layout-shift'),
      longTask: typeof PerformanceObserver !== 'undefined'
        && (PerformanceObserver.supportedEntryTypes || []).includes('longtask'),
    },
  };
  window.__vqa = vqa;
  const watchLoading = () => {
    const present = Array.from(document.querySelectorAll(transient)).some((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    });
    const now = performance.now();
    if (present && vqa.loadingSeenAt === null) vqa.loadingSeenAt = now;
    if (vqa.loadingPresent && !present) vqa.loadingGoneAt = now;
    if (present) vqa.loadingGoneAt = null;
    vqa.loadingPresent = present;
  };
  new MutationObserver((records) => {
    vqa.mutations += records.length;
    watchLoading();
  }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  const describe = (node) => {
    if (!node || node.nodeType !== 1) return node ? node.nodeName.toLowerCase() : null;
    const cls = typeof node.className === 'string' && node.className.trim() ? '.' + node.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    return node.tagName.toLowerCase() + cls;
  };
  if (vqa.supports.layoutShift) {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        vqa.shifts.push({
          value: entry.value, startTime: entry.startTime, hadRecentInput: entry.hadRecentInput,
          sources: (entry.sources || []).slice(0, 3).map((source) => describe(source.node)),
        });
      }
    }).observe({ type: 'layout-shift', buffered: true });
  }
  if (vqa.supports.longTask) {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) vqa.longTasks.push({ startTime: entry.startTime, duration: entry.duration });
    }).observe({ type: 'longtask', buffered: true });
  }
  vqa.mark = (name) => { vqa.marks[name] = performance.now(); return vqa.marks[name]; };
}

export const OBSERVERS = `(${installObservers.toString()})(${JSON.stringify(TRANSIENT)});`;

/**
 * The page's half of "settled". Waits two animation frames, then reports
 * every reason the page is not yet in its declared state.
 *
 * @param {{ expectText: string[], forbidText: string[], holds: string|null, transient: string }} input
 */
export async function settleProbe(input) {
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const why = [];
  const vqa = window.__vqa;
  if (document.readyState !== 'complete') why.push('document ' + document.readyState);
  if (document.fonts && document.fonts.status !== 'loaded') why.push('fonts ' + document.fonts.status);
  const text = document.body ? document.body.innerText : '';
  for (const needle of input.expectText) if (!text.includes(needle)) why.push('expected text "' + needle + '" not yet shown');
  for (const needle of input.forbidText) if (text.includes(needle)) why.push('forbidden text "' + needle + '" is shown');
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  };
  const loading = Array.from(document.querySelectorAll(input.transient)).filter(visible);
  if (input.holds === 'loading') {
    // A held-loading state is ready when its loading presentation is on screen;
    // its data request is deliberately never answered.
    if (!loading.length) why.push('the held loading presentation is not shown');
  } else if (loading.length) {
    why.push(loading.length + ' loading presentation(s) still shown (' + (loading[0].className || loading[0].tagName) + ')');
  }
  const images = Array.from(document.images).filter((img) => visible(img) && !img.complete);
  if (images.length) why.push(images.length + ' image(s) still loading');
  const running = (document.getAnimations ? document.getAnimations() : []).filter((animation) => {
    if (animation.playState !== 'running') return false;
    const timing = animation.effect && animation.effect.getTiming ? animation.effect.getTiming() : null;
    return !timing || timing.iterations !== Infinity;
  });
  if (running.length) why.push(running.length + ' transition(s) or animation(s) still running');
  return { why, mutations: vqa ? vqa.mutations : null };
}

/**
 * The P1 observations for one capture (§38). Each measurement states whether
 * it was measured, not applicable, unsupported or failed — a missing number
 * is never reported as zero.
 *
 * @param {{ holds: string|null, settledAt: number, prepareStart: number|null, prepareEnd: number|null }} input
 */
export function perfCollect(input) {
  const vqa = window.__vqa;
  if (!vqa) return { cls: { status: 'failed', why: 'observers were not installed' }, longTasks: { status: 'failed', why: 'observers were not installed' } };
  const r4 = (n) => Math.round(n * 10000) / 10000;

  let cls;
  if (!vqa.supports.layoutShift) cls = { status: 'unsupported', why: 'the browser does not report layout-shift entries' };
  else if (input.holds === 'loading') cls = { status: 'not-applicable', why: 'a held loading state: content never arrives by design' };
  else if (vqa.loadingSeenAt === null) cls = { status: 'not-applicable', why: 'no loading presentation was observed, so there was no loading-to-content transition' };
  else if (vqa.loadingGoneAt === null) cls = { status: 'failed', why: 'the loading presentation never cleared before settling' };
  else {
    const span = [vqa.loadingSeenAt, input.settledAt];
    const entries = vqa.shifts.filter((entry) => entry.startTime >= span[0] && entry.startTime <= span[1]);
    const counted = entries.filter((entry) => !entry.hadRecentInput);
    cls = {
      status: 'measured',
      value: r4(counted.reduce((sum, entry) => sum + entry.value, 0)),
      window: { from: Math.round(span[0]), loadingCleared: Math.round(vqa.loadingGoneAt), to: Math.round(span[1]) },
      entries: counted.map((entry) => ({ value: r4(entry.value), at: Math.round(entry.startTime), sources: entry.sources })),
      excludedForInput: entries.length - counted.length,
      outsideWindow: vqa.shifts.length - entries.length,
    };
  }

  let longTasks;
  if (!vqa.supports.longTask) longTasks = { status: 'unsupported', why: 'the browser does not report longtask entries' };
  else if (input.prepareStart === null) longTasks = { status: 'not-applicable', why: 'the state declares no interaction: it is a rendered state, not an action' };
  else if (input.prepareEnd === null) longTasks = { status: 'failed', why: 'the interaction did not complete' };
  else {
    const tasks = vqa.longTasks.filter((task) => task.startTime >= input.prepareStart && task.startTime <= input.prepareEnd);
    longTasks = {
      status: 'measured',
      count: tasks.length,
      totalMs: Math.round(tasks.reduce((sum, task) => sum + task.duration, 0)),
      maxMs: Math.round(tasks.reduce((max, task) => Math.max(max, task.duration), 0)),
      window: { from: Math.round(input.prepareStart), to: Math.round(input.prepareEnd) },
    };
  }

  return { cls, longTasks };
}
