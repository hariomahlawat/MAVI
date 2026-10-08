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
    // Every appearance of a loading presentation, from first visible to gone,
    // so a navigation's transition and one a preparation starts stay apart.
    loading: [],
    shifts: [],
    longTasks: [],
    // The harness's own settle probes, [start, end] of their work on the page's
    // main thread, so a long task they caused is not counted as the product's.
    probeSpans: [],
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
    if (present && !vqa.loadingPresent) vqa.loading.push({ seenAt: now, goneAt: null });
    if (!present && vqa.loadingPresent && vqa.loading.length) vqa.loading[vqa.loading.length - 1].goneAt = now;
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
  // The overlay's invoker (§15, §20): the last element focused outside any
  // modal before focus first enters that modal. Later focus moves — the focus
  // pass walking the page while a drawer is open — never replace it.
  vqa.lastOutsideFocus = null;
  vqa.invoker = null;
  vqa.invokerFor = null;
  document.addEventListener('focusin', (event) => {
    const modal = event.target && event.target.closest ? event.target.closest('[role="dialog"][aria-modal="true"]') : null;
    if (!modal) { vqa.lastOutsideFocus = event.target; return; }
    if (vqa.invokerFor !== modal) { vqa.invokerFor = modal; vqa.invoker = vqa.lastOutsideFocus; }
  }, true);
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
  const started = performance.now();
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
  // A video the page shows has its metadata and is not mid-seek, so a seek
  // the page makes on load (and the time readout beside it) has happened
  // before the capture. (A paused video can rest at metadata only.) A video
  // whose source failed or that has none is the page's own unavailable state.
  const videos = Array.from(document.querySelectorAll('video')).filter((video) => visible(video)
    && video.currentSrc && !video.error && video.networkState !== 3 && (video.readyState < 1 || video.seeking));
  if (videos.length) why.push(videos.length + ' video(s) still loading or seeking');
  const at = performance.now();
  if (vqa) vqa.probeSpans.push([started, at]);
  return { why, mutations: vqa ? vqa.mutations : null, at };
}

/**
 * The P1 observations for one capture (§38). Each measurement states whether
 * it was measured, not applicable, unsupported or failed — a missing number
 * is never reported as zero.
 *
 * @param {{ holds: string|null, settledAt: number, prepareStart: number|null, preparedAt: number|null, quietAt: number|null, interaction: string|null }} input
 */
export function perfCollect(input) {
  const vqa = window.__vqa;
  const missing = { status: 'failed', why: 'observers were not installed' };
  if (!vqa) return { cls: missing, clsPreparation: missing, longTasks: missing };
  const r4 = (n) => Math.round(n * 10000) / 10000;

  // CLS over one loading-to-content transition: from the first loading
  // presentation seen inside [from, to] to `to`, the moment the page settled.
  // Shifts outside that window — before the loading, after settling, or in
  // the harness's own activity between the two transitions — are not in it.
  const transition = (from, to, none) => {
    if (!vqa.supports.layoutShift) return { status: 'unsupported', why: 'the browser does not report layout-shift entries' };
    if (input.holds === 'loading') return { status: 'not-applicable', why: 'a held loading state: content never arrives by design' };
    const episodes = (vqa.loading || []).filter((episode) => episode.seenAt >= from && episode.seenAt <= to);
    if (!episodes.length) return { status: 'not-applicable', why: none };
    const open = episodes.find((episode) => episode.goneAt === null || episode.goneAt > to);
    if (open) return { status: 'failed', why: 'a loading presentation was still shown when the page settled' };
    const span = [episodes[0].seenAt, to];
    const entries = vqa.shifts.filter((entry) => entry.startTime >= span[0] && entry.startTime <= span[1]);
    const counted = entries.filter((entry) => !entry.hadRecentInput);
    return {
      status: 'measured',
      value: r4(counted.reduce((sum, entry) => sum + entry.value, 0)),
      window: { from: Math.round(span[0]), loadingCleared: Math.round(episodes[episodes.length - 1].goneAt), to: Math.round(span[1]) },
      episodes: episodes.length,
      entries: counted.map((entry) => ({ value: r4(entry.value), at: Math.round(entry.startTime), sources: entry.sources })),
      excludedForInput: entries.length - counted.length,
      outsideWindow: vqa.shifts.length - entries.length,
    };
  };
  const cls = transition(0, input.settledAt, 'no loading presentation was observed while the page loaded, so there was no loading-to-content transition');
  let clsPreparation;
  if (input.prepareStart === null) clsPreparation = { status: 'not-applicable', why: 'the state has no preparation' };
  else if (input.preparedAt === null) clsPreparation = { status: 'failed', why: 'the state did not settle after its preparation' };
  else {
    clsPreparation = transition(input.prepareStart, input.preparedAt, 'the preparation started no loading presentation');
    clsPreparation.by = input.interaction ?? 'fixture preparation';
  }

  // Long tasks of the state's first interaction: from the action to the page
  // going quiet with its outcome shown. A preparation that is fixture setup or
  // verification is not an operator interaction and is not measured as one.
  let longTasks;
  if (!vqa.supports.longTask) longTasks = { status: 'unsupported', why: 'the browser does not report longtask entries' };
  else if (!input.interaction) {
    longTasks = { status: 'not-applicable', why: input.prepareStart === null ? 'the state has no interaction: it is a rendered state' : 'its preparation is fixture setup or verification, not an operator interaction' };
  } else if (input.prepareStart === null || input.quietAt === null) longTasks = { status: 'failed', why: 'the interaction did not complete' };
  else {
    // From the named action when the preparation marked it, else from the
    // preparation's start (a preparation that is that one action).
    const marked = vqa.marks['interaction-start'];
    const from = typeof marked === 'number' && marked >= input.prepareStart && marked <= input.quietAt ? marked : input.prepareStart;
    const inWindow = vqa.longTasks.filter((task) => task.startTime >= from && task.startTime <= input.quietAt);
    // A long task that ran a settle probe is the harness's work, not the action's.
    const harness = (task) => (vqa.probeSpans || []).some(([a, b]) => task.startTime <= b && task.startTime + task.duration >= a);
    const tasks = inWindow.filter((task) => !harness(task));
    longTasks = {
      status: 'measured',
      interaction: input.interaction,
      excludedAsHarness: inWindow.length - tasks.length,
      startsAt: from === input.prepareStart ? 'preparation start (a single-action preparation)' : 'the marked action',
      count: tasks.length,
      totalMs: Math.round(tasks.reduce((sum, task) => sum + task.duration, 0)),
      maxMs: Math.round(tasks.reduce((max, task) => Math.max(max, task.duration), 0)),
      window: { from: Math.round(from), to: Math.round(input.quietAt) },
    };
  }

  return { cls, clsPreparation, longTasks };
}
