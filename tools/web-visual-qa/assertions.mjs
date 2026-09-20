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

  // 1. No horizontal page scroll at any acceptance width.
  if (doc.scrollWidth > doc.clientWidth + 1) {
    problems.push('horizontal page overflow: scrollWidth ' + doc.scrollWidth + ' > clientWidth ' + doc.clientWidth);
  }

  // 2. Interactive controls must not overlap one another. Controls are checked
  //    rather than every node, because text boxes legitimately nest.
  const controls = Array.from(document.querySelectorAll('button, a[href], input, select, textarea'))
    .filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    });
  for (let i = 0; i < controls.length; i++) {
    for (let j = i + 1; j < controls.length; j++) {
      const a = controls[i], b = controls[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
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
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    });
  for (let i = 0; i < leaves.length; i++) {
    for (let j = i + 1; j < leaves.length; j++) {
      const a = leaves[i], b = leaves[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
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

  return { problems, pageWidth: width, declaresFullWidth: full, viewport: doc.clientWidth };
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
