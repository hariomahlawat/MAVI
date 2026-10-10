/**
 * Stage 3.5 S6/X1 (specification §23, §10.1; plan
 * docs/superpowers/plans/2026-10-10-stage3-5-s6-x1-accessibility-assertions.md):
 * the §23 obligations that only a rendered page can settle, each a named
 * manifest rule, each a page-side read built on the T3 primitives
 * (zoomVisibility: the one account of what is seen; zoomPaintsAt: what hides
 * at a point; zoomOwn: what is a control's own). Nothing here is an
 * accessibility engine: every rule is one frozen obligation, judged by the
 * browser's own accessibility tree where a name or a role is the question
 * (cdp.mjs axNames) and by geometry and computed style where seeing is.
 *
 * The functions run inside the page through assertions.toExpression, which
 * inlines each function's `helpers`; they return plain data.
 */
import { zoomClipChain, zoomDescribe, zoomOwn, zoomPaintsAt, zoomVisibility, zoomVisibleRect } from './assertions.mjs';

/**
 * The pointer-operated controls of a page (§10.1, WCAG 2.5.8): the one
 * discovery every target-size judgement uses. A pointer target is a native
 * control, a disclosure's summary, an element with a widget role, an editable
 * region or a canvas hit target — never a bare `[tabindex]`: a programmatic
 * focus target (`main`, a dialog, an inspector) and a keyboard-scrollable
 * region are reached by the keyboard, not pressed by a pointer, and are
 * excluded by construction and named in the account. A control not shown
 * (zoomVisibility: not rendered, collapsed, transparent, inert) is not a
 * target either; the skip link, a pixel until focus reveals it, is
 * a11y.skip-link's.
 *
 * A control's effective target is its hit area (§10.1 "may exceed the visible
 * mark"): a checkbox or radio inside a label, or named by `label[for]`, is
 * pressed through that label, so the label's box is measured and the reading
 * is named; a canvas hit target (`.scene-handle__hit`) is measured by its own
 * box, its visible mark exempt; everything else by its own box.
 */
export function a11yPointerTargets() {
  const POINTER = 'button, a[href], input:not([type="hidden"]), select, textarea, summary, [role="button"], [role="link"], [role="checkbox"], [role="radio"], [role="switch"], [role="tab"], [role="menuitem"], [role="option"], [role="slider"], [contenteditable="true"], .scene-handle__hit';
  const excluded = {};
  const exclude = (reason) => { excluded[reason] = (excluded[reason] ?? 0) + 1; };
  const targets = [];
  for (const el of Array.from(document.querySelectorAll(POINTER))) {
    if (el.matches('.scene-handle__mark')) continue;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') { exclude('disabled'); continue; }
    const v = zoomVisibility(el);
    if (v.hidden === 'not rendered') { exclude('not rendered'); continue; }
    if (v.inert) { exclude('inside an inert region'); continue; }
    if (v.hidden) { exclude('hidden (' + v.hidden + ')'); continue; }
    let box = el.getBoundingClientRect();
    let reading = 'its own box';
    if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio')) {
      const label = el.closest('label') || (el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null);
      if (label) {
        const l = label.getBoundingClientRect();
        box = { left: Math.min(box.left, l.left), top: Math.min(box.top, l.top), right: Math.max(box.right, l.right), bottom: Math.max(box.bottom, l.bottom) };
        box = { ...box, width: box.right - box.left, height: box.bottom - box.top };
        reading = 'its label, the hit area that toggles it';
      }
    } else if (el.matches('.scene-handle__hit')) {
      reading = 'its invisible hit circle (the visible mark is exempt, §10.1)';
    }
    targets.push({ el, box, reading });
  }
  return { targets, excluded };
}
a11yPointerTargets.helpers = [zoomClipChain, zoomVisibleRect, zoomVisibility];

/** The text a control shows (2.5.3): its rendered text, less what is hidden or decorative. */
export function a11yVisibleLabel(el) {
  const parts = [];
  const walk = (node) => {
    if (node.nodeType === 3) { parts.push(node.textContent); return; }
    if (node.nodeType !== 1) return;
    if (node.getAttribute('aria-hidden') === 'true') return;
    const s = getComputedStyle(node);
    if (s.display === 'none' || s.visibility === 'hidden') return;
    const r = node.getBoundingClientRect();
    if (r.width <= 1 && r.height <= 1 && node !== el) return; // the visually-hidden pattern
    if (node.tagName === 'IMG' && node.alt) parts.push(node.alt);
    for (const child of Array.from(node.childNodes)) walk(child);
  };
  walk(el);
  return parts.join(' ');
}

/** Bounded normalisation for "the name contains the label": case, whitespace, punctuation and ellipses. */
export function a11yNormalise(text) {
  return String(text || '').toLowerCase().replace(/[…]|\.{3}/g, ' ').replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim();
}

/**
 * The order the keyboard reaches controls in, against the order they are
 * read in (§23 "tab order follows reading order"; WCAG 2.4.3). Two readings,
 * both held: adjacent tab stops never step back along a line, nor back up a
 * column where the composition is a column (the T3 rule); and, per
 * container — the nearest flex or grid ancestor inside `scope`, else the
 * scope — the tab stops are visited in the container's reading order (rows
 * by vertical overlap, left to right within a row, top to bottom across
 * rows; a column-flow container down its column), so a wrapped grid whose
 * consecutive stops are all diagonal is judged too. Exemptions, named: a
 * control placed by its data (an inline inset on it or an absolutely
 * positioned ancestor — a timeline marker at its offset), which follows the
 * data's order; side-by-side columns are separate containers, read one
 * after another. Returns messages.
 */
export function a11yOrderFindings(scope, label, column) {
  const out = [];
  if (!scope) return out;
  const describe = zoomDescribe;
  const placed = (el) => {
    for (let n = el; n && n !== scope; n = n.parentElement) {
      if (getComputedStyle(n).position === 'absolute' && Array.from(n.style).some((property) => /^(left|top|right|bottom|inset)/.test(property))) return true;
    }
    return false;
  };
  const controls = Array.from(scope.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])'))
    .filter((el) => !el.disabled && el.tabIndex >= 0 && !el.closest('[inert]') && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
    .map((el, index) => ({ el, index, r: el.getBoundingClientRect() }))
    .filter(({ r }) => r.width > 1 && r.height > 1)
    .sort((a, b) => {
      const ta = a.el.tabIndex > 0 ? a.el.tabIndex : Infinity;
      const tb = b.el.tabIndex > 0 ? b.el.tabIndex : Infinity;
      return ta === tb ? a.index - b.index : ta - tb;
    });
  // Per container: the reading order of its own tab stops.
  const containerOf = (el) => {
    for (let n = el.parentElement; n && n !== scope; n = n.parentElement) {
      const d = getComputedStyle(n).display;
      if (/flex|grid/.test(d)) return n;
    }
    return scope;
  };
  for (let i = 1; i < controls.length; i += 1) {
    const a = controls[i - 1]; const b = controls[i];
    // Across containers the order is the containers' (side by side, a column
    // is read before the next); the adjacent checks hold within one.
    if (containerOf(a.el) !== containerOf(b.el)) continue;
    const sameLine = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top) > Math.min(a.r.height, b.r.height) / 2;
    if (sameLine && b.r.right <= a.r.left + 1) {
      out.push('in ' + label + ' the keyboard reaches ' + describe(b.el) + ' after ' + describe(a.el) + ', but it is drawn before it on the same line: focus order is not the visual order');
      return out;
    }
    const sameColumn = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left) > Math.min(a.r.width, b.r.width) / 2;
    if (column && !sameLine && sameColumn && b.r.bottom <= a.r.top + 1 && !placed(a.el) && !placed(b.el)) {
      out.push('in ' + label + ' the keyboard reaches ' + describe(b.el) + ' after ' + describe(a.el) + ', but it is drawn above it in the same column: focus order is not the visual order');
      return out;
    }
  }
  const groups = new Map();
  for (const c of controls) {
    if (placed(c.el)) continue;
    const k = containerOf(c.el);
    groups.set(k, [...(groups.get(k) ?? []), c]);
  }
  for (const [container, stops] of groups) {
    if (stops.length < 2) continue;
    const s = getComputedStyle(container);
    const columnFlow = (s.display.includes('flex') && s.flexDirection.startsWith('column')) || (s.display.includes('grid') && s.gridAutoFlow.startsWith('column'));
    const overlap = (p, q, axis) => (axis === 'y'
      ? Math.min(p.r.bottom, q.r.bottom) - Math.max(p.r.top, q.r.top) > Math.min(p.r.height, q.r.height) / 2
      : Math.min(p.r.right, q.r.right) - Math.max(p.r.left, q.r.left) > Math.min(p.r.width, q.r.width) / 2);
    // Lines (or columns): clusters by overlap on the cross axis, each ordered along the main axis.
    const lines = [];
    for (const stop of stops) {
      const line = lines.find((l) => l.some((m) => overlap(m, stop, columnFlow ? 'x' : 'y')));
      if (line) line.push(stop); else lines.push([stop]);
    }
    const lineKey = (l) => (columnFlow ? Math.min(...l.map((m) => m.r.left)) : Math.min(...l.map((m) => m.r.top)));
    lines.sort((p, q) => lineKey(p) - lineKey(q));
    const visual = lines.flatMap((l) => l.slice().sort((p, q) => (columnFlow ? p.r.top - q.r.top : p.r.left - q.r.left)));
    for (let i = 0; i < stops.length; i += 1) {
      if (visual[i] !== stops[i]) {
        out.push('in ' + label + ' the keyboard visits ' + describe(stops[i].el) + ' where the reading order of ' + describe(container) + ' has ' + describe(visual[i].el) + ': focus order is not the reading order');
        return out;
      }
    }
  }
  return out;
}
a11yOrderFindings.helpers = [zoomDescribe];

/**
 * The X1 page rules that need no accessibility tree: target size, role
 * contracts, live regions rendered, state cues, the spatial twin, reading
 * order, tab order, focus not obscured; and the controls tagged for the
 * accessibility-tree pass (a11y.names, a11y.form-fields, a11y.tooltips),
 * whose verdicts a11yNamesJudge gives once Chromium has named them.
 *
 * @param {{ tier: string, archetype: string|null, surface: string|null }} input
 */
export function a11yAssertions(input) {
  const findings = [];
  const evaluated = new Set();
  const fail = (rule, message) => findings.push({ rule, message });
  const describe = zoomDescribe;
  const measured = {};
  const rendered = (el) => { const v = zoomVisibility(el); return !v.hidden && !v.inert; };
  const namesOnly = Boolean(input?.namesOnly);

  // --- a11y.target-size (§10.1, WCAG 2.5.8) --------------------------------
  if (!namesOnly) {
    const { targets, excluded } = a11yPointerTargets();
    const small = [];
    for (const { el, box, reading } of targets) {
      if (box.width < 24 - 0.5 || box.height < 24 - 0.5) small.push(describe(el) + ' ' + Math.round(box.width) + 'x' + Math.round(box.height) + ' (' + reading + ')');
    }
    evaluated.add('a11y.target-size');
    if (small.length) fail('a11y.target-size', small.length + ' pointer target(s) under 24x24: ' + small.slice(0, 6).join(', '));
    measured.targets = { judged: targets.length, excluded };
  }

  // --- a11y.role-contract (§23: a role's contract honoured or not claimed) ---
  if (!namesOnly) {
    const resolves = (ids) => ids.split(/\s+/).filter(Boolean).every((id) => document.getElementById(id));
    for (const el of Array.from(document.querySelectorAll('[aria-controls], [aria-labelledby], [aria-describedby], [aria-errormessage], [aria-activedescendant], [aria-owns]'))) {
      for (const attr of ['aria-controls', 'aria-labelledby', 'aria-describedby', 'aria-errormessage', 'aria-activedescendant', 'aria-owns']) {
        const ids = el.getAttribute(attr);
        if (ids && !resolves(ids)) fail('a11y.role-contract', describe(el) + ' ' + attr + '="' + ids + '" names an id that does not resolve');
      }
    }
    for (const el of Array.from(document.querySelectorAll('[aria-expanded]')).filter(rendered)) {
      const expanded = el.getAttribute('aria-expanded') === 'true';
      const controls = el.getAttribute('aria-controls');
      const region = controls ? document.getElementById(controls.split(/\s+/)[0]) : (el.tagName === 'SUMMARY' ? el.parentElement : null);
      if (!region) { fail('a11y.role-contract', describe(el) + ' is aria-expanded="' + el.getAttribute('aria-expanded') + '" with no controlled region (aria-controls, or a details)'); continue; }
      if (expanded && region.tagName !== 'DETAILS') {
        const s = getComputedStyle(region);
        if (s.display === 'none' || s.visibility === 'hidden' || region.hidden) fail('a11y.role-contract', describe(el) + ' is aria-expanded="true" but its region ' + describe(region) + ' is not rendered');
      }
    }
    for (const option of Array.from(document.querySelectorAll('[role="option"]'))) {
      const inner = option.querySelector('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (inner) fail('a11y.role-contract', describe(option) + ' is an option holding a focusable ' + describe(inner));
    }
    for (const listbox of Array.from(document.querySelectorAll('[role="listbox"]'))) {
      const stray = Array.from(listbox.querySelectorAll('[role]')).find((n) => !['option', 'group'].includes(n.getAttribute('role')));
      if (stray) fail('a11y.role-contract', describe(listbox) + ' is a listbox holding ' + describe(stray) + ' (role ' + stray.getAttribute('role') + ')');
    }
    const NATIVE = { button: 'button', link: 'a[href]', checkbox: 'input[type=checkbox]', radio: 'input[type=radio]', textbox: 'input or textarea', list: 'ul or ol', listitem: 'li', heading: 'h1–h6', table: 'table', row: 'tr', cell: 'td', columnheader: 'th', navigation: 'nav', main: 'main', banner: 'header' };
    for (const el of Array.from(document.querySelectorAll('div[role], span[role], p[role], section[role], article[role]'))) {
      const role = el.getAttribute('role');
      if (NATIVE[role]) fail('a11y.role-contract', describe(el) + ' claims role="' + role + '" where the native ' + NATIVE[role] + ' carries the semantics (§23: semantic HTML first)');
    }
    for (const el of Array.from(document.querySelectorAll('button[role], input[role], select[role], textarea[role], a[href][role]'))) {
      const role = el.getAttribute('role');
      const implicit = { BUTTON: 'button', A: 'link', INPUT: el.type === 'checkbox' ? 'checkbox' : el.type === 'radio' ? 'radio' : 'textbox', SELECT: 'combobox', TEXTAREA: 'textbox' }[el.tagName];
      if (role !== implicit && !(el.tagName === 'INPUT' && ['combobox', 'searchbox', 'spinbutton', 'switch'].includes(role)) && !(el.tagName === 'A' && role === 'button'))
        fail('a11y.role-contract', describe(el) + ' re-roles a native control as "' + role + '"');
    }
    evaluated.add('a11y.role-contract');
  }

  // --- a11y.live-regions (rendered part; mounting is a11yLiveCheck's) ------
  if (!namesOnly) {
    const regions = Array.from(document.querySelectorAll('[aria-live], [role="status"], [role="alert"], [role="log"]')).filter((el) => el.getAttribute('aria-live') !== 'off');
    for (const el of regions) {
      const s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden') fail('a11y.live-regions', describe(el) + ' is a live region that is not rendered (' + (s.display === 'none' ? 'display none' : 'visibility hidden') + '), so what it announces is never shown');
      if (el.closest('[aria-hidden="true"]')) fail('a11y.live-regions', describe(el) + ' is a live region inside aria-hidden, so it announces nothing');
    }
    evaluated.add('a11y.live-regions');
    measured.liveRegions = regions.length;
  }

  // --- a11y.state-cues (§23: a non-colour cue for every state) --------------
  if (!namesOnly) {
    const NONCOLOUR = ['border-left-width', 'border-right-width', 'border-top-width', 'border-bottom-width', 'border-left-style', 'border-bottom-style', 'box-shadow', 'font-weight', 'text-decoration-line', 'outline-style', 'outline-width', 'transform', 'stroke-width', 'stroke-dasharray'];
    const luminance = (rgb) => {
      const m = /rgba?\(([^)]+)\)/.exec(rgb); if (!m) return null;
      const [r, g, b, a] = m[1].split(',').map((v) => parseFloat(v));
      if (a === 0) return null;
      const ch = (c) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b);
    };
    const ratio = (x, y) => { const a = luminance(x); const b = luminance(y); if (a === null || b === null) return null; return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); };
    // The background seen at an element: its own, else the first opaque one behind it.
    const backgroundOf = (el) => {
      for (let n = el; n; n = n.parentElement) {
        const bg = getComputedStyle(n).backgroundColor;
        if (luminance(bg) !== null) return bg;
      }
      return 'rgb(255, 255, 255)';
    };
    const STATE_CLASSES = /^(is-selected|is-active|is-current|is-invalid|is-off)$/;
    const cued = (el, peer) => {
      if (!peer) return null;
      const a = getComputedStyle(el); const b = getComputedStyle(peer);
      for (const p of NONCOLOUR) if (a.getPropertyValue(p) !== b.getPropertyValue(p)) return p;
      for (const pseudo of ['::before', '::after']) {
        const pa = getComputedStyle(el, pseudo); const pb = getComputedStyle(peer, pseudo);
        if (pa.content !== pb.content && pa.content !== 'none' && pa.content !== 'normal') return pseudo + ' content';
      }
      // A luminance step of 3:1 between the states is a non-colour difference (WCAG 1.4.1).
      const lr = ratio(backgroundOf(el), backgroundOf(peer));
      if (lr !== null && lr >= 3) return 'background luminance ' + lr.toFixed(1) + ':1';
      if (el.querySelector('.scene-handle') && !peer.querySelector('.scene-handle')) return 'handles shown';
      // SVG: the state is drawn by the first mark inside (a handle's circle, a
      // zone's polygon): its stroke width, dash, radius, or a fill luminance step.
      // SVG: the state is drawn by the marks inside (a handle's hit circle and
      // its mark, a zone's polygon), compared pairwise in document order: a
      // stroke width, dash, radius, or a fill or stroke luminance step on any.
      const marksA = Array.from(el.querySelectorAll('circle, polygon, line, path')); const marksB = Array.from(peer.querySelectorAll('circle, polygon, line, path'));
      for (let i = 0; i < Math.min(marksA.length, marksB.length); i += 1) {
        const ma = getComputedStyle(marksA[i]); const mb = getComputedStyle(marksB[i]);
        for (const p of ['stroke-width', 'stroke-dasharray', 'r']) if (ma.getPropertyValue(p) !== mb.getPropertyValue(p)) return 'mark ' + p;
        const fr = ratio(ma.fill, mb.fill);
        if (fr !== null && fr >= 3) return 'mark fill luminance ' + fr.toFixed(1) + ':1';
        const sr = ratio(ma.stroke, mb.stroke);
        if (sr !== null && sr >= 3) return 'mark stroke luminance ' + sr.toFixed(1) + ':1';
      }
      return null;
    };
    const peerOf = (el) => {
      const classes = Array.from(el.classList).filter((c) => !STATE_CLASSES.test(c));
      return Array.from(el.parentElement?.children ?? []).find((sib) => sib !== el && sib.tagName === el.tagName
        && !sib.matches('[aria-current]:not([aria-current="false"]), [aria-selected="true"], .is-selected, .is-active')
        && classes.every((c) => sib.classList.contains(c)));
    };
    let judged = 0; let unjudged = 0;
    for (const el of Array.from(document.querySelectorAll('[aria-current]:not([aria-current="false"]), [aria-selected="true"], .is-selected, .is-active')).filter(rendered)) {
      if (el.hasAttribute('aria-pressed')) continue; // pressed.visible's
      const peer = peerOf(el);
      if (!peer) { unjudged += 1; continue; }
      judged += 1;
      const cue = cued(el, peer) ?? (el.querySelector('.icon, svg, [aria-hidden="true"]:not(:empty)') && !peer.querySelector('.icon, svg, [aria-hidden="true"]:not(:empty)') ? 'a glyph' : null);
      if (!cue) fail('a11y.state-cues', describe(el) + ' is selected/current, but nothing but colour tells it from ' + describe(peer) + ' (no border, bar, shadow, weight, glyph or a 3:1 luminance step)');
    }
    for (const el of Array.from(document.querySelectorAll('.scene-zone.is-invalid, .scene-line.is-invalid'))) {
      const stroke = el.querySelector('polygon, line, path, .scene-line__segment');
      const dash = stroke ? getComputedStyle(stroke).strokeDasharray : 'none';
      judged += 1;
      if (!dash || dash === 'none') fail('a11y.state-cues', describe(el) + ' is invalid geometry told by its stroke colour alone (no dash pattern)');
    }
    const badges = Array.from(document.querySelectorAll('.badge, [data-status]')).filter(rendered);
    const byText = new Map();
    for (const el of badges) {
      judged += 1;
      const text = (el.textContent || '').trim();
      if (!text) fail('a11y.state-cues', describe(el) + ' is a status badge with no text: its tone is its only cue');
      const tone = Array.from(el.classList).find((c) => /^badge--/.test(c)) ?? '';
      const key = text.toLowerCase();
      const seen = byText.get(key);
      if (seen && seen !== tone) fail('a11y.state-cues', 'two status badges read "' + text + '" with different tones (' + seen + ', ' + tone + '): the tone alone tells them apart');
      byText.set(key, tone);
    }
    for (const el of Array.from(document.querySelectorAll('[class*="coverage--"]')).filter(rendered)) {
      judged += 1;
      if (!(el.querySelector('.icon, svg') && (el.textContent || '').trim())) fail('a11y.state-cues', describe(el) + ' is a coverage state without both an icon and text');
    }
    const ticks = Array.from(document.querySelectorAll('.evidence-timeline__marker[data-kind] .evidence-timeline__marker-tick'));
    const kinds = new Map();
    for (const t of ticks) {
      const kind = t.closest('[data-kind]').getAttribute('data-kind');
      const s = getComputedStyle(t);
      if (!kinds.has(kind)) kinds.set(kind, s.transform + '|' + s.height + '|' + s.top + '|' + s.borderRadius);
    }
    if (kinds.size >= 2) {
      judged += 1;
      const shapes = new Set(kinds.values());
      if (shapes.size < kinds.size) fail('a11y.state-cues', 'timeline marker kinds ' + Array.from(kinds.keys()).join(', ') + ' share one tick shape: colour alone tells them apart');
    }
    if (judged) evaluated.add('a11y.state-cues');
    measured.stateCues = { judged, unjudged };
  }

  // --- a11y.spatial-twin (§23: the canvas's list; the timeline's entries) ---
  if (!namesOnly) {
    let judged = 0;
    const objects = Array.from(document.querySelectorAll('.scene-zone[data-object-key], .scene-line[data-object-key]'));
    const rows = Array.from(document.querySelectorAll('li[data-object-key]'));
    if (objects.length || rows.length) {
      judged += 1;
      const rowFor = new Map(rows.map((li) => [li.getAttribute('data-object-key'), li]));
      for (const obj of objects) {
        const key = obj.getAttribute('data-object-key');
        const li = rowFor.get(key);
        if (!li) { fail('a11y.spatial-twin', describe(obj) + ' (' + key + ') is drawn with no entry in the object list'); continue; }
        const text = (li.textContent || '').replace(/\s+/g, ' ').trim();
        const control = li.querySelector('button, a[href], [tabindex]:not([tabindex="-1"])');
        if (!control) fail('a11y.spatial-twin', 'the entry for ' + key + ' offers no control: the twin must be the control the pointer uses');
        const polygon = obj.classList.contains('scene-line') ? null : obj.querySelector('polygon');
        if (polygon) {
          const expected = polygon.points.length;
          const points = li.querySelectorAll('.scene-navigator__points li, .scene-navigator__coordinates li');
          if (!points.length) fail('a11y.spatial-twin', 'the entry for ' + key + ' names no coordinates (§23: the list names each object, its state and its coordinates)');
          else if (points.length !== expected) fail('a11y.spatial-twin', 'the entry for ' + key + ' lists ' + points.length + ' coordinate(s) for a polygon of ' + expected + ' vertices');
          else if (Array.from(points).some((p) => !/-?\d/.test(p.textContent))) fail('a11y.spatial-twin', 'the entry for ' + key + ' lists a coordinate with no number in it');
          const sides = Array.from(points).map((p) => p.textContent);
          if (sides.length !== new Set(sides).size && expected !== new Set(Array.from(polygon.points).map((p) => p.x + ',' + p.y)).size) { /* repeated vertices are the drawing's */ }
        } else {
          const endpoints = li.querySelector('.scene-navigator__endpoints');
          if (!endpoints || (endpoints.textContent.match(/-?\d+(\.\d+)?/g) || []).length < 4) fail('a11y.spatial-twin', 'the entry for ' + key + ' does not name both endpoints of the line');
        }
        if (!/\b(enabled|disabled|invalid|selected|zone|line|vertices|vertex)\b/i.test(text)) fail('a11y.spatial-twin', 'the entry for ' + key + ' names no state');
      }
      for (const [key] of rowFor) if (!objects.some((o) => o.getAttribute('data-object-key') === key)) fail('a11y.spatial-twin', 'the object list names ' + key + ', which is not drawn');
    }
    const intervals = Array.from(document.querySelectorAll('.evidence-timeline__interval, .evidence-timeline__marker'));
    if (intervals.length) {
      judged += 1;
      for (const li of intervals) {
        const named = (li.getAttribute('aria-label') || li.textContent || '').trim();
        const control = li.matches('button, a[href], [tabindex]') ? li : li.querySelector('button, a[href], [tabindex]:not([tabindex="-1"])');
        if (!named) fail('a11y.spatial-twin', describe(li) + ' is a timeline entry with no name');
        if (!control && li.matches('.evidence-timeline__marker')) fail('a11y.spatial-twin', describe(li) + ' is a timeline marker with no control');
      }
    }
    if (judged) evaluated.add('a11y.spatial-twin');
    measured.twin = { objects: objects.length, rows: rows.length, intervals: intervals.length };
  }

  // --- a11y.reading-order (WCAG 1.3.2: DOM order is the reading order) -----
  if (!namesOnly) {
    const containers = Array.from(document.querySelectorAll('tbody, ul, ol, dl, main .page, main .workspace, .state-region, .context-bar, .workspace__body'));
    let judged = 0;
    const placedChild = (el) => getComputedStyle(el).position !== 'static' && Array.from(el.style).some((p) => /^(left|top|right|bottom|inset)/.test(p));
    for (const container of containers) {
      if (container.closest('[inert], [aria-hidden="true"], svg')) continue;
      const children = Array.from(container.children).filter((el) => {
        const s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || s.position === 'absolute' || s.position === 'fixed' || placedChild(el)) return false;
        const r = el.getBoundingClientRect();
        return r.width > 1 && r.height > 1 && (el.textContent || '').trim();
      }).map((el, index) => ({ el, index, r: el.getBoundingClientRect() }));
      if (children.length < 2) continue;
      judged += 1;
      const s = getComputedStyle(container);
      const columnFlow = (s.display.includes('flex') && s.flexDirection.startsWith('column')) || (s.display.includes('grid') && s.gridAutoFlow.startsWith('column'));
      const overlapY = (p, q) => Math.min(p.r.bottom, q.r.bottom) - Math.max(p.r.top, q.r.top) > Math.min(p.r.height, q.r.height) / 2;
      const lines = [];
      for (const c of children) {
        const line = lines.find((l) => l.some((m) => overlapY(m, c)));
        if (line) line.push(c); else lines.push([c]);
      }
      lines.sort((p, q) => Math.min(...p.map((m) => m.r.top)) - Math.min(...q.map((m) => m.r.top)));
      const visual = lines.flatMap((l) => l.slice().sort((p, q) => p.r.left - q.r.left));
      for (let i = 0; i < children.length; i += 1) {
        if (visual[i] !== children[i]) {
          fail('a11y.reading-order', 'in ' + describe(container) + ' the document reads ' + describe(children[i].el) + ' where the page shows ' + describe(visual[i].el) + (columnFlow ? ' (a column-flow container)' : '') + ': the reading order is not the visual order');
          break;
        }
      }
    }
    if (judged) evaluated.add('a11y.reading-order');
    measured.readingOrder = { containers: judged };
  }

  // --- a11y.tab-order (§23, WCAG 2.4.3) ---------------------------------------
  if (!namesOnly) {
    const modals = Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).filter((m) => !m.closest('[inert]'));
    const top = modals[modals.length - 1];
    const scopes = [[document.querySelector('.context-bar'), 'the Context Bar', false], [top ?? document.querySelector('main .workspace, main .page'), top ? 'the open overlay' : 'the workspace', input?.tier === 'C']];
    let judged = 0;
    for (const [scope, label, column] of scopes) {
      if (!scope) continue;
      judged += 1;
      for (const message of a11yOrderFindings(scope, label, column)) fail('a11y.tab-order', message);
    }
    if (judged) evaluated.add('a11y.tab-order');
  }

  // --- a11y.focus-not-obscured (WCAG 2.4.11 at the anchors) ------------------
  if (!namesOnly) {
    const scrolled = [document.scrollingElement, ...document.querySelectorAll('*')]
      .filter((el) => el && (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth))
      .map((el) => [el, el.scrollTop, el.scrollLeft]);
    const before = document.activeElement;
    const reveal = document.createElement('style');
    reveal.textContent = '*, *::before, *::after { pointer-events: auto !important; }';
    document.head.appendChild(reveal);
    let judged = 0;
    const stickyLayer = (node) => {
      for (let n = node; n && n !== document.documentElement; n = n.parentElement) {
        const p = getComputedStyle(n).position;
        if (p === 'fixed' || p === 'sticky') return n;
      }
      return null;
    };
    try {
      for (const el of Array.from(document.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])'))) {
        if (el.disabled || el.closest('[inert]')) continue;
        const v0 = zoomVisibility(el);
        if (v0.hidden || !v0.reachable) continue;
        el.focus();
        if (document.activeElement !== el) continue;
        judged += 1;
        const v = zoomVisibility(el);
        if (v.seen.width < 1 || v.seen.height < 1) continue; // out of view is a11y.zoom-200's and the overflow rules'
        const x = (v.seen.left + v.seen.right) / 2; const y = (v.seen.top + v.seen.bottom) / 2;
        for (const node of document.elementsFromPoint(x, y)) {
          if (zoomOwn(node, el)) break;
          if (node.contains(el)) continue;
          const layer = stickyLayer(node);
          if (layer && zoomPaintsAt(node, x, y)) { fail('a11y.focus-not-obscured', describe(el) + ', focused, is under ' + describe(layer === node ? node : layer) + ' (a ' + getComputedStyle(layer).position + ' layer) at its middle'); break; }
        }
      }
    } finally {
      reveal.remove();
      if (before instanceof HTMLElement && before !== document.body && before.isConnected) before.focus({ preventScroll: true });
      else if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
      for (const [el, top, left] of scrolled) { el.scrollTop = top; el.scrollLeft = left; }
    }
    if (judged) evaluated.add('a11y.focus-not-obscured');
    measured.focusNotObscured = judged;
  }

  // --- Controls for the accessibility-tree pass (names, fields, tooltips) ----
  const tagged = [];
  {
    const CONTROLS = 'button, a[href], input:not([type="hidden"]), select, textarea, summary, [role="button"], [role="link"], [role="checkbox"], [role="radio"], [role="switch"], [role="tab"], [role="menuitem"], [role="option"], [role="slider"], [role="combobox"], [contenteditable="true"]';
    let index = 0;
    for (const el of Array.from(document.querySelectorAll(CONTROLS))) {
      if (!rendered(el)) continue;
      const v = zoomVisibility(el);
      el.setAttribute('data-vqa-ax', String(index));
      const isField = /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) && !/^(submit|button|reset|image|checkbox|radio|file|range|color)$/.test(el.type || '');
      const describedIds = (el.getAttribute('aria-describedby') || '') + ' ' + (el.getAttribute('aria-errormessage') || '');
      const described = describedIds.split(/\s+/).filter(Boolean).map((id) => document.getElementById(id)).filter(Boolean);
      const errorText = described.map((d) => (d.textContent || '').trim()).filter(Boolean);
      const announced = described.some((d) => d.closest('[role="alert"], [aria-live]'));
      tagged.push({
        index, description: describe(el), visibleLabel: a11yVisibleLabel(el), title: el.getAttribute('title') || '',
        railItem: Boolean(el.closest('nav[aria-label="Primary"], .sidebar, .rail')) && el.tagName === 'A',
        railCollapsed: Boolean(document.querySelector('[aria-controls][aria-expanded="false"]') && el.closest('.sidebar')),
        isField, type: el.type || el.tagName.toLowerCase(), placeholder: el.getAttribute('placeholder') || '',
        invalid: el.getAttribute('aria-invalid') === 'true', errorText, announced, focused: document.activeElement === el,
        onScreen: v.seen.width >= 1 && v.seen.height >= 1,
      });
      index += 1;
    }
    // Tooltips and titles anywhere, for a11y.tooltips (§23).
    const tooltips = [];
    for (const el of Array.from(document.querySelectorAll('[title], [role="tooltip"]'))) {
      if (el.closest('svg') && el.tagName !== 'svg') continue;
      const text = el.getAttribute('role') === 'tooltip' ? (el.textContent || '').trim() : el.getAttribute('title');
      if (!text) continue;
      // A tooltip nobody can reach — its host not rendered, behind an overlay
      // or in a hidden composition — says nothing to the operator here.
      const host = el.getAttribute('role') === 'tooltip' ? (el.closest('.tooltip-anchor') ?? el.parentElement) : el;
      if (!host || !rendered(host)) continue;
      const control = el.closest(CONTROLS) || (el.getAttribute('role') === 'tooltip' ? el.closest('.tooltip-anchor')?.querySelector(CONTROLS) : null) || el.querySelector(CONTROLS);
      const truncated = (node) => { const s = getComputedStyle(node); return s.textOverflow === 'ellipsis' && node.scrollWidth > node.clientWidth + 1; };
      const anchor = el.getAttribute('role') === 'tooltip' ? el.closest('.tooltip-anchor') : null;
      const truncatedHolder = [el, ...Array.from(el.querySelectorAll('*')), el.closest('.truncate'), ...(anchor ? Array.from(anchor.querySelectorAll('*')) : [])].filter(Boolean).find(truncated);
      // A timestamp's full form over its compact form (§24): a `<time>` with
      // its datetime, or a title that spells out the day and time the
      // element shows compactly (the same HH:MM, the same day number).
      const visible = (el.textContent || '').replace(/\s+/g, ' ').trim();
      const times = (s) => (s.match(/\b\d{1,2}:\d{2}\b/g) || []);
      const days = (s) => (s.match(/\b\d{1,2}\b(?=\s+[A-Z][a-z]{2,8})/g) || []);
      const expandsTime = times(visible).length > 0 && times(visible).every((v) => text.includes(v)) && days(visible).every((d) => days(text).includes(d));
      tooltips.push({
        description: describe(el), text, controlIndex: control ? Number(control.getAttribute('data-vqa-ax')) : null,
        isTime: (el.tagName === 'TIME' && Boolean(el.getAttribute('datetime'))) || expandsTime,
        truncated: Boolean(truncatedHolder) || Boolean(el.closest('.truncate') && (el.closest('.truncate').scrollWidth > el.closest('.truncate').clientWidth + 1)),
        heading: /^(H[1-6]|TH)$/.test(el.tagName) || el.closest('th') !== null,
        elsewhere: a11yNormalise(document.body.innerText).includes(a11yNormalise(text)),
        isRoleTooltip: el.getAttribute('role') === 'tooltip',
      });
    }
    measured.tagged = tagged.length;
    measured.tooltips = tooltips.length;
    measured.tooltipList = tooltips;
  }

  return { findings, evaluated: Array.from(evaluated), measured, controls: tagged };
}
a11yAssertions.helpers = [zoomDescribe, zoomOwn, zoomClipChain, zoomVisibleRect, zoomPaintsAt, zoomVisibility, a11yPointerTargets, a11yVisibleLabel, a11yNormalise, a11yOrderFindings];

/**
 * The verdicts that need Chromium's accessibility tree (a11y.names,
 * a11y.form-fields, a11y.tooltips), given the controls a11yAssertions tagged
 * and the names cdp.axNames read for them. Removes the tags.
 *
 * @param {{ controls: Array, names: Array<{ index: number, name: string, source: string|null }>, tooltips: Array }} input
 */
export function a11yNamesJudge(input) {
  const findings = [];
  const fail = (rule, message) => findings.push({ rule, message });
  const named = new Map(input.names.map((n) => [n.index, n]));
  let judged = 0; let fields = 0;
  let unresolved = 0;
  for (const c of input.controls) {
    const ax = named.get(c.index);
    if (!ax) { unresolved += 1; continue; }
    const name = (ax.name ?? '').trim();
    const source = ax.source ?? null;
    judged += 1;
    if (!name) {
      fail('a11y.names', c.description + ' has no accessible name');
    } else {
      const label = a11yNormalise(c.visibleLabel).replace(/\s+/g, '');
      const flat = a11yNormalise(name).replace(/\s+/g, '');
      if (label && !flat.includes(label) && !label.includes(flat)) {
        fail('a11y.names', c.description + ' is named "' + name.slice(0, 60) + '" but shows "' + c.visibleLabel.trim().slice(0, 60) + '": the name does not contain the visible label (WCAG 2.5.3)');
      }
      if (source === 'title' && !(c.railItem && c.railCollapsed)) {
        fail('a11y.names', c.description + ' is named by its title alone ("' + name.slice(0, 60) + '"): a tooltip is never a control\'s only label (§23; the one exception is the collapsed rail item)');
      }
    }
    if (c.isField) {
      fields += 1;
      if (name && source === 'placeholder') fail('a11y.form-fields', c.description + ' is labelled by its placeholder alone ("' + name.slice(0, 60) + '")');
      if (!name) fail('a11y.form-fields', c.description + ' is a form field with no label');
      if (c.invalid) {
        if (!c.errorText.length) fail('a11y.form-fields', c.description + ' is aria-invalid with no rendered error message associated (aria-describedby/aria-errormessage)');
        else if (!c.announced && !c.focused) fail('a11y.form-fields', c.description + ' has its error "' + c.errorText[0].slice(0, 60) + '" associated but neither announced (a live or alert region) nor focused');
      }
    }
  }
  let tooltips = 0;
  for (const t of input.tooltips) {
    tooltips += 1;
    const control = t.controlIndex === null ? null : input.controls.find((c) => c.index === t.controlIndex);
    const name = control ? a11yNormalise(named.get(control.index)?.name ?? '') : '';
    const text = a11yNormalise(t.text);
    const stripped = a11yNormalise(t.text.replace(/\s*(\(.*\)|·.*|—.*)$/u, ''));
    const classes = [];
    if (control && name && (text === name || name.includes(text))) classes.push('N');
    if (control && stripped && (stripped === name || name.includes(stripped) || (control.visibleLabel && a11yNormalise(control.visibleLabel) === stripped))) classes.push('K');
    if (t.truncated) classes.push('V');
    if (t.isTime) classes.push('F');
    if (t.elsewhere || t.heading) classes.push('S');
    if (!classes.length) fail('a11y.tooltips', t.description + ' carries "' + t.text.slice(0, 80) + '" only in a tooltip: not its control\'s name, a truncated value, a timestamp\'s full form, nor stated elsewhere on the page (§23)');
  }
  for (const el of Array.from(document.querySelectorAll('[data-vqa-ax]'))) el.removeAttribute('data-vqa-ax');
  const evaluated = [];
  if (judged) evaluated.push('a11y.names');
  if (fields) evaluated.push('a11y.form-fields');
  if (tooltips) evaluated.push('a11y.tooltips');
  return { findings, evaluated, measured: { controls: judged, fields, tooltips, unresolved } };
}
a11yNamesJudge.helpers = [a11yNormalise];

/** Before a preparation (a11y.live-regions): the live regions the page has. */
export function a11yLiveMark() {
  const LIVE = '[aria-live], [role="status"], [role="alert"], [role="log"]';
  window.__vqaLive = new Set(Array.from(document.querySelectorAll(LIVE)));
  window.__vqaLiveContainers = new Set(Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .inspector, .drawer')));
  // What the preparation does to the document, batch by batch: a region
  // inserted in one batch and given its text in a later one was mounted
  // before it was populated (its text is a change in an existing region); a
  // region whose text is there by the end of the batch that inserted it was
  // inserted populated. A batch is one observer callback: the mutations of
  // one task, so an insertion and a text set in the same task are one batch.
  window.__vqaLiveObserver?.disconnect();
  const tracked = new WeakMap();
  window.__vqaLiveTracked = tracked;
  let batch = 0;
  const regionOf = (node) => (node.nodeType === 1 ? node : node.parentElement)?.closest(LIVE) ?? null;
  const observer = new MutationObserver((records) => {
    batch += 1;
    for (const record of records) {
      for (const added of Array.from(record.addedNodes)) {
        if (added.nodeType !== 1) continue;
        const regions = [added.matches(LIVE) ? added : null, ...Array.from(added.querySelectorAll(LIVE))].filter(Boolean);
        for (const region of regions) if (!tracked.has(region) && !window.__vqaLive.has(region)) tracked.set(region, { insertedBatch: batch, populatedBatch: null });
      }
    }
    for (const record of records) {
      const region = regionOf(record.target);
      const info = region && tracked.get(region);
      if (info && info.populatedBatch === null && (region.textContent || '').trim()) info.populatedBatch = batch;
    }
  });
  observer.observe(document.documentElement, { subtree: true, childList: true, characterData: true });
  window.__vqaLiveObserver = observer;
  return window.__vqaLive.size;
}

/**
 * After a preparation (a11y.live-regions): every live region holding text now
 * was mounted before the preparation — a region inserted together with its
 * message is not announced (§23: status regions mounted before populated).
 * A region inside an overlay the preparation opened is judged with it: the
 * overlay is new, so its regions are new, and the rule asks that the
 * region be mounted before its message, which an overlay that opens with its
 * message cannot show — unless the message came from the operator's own
 * action in that overlay (a second step), which the states declare by
 * preparing in steps.
 */
export function a11yLiveCheck() {
  const findings = [];
  const marked = window.__vqaLive ?? new Set();
  let judged = 0;
  // An alert (role="alert", aria-live="assertive") is announced when it is
  // inserted — that is its contract — so an error inserted with its message
  // is right; a status region (polite) is announced only on change, so one
  // inserted with its message is silent.
  for (const el of Array.from(document.querySelectorAll('[aria-live], [role="status"], [role="log"]'))) {
    if (el.getAttribute('role') === 'alert' || el.getAttribute('aria-live') === 'assertive' || el.getAttribute('aria-live') === 'off') continue;
    if (!(el.textContent || '').trim()) continue;
    // A region inside an overlay or inspector the preparation itself opened
    // is mounted with that component: what the operator opened is read from
    // the component's own name and focus, and the region's later changes are
    // announced from then on.
    const container = el.closest('[role="dialog"], [aria-modal="true"], .inspector, .drawer');
    if (container && !marked.has(container) && !(window.__vqaLiveContainers ?? new Set()).has(container)) continue;
    judged += 1;
    if (marked.has(el)) continue;
    // Inserted during the preparation: it passes only if its text arrived in
    // a later batch than its insertion (a11yLiveMark's observer).
    const info = window.__vqaLiveTracked?.get(el);
    const populatedLater = Boolean(info) && info.populatedBatch !== null && info.populatedBatch > info.insertedBatch;
    if (!populatedLater) findings.push({ rule: 'a11y.live-regions', message: zoomDescribe(el) + ' was inserted already holding "' + (el.textContent || '').trim().slice(0, 60) + '": a status region is mounted before it is populated (its text set in a later task), or it is not announced' });
  }
  window.__vqaLiveObserver?.disconnect();
  return { findings, judged };
}
a11yLiveCheck.helpers = [zoomDescribe];

/**
 * a11y.shortcuts-in-text-entry (§23, WCAG 2.1.4): the first text-entry
 * control, focused, and the counts a shortcut would change. The keys are
 * pressed by the harness (cdp.press), and a11yShortcutsAfter judges.
 */
export function a11yShortcutsBefore() {
  const field = Array.from(document.querySelectorAll('input:not([type]), input[type="text"], input[type="search"], input[type="number"], input[type="email"], input[type="url"], textarea, [contenteditable="true"]'))
    .find((el) => { const v = zoomVisibility(el); return !el.disabled && !el.readOnly && !v.hidden && !v.inert; });
  if (!field) return { field: null };
  field.focus();
  if (document.activeElement !== field) return { field: null, refused: zoomDescribe(field) };
  window.__vqaShortcutField = field;
  window.__vqaShortcutValue = 'value' in field ? field.value : field.textContent;
  return {
    field: zoomDescribe(field),
    dialogs: document.querySelectorAll('[role="dialog"]').length,
    objects: document.querySelectorAll('.scene-zone, .scene-line').length,
    sceneEditor: Boolean(document.querySelector('.workspace--workbench')),
    url: location.pathname,
  };
}
a11yShortcutsBefore.helpers = [zoomDescribe, zoomClipChain, zoomVisibleRect, zoomVisibility];

export function a11yShortcutsAfter(input) {
  const findings = [];
  const field = window.__vqaShortcutField;
  const value = field && ('value' in field ? field.value : field.textContent);
  const after = { dialogs: document.querySelectorAll('[role="dialog"]').length, objects: document.querySelectorAll('.scene-zone, .scene-line').length, url: location.pathname };
  if (after.dialogs > input.dialogs) findings.push({ rule: 'a11y.shortcuts-in-text-entry', message: 'the "?" shortcut opened an overlay while ' + input.field + ' was being typed in' });
  if (after.url !== input.url) findings.push({ rule: 'a11y.shortcuts-in-text-entry', message: 'a shortcut navigated away from ' + input.url + ' while ' + input.field + ' was being typed in' });
  if (input.sceneEditor && after.objects < input.objects) findings.push({ rule: 'a11y.shortcuts-in-text-entry', message: 'Delete removed a scene object while ' + input.field + ' was being typed in' });
  if (field && typeof value === 'string' && !value.includes('?')) findings.push({ rule: 'a11y.shortcuts-in-text-entry', message: 'the "?" typed into ' + input.field + ' did not reach it (something consumed the key)' });
  // Put the field back as it was.
  if (field) {
    if ('value' in field) {
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), 'value')?.set;
      if (setter) setter.call(field, window.__vqaShortcutValue); else field.value = window.__vqaShortcutValue;
      field.dispatchEvent(new Event('input', { bubbles: true }));
    } else field.textContent = window.__vqaShortcutValue;
    field.blur();
  }
  return { findings, evaluated: field ? ['a11y.shortcuts-in-text-entry'] : [] };
}

/**
 * a11y.hover-content (WCAG 1.4.13): the custom tooltips of the page — the
 * product's `.tooltip-anchor` with its `[role="tooltip"]` — each with its
 * trigger's and its own centre, for the harness to drive (cdp.press,
 * cdp.mouseMove). Native `title` is the browser's and is not driven.
 */
export function a11yTooltipTargets() {
  const out = [];
  // With an overlay or inspector open, Escape is its (the overlay exit probe
  // judges it) wherever the trigger is: Search's inspector closes on Escape
  // from the shell's own controls too, and returns focus to the result.
  const escapeHeld = Boolean(document.querySelector('[role="dialog"], [aria-modal="true"], .inspector, .drawer, .workspace__inspector'));
  for (const anchor of Array.from(document.querySelectorAll('.tooltip-anchor'))) {
    const tip = anchor.querySelector('[role="tooltip"]');
    const trigger = anchor.querySelector('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (!tip || !trigger) continue;
    if (trigger.disabled || trigger.getAttribute('aria-disabled') === 'true') continue;
    const v = zoomVisibility(trigger);
    if (v.hidden || v.inert || v.seen.width < 1 || v.seen.height < 1) continue;
    const r = trigger.getBoundingClientRect();
    out.push({
      id: tip.id, description: zoomDescribe(trigger), x: (v.seen.left + v.seen.right) / 2, y: (v.seen.top + v.seen.bottom) / 2,
      box: { x: r.x, y: r.y, width: r.width, height: r.height },
      inOverlay: escapeHeld || Boolean(anchor.closest('[role="dialog"], [aria-modal="true"], .inspector, .drawer')),
    });
  }
  return out;
}
a11yTooltipTargets.helpers = [zoomDescribe, zoomClipChain, zoomVisibleRect, zoomVisibility];

/** The state of one tooltip and the focus, for the harness's polling. */
export function a11yTooltipState(id) {
  const tip = document.getElementById(id);
  if (!tip) return { gone: true };
  const r = tip.getBoundingClientRect();
  const active = document.activeElement;
  return { shown: !tip.hidden && getComputedStyle(tip).display !== 'none' && r.width > 0, box: { x: r.x, y: r.y, width: r.width, height: r.height }, focus: active ? zoomDescribe(active) : null, describes: Boolean(document.querySelector('[aria-describedby~="' + CSS.escape(id) + '"]')) };
}
a11yTooltipState.helpers = [zoomDescribe];

/** Focus a tooltip's trigger (by its tooltip id) from the page, as Tab would land on it. */
/** Where a tooltip's trigger (by its tooltip id) is now: the centre of its visible part, or null. */
export function a11yTooltipPoint(id) {
  const tip = document.getElementById(id);
  const anchor = tip?.closest('.tooltip-anchor');
  const trigger = anchor?.querySelector('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if (!trigger) return null;
  const v = zoomVisibility(trigger);
  if (v.hidden || v.seen.width < 1 || v.seen.height < 1) return null;
  return { x: (v.seen.left + v.seen.right) / 2, y: (v.seen.top + v.seen.bottom) / 2 };
}
a11yTooltipPoint.helpers = [zoomClipChain, zoomVisibleRect, zoomVisibility];

export function a11yTooltipFocus(id) {
  const tip = document.getElementById(id);
  const anchor = tip?.closest('.tooltip-anchor');
  const trigger = anchor?.querySelector('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if (!trigger) return false;
  trigger.focus();
  return document.activeElement === trigger;
}

/** The text-spacing overrides in force (a11y.text-spacing): read from computed style, never assumed. */
export function a11yTextSpacingEnvironment() {
  const body = document.body;
  const s = getComputedStyle(body);
  const fontSize = parseFloat(s.fontSize);
  const problems = [];
  const lineHeight = parseFloat(s.lineHeight) / fontSize;
  const letter = parseFloat(s.letterSpacing) / fontSize;
  const word = parseFloat(s.wordSpacing) / fontSize;
  if (!(lineHeight >= 1.5 - 0.01)) problems.push('line-height is ' + lineHeight.toFixed(2) + '× the font size, not 1.5×');
  if (!(letter >= 0.12 - 0.005)) problems.push('letter-spacing is ' + letter.toFixed(3) + 'em, not 0.12em');
  if (!(word >= 0.16 - 0.005)) problems.push('word-spacing is ' + word.toFixed(3) + 'em, not 0.16em');
  const p = document.querySelector('main p, p');
  let paragraph = null;
  if (p) {
    const ps = getComputedStyle(p);
    paragraph = parseFloat(ps.marginBottom) / parseFloat(ps.fontSize);
    if (!(paragraph >= 2 - 0.01)) problems.push('paragraph spacing is ' + paragraph.toFixed(2) + '× the font size, not 2×');
  }
  return { problems, lineHeight, letterSpacing: letter, wordSpacing: word, paragraphSpacing: paragraph };
}
