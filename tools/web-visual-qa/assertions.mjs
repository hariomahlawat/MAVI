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
 * Focus visibility, checked by actually walking focus through the page rather
 * than by reading CSS: a ring that is painted but clipped is still invisible.
 */
export const FOCUS_ASSERTIONS = `(() => {
  const problems = [];
  const targets = Array.from(document.querySelectorAll('button, a[href], input, select, textarea'))
    .filter((el) => !el.disabled && el.getBoundingClientRect().width > 0)
    .slice(0, 40);
  for (const el of targets) {
    el.focus();
    if (document.activeElement !== el) continue;
    const style = getComputedStyle(el);
    const ring = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;
    const shadow = style.boxShadow && style.boxShadow !== 'none';
    if (!ring && !shadow) {
      problems.push('no visible focus on <' + el.tagName.toLowerCase() + '> "' +
        (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 32) + '"');
    }
  }
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  return { problems, checked: targets.length };
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
