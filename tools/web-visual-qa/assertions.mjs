/**
 * The automated part of the section 26 visual-QA standard.
 *
 * These run in the page. They are deliberately the three checks section 26
 * names — no horizontal page overflow, no uncaught page errors, no element
 * overlap — plus two the UI-1 acceptance criteria need: that a surface which
 * declares full width actually uses it, and that no stylesheet reference failed
 * to resolve. Everything else in section 26 is a human looking at the screen,
 * which is why the harness also writes screenshots.
 */

export const PAGE_ASSERTIONS = `(() => {
  const problems = [];
  const doc = document.documentElement;

  // What of an element is actually on screen.
  //
  // getBoundingClientRect reports where an element would be, not where it can
  // be seen: a row scrolled out of an inspector body still reports a rect, and
  // that rect lands on whatever is painted there. Comparing those rects finds
  // "overlaps" between things a person can never see at the same time. So each
  // element is clipped by every scrolling or hidden ancestor, and by the
  // viewport, before anything is compared — and an element clipped to nothing
  // takes no part in the comparison at all.
  const visibleRect = (el) => {
    const r = el.getBoundingClientRect();
    let box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    for (let node = el.parentElement; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.overflowX === 'visible' && style.overflowY === 'visible') continue;
      const c = node.getBoundingClientRect();
      box = {
        left: Math.max(box.left, c.left), top: Math.max(box.top, c.top),
        right: Math.min(box.right, c.right), bottom: Math.min(box.bottom, c.bottom),
      };
    }
    box = {
      left: Math.max(box.left, 0), top: Math.max(box.top, 0),
      right: Math.min(box.right, doc.clientWidth), bottom: Math.min(box.bottom, doc.clientHeight),
    };
    return { ...box, width: box.right - box.left, height: box.bottom - box.top };
  };

  // 1. No horizontal page scroll at any acceptance width.
  if (doc.scrollWidth > doc.clientWidth + 1) {
    problems.push('horizontal page overflow: scrollWidth ' + doc.scrollWidth + ' > clientWidth ' + doc.clientWidth);
  }

  // 2. Interactive controls must not overlap one another. Controls are checked
  //    rather than every node, because text boxes legitimately nest.
  const controls = Array.from(document.querySelectorAll('button, a[href], input, select, textarea'))
    .filter((el) => {
      const r = visibleRect(el);
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    });
  for (let i = 0; i < controls.length; i++) {
    for (let j = i + 1; j < controls.length; j++) {
      const a = controls[i], b = controls[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = visibleRect(a), rb = visibleRect(b);
      const overlapX = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const overlapY = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      // A couple of pixels is antialiasing and adjacency, not an overlap.
      if (overlapX > 2 && overlapY > 2) {
        problems.push('overlapping controls: <' + a.tagName.toLowerCase() + '> "' +
          (a.textContent || '').trim().slice(0, 24) + '" and <' + b.tagName.toLowerCase() + '> "' +
          (b.textContent || '').trim().slice(0, 24) + '"');
      }
    }
  }

  // 2b. Text that collides with other text. Controls alone are not enough: a
  //     section heading landing on top of a field label is just as unusable,
  //     and only a rendered page can show it.
  const leaves = Array.from(document.querySelectorAll('h1, h2, h3, h4, label, p, span, strong, dt, dd'))
    .filter((el) => {
      if (el.querySelector('h1, h2, h3, h4, label, p, span, strong, dt, dd')) return false;
      const text = (el.textContent || '').trim();
      if (!text) return false;
      const r = visibleRect(el);
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    });
  for (let i = 0; i < leaves.length; i++) {
    for (let j = i + 1; j < leaves.length; j++) {
      const a = leaves[i], b = leaves[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = visibleRect(a), rb = visibleRect(b);
      const ox = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const oy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (ox > 4 && oy > 4) {
        problems.push('overlapping text: "' + (a.textContent || '').trim().slice(0, 28) +
          '" and "' + (b.textContent || '').trim().slice(0, 28) + '"');
      }
    }
  }

  // 3. Every custom property a stylesheet asks for must resolve. An unresolved
  //    one renders as nothing at all, which is how the baseline shipped an
  //    invisible focus ring.
  const root = getComputedStyle(doc);
  const referenced = new Set();
  for (const sheet of Array.from(document.styleSheets)) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; }
    for (const rule of Array.from(rules || [])) {
      const text = rule.cssText || '';
      for (const m of text.matchAll(/var\\(\\s*(--[a-z0-9-]+)/g)) referenced.add(m[1]);
    }
  }
  for (const name of referenced) {
    if (root.getPropertyValue(name).trim() === '') problems.push('unresolved custom property: ' + name);
  }

  // 4. Width discipline. A page that declares full width must use the viewport;
  //    a page that does not must stay capped. Both directions matter: UI-1 must
  //    not widen a surface whose archetype migration has not happened yet.
  const page = document.querySelector('.page');
  const width = page ? Math.round(page.getBoundingClientRect().width) : null;
  const full = page ? page.classList.contains('page--full') : null;

  // 5. Exactly one Context Bar. §5 says the topbar *becomes* the Context Bar;
  //    a surface that published its own while the shell still rendered the old
  //    band would show two, and every individual assertion here would pass.
  const bars = document.querySelectorAll('.context-bar').length;
  if (bars !== 1) problems.push('expected exactly one Context Bar, found ' + bars);

  return { problems, pageWidth: width, declaresFullWidth: full, viewport: doc.clientWidth };
})()`;

/**
 * Archetype conformance (§4), measured on the rendered page.
 *
 * The frozen rules this checks are the ones a unit test cannot see, because
 * they are about what the browser actually computed: how wide the stage ended
 * up, whether the page can be scrolled, and which element owns the scroll.
 *
 * The stage-width rule (§4.3.1) is a ratio against the *working* width — the
 * content column minus page padding — which is exactly the width of the
 * workspace element itself, so it is measured rather than reconstructed from
 * viewport arithmetic.
 */
export const WORKSPACE_ASSERTIONS = `(() => {
  const problems = [];
  const doc = document.documentElement;
  const round = (n) => Math.round(n * 10) / 10;

  const workspace = document.querySelector('.workspace');
  if (!workspace) return { problems: ['no .workspace element: this surface is not on an archetype'], measured: null };

  const archetype = Array.from(workspace.classList).find((c) => c.startsWith('workspace--')) || 'unknown';
  const working = workspace.getBoundingClientRect().width;
  const measured = { archetype: archetype.replace('workspace--', ''), workingWidth: round(working) };

  // Which element owns vertical scroll, anywhere inside the workspace.
  const scrollers = Array.from(workspace.querySelectorAll('*')).filter((el) => {
    const style = getComputedStyle(el);
    if (!/(auto|scroll)/.test(style.overflowY)) return false;
    return el.scrollHeight > el.clientHeight + 1;
  // Class names, for naming the scroll owner. The doubled escape is deliberate:
  // this assertion is a template literal, so a single backslash would be eaten
  // before the page ever saw it and the split would run on the letter s.
  }).map((el) => (el.className && typeof el.className === 'string'
    ? '.' + el.className.trim().split(/\\s+/).join('.')
    : el.tagName.toLowerCase()));
  measured.scrollers = scrollers;

  if (archetype === 'workspace--workbench') {
    const stage = workspace.querySelector('.workspace__stage');
    const inspector = workspace.querySelector('.workspace__inspector');
    if (!stage || !inspector) {
      problems.push('Workbench is missing its stage or inspector region');
      return { problems, measured };
    }

    const stageWidth = stage.getBoundingClientRect().width;
    const inspectorWidth = inspector.getBoundingClientRect().width;
    const share = working > 0 ? stageWidth / working : 0;
    measured.stageWidth = round(stageWidth);
    measured.inspectorWidth = round(inspectorWidth);
    measured.stageShare = round(share * 100);

    // Below ~1150 the inspector becomes an overlay and the stage takes the
    // whole working width, so the side-by-side rules apply above that only.
    if (doc.clientWidth >= 1150) {
      // §4.3.1: the stage is never compressed below 65% of the working width.
      if (share < 0.65) {
        problems.push('Workbench stage is ' + measured.stageShare + '% of the working width, below the 65% floor');
      }
      // §4.3: the inspector is fixed between 300 and 360, at every width.
      if (inspectorWidth < 299 || inspectorWidth > 361) {
        problems.push('Workbench inspector is ' + measured.inspectorWidth + 'px, outside the fixed 300-360 range');
      }
    }

    // §4.3.2: the one archetype with a hard no-page-scroll rule. Checked from
    // 1150 up, which is where the specification says the layout must fit.
    //
    // The document is not the only thing that can scroll: the shell's content
    // column is the real scroll container, so a Workbench that overflowed it
    // would scroll for the operator while the document reported nothing. Every
    // ancestor between the workspace and the document is checked for that.
    const scrolledAncestors = [];
    for (let node = workspace.parentElement; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (!/(auto|scroll)/.test(style.overflowY)) continue;
      if (node.scrollHeight > node.clientHeight + 1) {
        scrolledAncestors.push((node.className && typeof node.className === 'string'
          ? '.' + node.className.trim().split(/\\s+/).join('.')
          : node.tagName.toLowerCase()) + ' (' + node.scrollHeight + ' > ' + node.clientHeight + ')');
      }
    }
    measured.scrolledAncestors = scrolledAncestors;

    if (doc.clientWidth >= 1150) {
      if (doc.scrollHeight > doc.clientHeight + 1) {
        problems.push('Workbench page scrolls: scrollHeight ' + doc.scrollHeight + ' > clientHeight ' + doc.clientHeight);
      }
      for (const name of scrolledAncestors) {
        problems.push('Workbench scrolls inside ' + name + ', which is a page scroll to the operator');
      }
    }

    // §4.3: only the inspector body scrolls.
    const stray = scrollers.filter((name) => !name.includes('inspector__body'));
    if (doc.clientWidth >= 1150 && stray.length) {
      problems.push('Workbench has a scroll owner other than the inspector body: ' + stray.join(', '));
    }
  }

  return { problems, measured };
})()`;

/**
 * Focus visibility, checked by actually focusing every practical control on the
 * surface rather than reading CSS: a ring that is painted but clipped is still
 * invisible, and a cap on how many controls are checked is a coverage claim the
 * harness cannot back.
 *
 * Every focusable element is accounted for. A control is either checked or
 * skipped with a named reason, and the caller fails the pass when those two do
 * not add up to what was discovered — so a control can never fall out of the
 * count silently.
 *
 * Focus is left on the first checked control rather than blurred, so each
 * capture carries one real focus ring for the human half of section 26 without
 * adding a state to the matrix.
 */
export const FOCUS_ASSERTIONS = `(() => {
  const problems = [];
  const skipped = {};
  const skip = (reason) => { skipped[reason] = (skipped[reason] || 0) + 1; };

  const candidates = Array.from(document.querySelectorAll(
    'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]'
  ));
  const discovered = candidates.length;
  let checked = 0;
  let first = null;

  for (const el of candidates) {
    // Disabled controls are not in the focus order and have no ring to show.
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') { skip('disabled'); continue; }
    if (el.closest('[inert]')) { skip('inside an inert subtree'); continue; }

    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (rect.width === 0 || rect.height === 0) { skip('zero-sized'); continue; }
    if (style.visibility === 'hidden' || style.display === 'none') { skip('not visible'); continue; }
    // The visually-hidden skip link and its kin are reachable and do have a
    // ring, but it is painted off-screen where a capture cannot judge it.
    if (rect.width <= 1 && rect.height <= 1) { skip('visually hidden'); continue; }

    el.focus();
    if (document.activeElement !== el) { skip('refused focus'); continue; }

    checked += 1;
    if (!first) first = el;

    const focused = getComputedStyle(el);
    const ring = focused.outlineStyle !== 'none' && parseFloat(focused.outlineWidth) > 0;
    const shadow = focused.boxShadow && focused.boxShadow !== 'none';
    if (!ring && !shadow) {
      problems.push('no visible focus on <' + el.tagName.toLowerCase() + '> "' +
        (el.textContent || el.getAttribute('aria-label') || el.getAttribute('name') || '').trim().slice(0, 32) + '"');
    }
  }

  // Leave one real focus state on screen for the capture.
  if (first) first.focus();
  else if (document.activeElement instanceof HTMLElement) document.activeElement.blur();

  return { problems, discovered, checked, skipped };
})()`;

/**
 * Effective pointer target sizes (section 10.1). Reported rather than failed:
 * canvas handles are legitimately small, and the rule is "at least 24x24
 * wherever practical, or a documented exception".
 */
export const TARGET_SIZE_REPORT = `(() => {
  const small = [];
  for (const el of Array.from(document.querySelectorAll('button, a[href], input, select'))) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.width < 24 || r.height < 24) {
      small.push({
        tag: el.tagName.toLowerCase(),
        label: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 32),
        w: Math.round(r.width), h: Math.round(r.height),
      });
    }
  }
  return small;
})()`;

/**
 * Is the evidence overlay genuinely on screen, over a decoded frame?
 *
 * Section 26 asks for overlay visibility to be checked against each footage
 * condition. A capture taken before the media decoded, or before the player
 * reached the frame the overlay is drawn at, validates nothing while looking
 * exactly like a pass.
 */
export const OVERLAY_READY = `(() => {
  const video = document.querySelector('.player video');
  if (!video) return { ok: false, why: 'no player video element' };
  if (video.readyState < 2) return { ok: false, why: 'media not decoded (readyState ' + video.readyState + ')' };
  if (!(video.videoWidth > 0)) return { ok: false, why: 'media reports no frame size' };
  if (!(video.currentTime > 0)) return { ok: false, why: 'player never left the first frame' };

  const marks = Array.from(document.querySelectorAll('.player__overlay rect, .player__overlay polyline'));
  const drawn = marks.filter((m) => { const r = m.getBoundingClientRect(); return r.width > 1 && r.height > 1; });
  if (drawn.length === 0) return { ok: false, why: 'no overlay geometry drawn at this frame' };

  const overlay = document.querySelector('.player__overlay');
  const filter = overlay ? getComputedStyle(overlay).filter : 'none';
  if (!filter || filter === 'none') return { ok: false, why: 'overlay layer carries no halo' };

  return { ok: true, why: '', drawn: drawn.length };
})()`;
