/**
 * The automated part of the section 26 visual-QA standard: what a rendered
 * page can settle and a unit test cannot.
 *
 * Every function here runs **in the page**, serialised with `toExpression`;
 * none of them may reference anything outside its own body. Each returns its
 * findings as `{ rule, message }`, where `rule` is a manifest id
 * (`manifest.mjs`), and `evaluated`: the rules it actually had something to
 * check in this capture. The run resolves severity from the manifest and uses
 * `evaluated` to prove no blocking rule went vacuous across the sweep — a
 * rule that never matched anything has not passed, it has not run.
 */

/** A page-side function call, as an expression for Runtime.evaluate. */
export function toExpression(fn, input) {
  return `(${fn.toString()})(${input === undefined ? '' : JSON.stringify(input)})`;
}

/**
 * Page-wide rules: overflow, overlap, tokens, width discipline, the shell, the
 * skip link and landmarks, the one-primary rule, text overflow, aria-pressed,
 * containment depth, state placement, overlays and the tier composition rules.
 *
 * @param {{ tier: string, width: number, fullWidth: boolean|null, archetype: string|null, holds: string|null }} input
 */
export function pageAssertions(input) {
  const findings = [];
  const evaluated = new Set();
  // Surface-scoped rules (manifest `scope: 'surface'`) evaluated inside a
  // region S1 owns, where they block whatever the surface's status.
  const foundationEvaluated = new Set();
  const fail = (rule, message, scope = null) => findings.push(scope ? { rule, message, scope } : { rule, message });
  // The regions S1 built and accepted: the shell, the Context Bar, every
  // Ledger, the Dialog host, the shortcut sheet, the skip link and every
  // StateRegion presentation. A surface-scoped finding inside one is S1's.
  const S1_OWNED = '.sidebar, .context-bar, .workspace--ledger, .dialog-host, .shortcut-sheet, .skip-link, .state-region';
  const scopeOf = (el) => (el.closest(S1_OWNED) ? 'foundation' : null);
  const doc = document.documentElement;
  const round = (n) => Math.round(n * 10) / 10;

  // What of an element is actually on screen: clipped by every scrolling or
  // hidden ancestor and by the viewport. An element scrolled out of its box
  // still reports a rect; comparing those finds collisions nobody can see.
  const clipRect = (el, r) => {
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
  const visibleRect = (el) => clipRect(el, el.getBoundingClientRect());
  // The boxes an element paints into — one per line for wrapped inline text —
  // rather than their union, which would cover its own siblings.
  const visibleRects = (el) => {
    const rects = Array.from(el.getClientRects());
    return (rects.length ? rects : [el.getBoundingClientRect()])
      .map((r) => clipRect(el, r))
      .filter((r) => r.width > 0 && r.height > 0);
  };
  const rectsOverlap = (aRects, bRects, slack) => {
    for (const ra of aRects) {
      for (const rb of bRects) {
        const ox = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
        const oy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
        if (ox > slack && oy > slack) return true;
      }
    }
    return false;
  };
  // A drawer covers what is behind it by design: a pair where exactly one side
  // is inside a positioned overlay is the archetype working (§26).
  const overlayOf = (el) => {
    for (let node = el; node; node = node.parentElement) {
      const position = getComputedStyle(node).position;
      if (position === 'absolute' || position === 'fixed') return node;
    }
    return null;
  };
  const deliberatelyLayered = (a, b) => {
    const oa = overlayOf(a);
    const ob = overlayOf(b);
    if (oa === ob) return false;
    if (oa && !oa.contains(b)) return true;
    if (ob && !ob.contains(a)) return true;
    return false;
  };
  // Whether the browser paints the element at all (a closed disclosure lays
  // out content it never paints).
  const painted = (el) => (
    typeof el.checkVisibility === 'function'
      ? el.checkVisibility({ contentVisibilityAuto: true, opacityProperty: false, visibilityProperty: true })
      : getComputedStyle(el).visibility !== 'hidden'
  );
  const shown = (el) => {
    const r = visibleRect(el);
    return r.width > 0 && r.height > 0 && painted(el);
  };
  const describe = (el) => '<' + el.tagName.toLowerCase() + '> "'
    + ((el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 28)) + '"';

  // 1. No horizontal page scroll.
  evaluated.add('page.horizontal-overflow');
  if (doc.scrollWidth > doc.clientWidth + 1) {
    fail('page.horizontal-overflow', 'horizontal page overflow: scrollWidth ' + doc.scrollWidth + ' > clientWidth ' + doc.clientWidth);
  }

  // 2. Interactive controls must not overlap one another.
  const controls = Array.from(document.querySelectorAll('button, a[href], input, select, textarea')).filter(shown);
  const controlRects = controls.map(visibleRects);
  if (controls.length > 1) evaluated.add('page.control-overlap');
  for (let i = 0; i < controls.length; i++) {
    for (let j = i + 1; j < controls.length; j++) {
      const a = controls[i], b = controls[j];
      if (a.contains(b) || b.contains(a)) continue;
      if (!rectsOverlap(controlRects[i], controlRects[j], 2)) continue;
      if (deliberatelyLayered(a, b)) continue;
      fail('page.control-overlap', 'overlapping controls: ' + describe(a) + ' and ' + describe(b));
    }
  }

  // 2b. Text that collides with other text.
  const LEAVES = 'h1, h2, h3, h4, label, p, span, strong, dt, dd';
  const leaves = Array.from(document.querySelectorAll(LEAVES)).filter((el) => {
    if (el.querySelector(LEAVES)) return false;
    if (!(el.textContent || '').trim()) return false;
    return shown(el);
  });
  const leafRects = leaves.map(visibleRects);
  if (leaves.length > 1) evaluated.add('page.text-overlap');
  for (let i = 0; i < leaves.length; i++) {
    for (let j = i + 1; j < leaves.length; j++) {
      const a = leaves[i], b = leaves[j];
      if (a.contains(b) || b.contains(a)) continue;
      if (!rectsOverlap(leafRects[i], leafRects[j], 4)) continue;
      if (deliberatelyLayered(a, b)) continue;
      fail('page.text-overlap', 'overlapping text: "' + (a.textContent || '').trim().slice(0, 28)
        + '" and "' + (b.textContent || '').trim().slice(0, 28) + '"');
    }
  }

  // 3. Every custom property a stylesheet asks for resolves.
  const root = getComputedStyle(doc);
  const referenced = new Set();
  for (const sheet of Array.from(document.styleSheets)) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; }
    for (const rule of Array.from(rules || [])) {
      for (const m of (rule.cssText || '').matchAll(/var\(\s*(--[a-z0-9-]+)/g)) referenced.add(m[1]);
    }
  }
  if (referenced.size) evaluated.add('page.token-resolution');
  for (const name of referenced) {
    if (root.getPropertyValue(name).trim() === '') fail('page.token-resolution', 'unresolved custom property: ' + name);
  }

  // 4. Width discipline at the ultra-wide anchors (§25, §4.1).
  const page = document.querySelector('.page');
  const pageWidth = page ? Math.round(page.getBoundingClientRect().width) : null;
  const declaresFullWidth = page ? page.classList.contains('page--full') : null;
  if (input.width >= 2400 && pageWidth !== null && input.fullWidth !== null) {
    evaluated.add('page.width-discipline');
    if (input.fullWidth && pageWidth < input.width - 400) {
      fail('page.width-discipline', 'declares full width but rendered ' + pageWidth + 'px inside a ' + input.width + 'px viewport');
    }
    if (!input.fullWidth && pageWidth > 1700) {
      fail('page.width-discipline', 'is not a full-width surface but rendered ' + pageWidth + 'px');
    }
    if (declaresFullWidth !== input.fullWidth) {
      fail('page.width-discipline', 'expected page--full=' + input.fullWidth + ', found ' + declaresFullWidth);
    }
  }

  // 5. The shell (§5, S1d).
  const shell = {};
  evaluated.add('shell.context-bar');
  const bars = document.querySelectorAll('.context-bar');
  if (bars.length !== 1) fail('shell.context-bar', 'expected exactly one Context Bar, found ' + bars.length);
  if (bars[0]) {
    shell.contextBarHeight = round(bars[0].getBoundingClientRect().height);
    if (Math.abs(shell.contextBarHeight - 44) > 0.5) fail('shell.context-bar', 'Context Bar is ' + shell.contextBarHeight + 'px tall, not 44px');
  }
  const rail = document.querySelector('.sidebar');
  const toggle = rail && rail.querySelector('.sidebar__toggle');
  if (rail) {
    shell.railWidth = Math.round(rail.getBoundingClientRect().width);
    shell.railCollapsed = Boolean(document.querySelector('.shell--collapsed'));
  }
  if (rail && input.tier !== 'C') {
    evaluated.add('shell.rail');
    const expected = shell.railCollapsed ? 56 : 216;
    if (shell.railWidth !== expected) fail('shell.rail', 'rail is ' + shell.railWidth + 'px, not ' + expected + 'px');
    if (!toggle) fail('shell.rail', 'rail has no collapse control');
    else {
      const box = toggle.getBoundingClientRect();
      shell.collapseControl = [Math.round(box.width), Math.round(box.height)];
      if (Math.round(box.height) !== 32) fail('shell.rail', 'rail collapse control is ' + Math.round(box.height) + 'px tall, not 32px');
      if (shell.railCollapsed && Math.round(box.width) !== 32) fail('shell.rail', 'collapsed rail control is ' + Math.round(box.width) + 'px wide, not 32px');
      if (!toggle.hasAttribute('aria-expanded')) fail('shell.rail', 'rail collapse control does not announce its state');
    }
  }

  // 6. Modal overlays. An open Dialog or overlay drawer makes everything else
  //    inert by design (§15, §20), which the skip-link rule must respect.
  const modals = Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).filter(shown);
  const focusable = (el) => el.matches('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])')
    && !el.disabled && !el.closest('[inert]') && shown(el);
  const allFocusable = Array.from(document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]'))
    .filter((el) => el.getAttribute('tabindex') !== '-1' && !el.closest('[inert]') && !el.disabled);
  const nameOf = (el) => {
    const label = el.getAttribute('aria-label');
    if (label && label.trim()) return label.trim();
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    return ids.map((id) => (document.getElementById(id)?.textContent || '').trim()).join(' ').trim();
  };
  for (const modal of modals) {
    const rule = modal.classList.contains('dialog') ? 'overlay.dialog' : 'overlay.drawer';
    evaluated.add(rule);
    const what = rule === 'overlay.dialog' ? 'Dialog' : 'overlay drawer';
    if (!nameOf(modal)) fail(rule, 'the open ' + what + ' has no accessible name');
    if (!modal.contains(document.activeElement)) {
      fail(rule, 'focus is outside the open ' + what + ' (on ' + (document.activeElement ? describe(document.activeElement) : 'nothing') + ')');
    }
    // A Dialog makes every other part of the page inert (§15, S1c). A drawer
    // makes inert the content it covers (§20): what lies under its scrim, or,
    // without one, under the drawer's own positioned container.
    let covers = () => true;
    if (rule === 'overlay.drawer') {
      const scrim = Array.from(document.querySelectorAll('.drawer-scrim')).find(shown);
      const area = (scrim || modal.offsetParent || document.body).getBoundingClientRect();
      covers = (el) => {
        const r = el.getBoundingClientRect();
        const x = r.left + r.width / 2;
        const y = r.top + r.height / 2;
        return x >= area.left && x <= area.right && y >= area.top && y <= area.bottom;
      };
    }
    const escapes = Array.from(document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'))
      .filter((el) => !modal.contains(el) && focusable(el) && covers(el));
    if (escapes.length) {
      fail(rule, escapes.length + ' focusable control(s) ' + (rule === 'overlay.drawer' ? 'covered by' : 'outside')
        + ' the open ' + what + ' are not inert: ' + escapes.slice(0, 3).map(describe).join(', '));
    }
  }
  shell.modals = modals.length;

  // 7. Skip link and landmarks (§5, §23).
  shell.firstFocusable = allFocusable[0] ? (allFocusable[0].className || allFocusable[0].tagName) : null;
  if (!modals.length) {
    evaluated.add('a11y.skip-link');
    const skip = allFocusable[0];
    if (!skip || !skip.classList.contains('skip-link')) {
      fail('a11y.skip-link', 'the skip link is not the first focusable element (first is ' + shell.firstFocusable + ')');
    } else {
      const target = (skip.getAttribute('href') || '').startsWith('#')
        ? document.getElementById(skip.getAttribute('href').slice(1)) : null;
      if (!target) fail('a11y.skip-link', 'the skip link target ' + skip.getAttribute('href') + ' does not exist');
      else {
        if (!target.matches('main, [role="main"]')) fail('a11y.skip-link', 'the skip link targets ' + describe(target) + ', not the main landmark');
        if (target.getAttribute('tabindex') !== '-1') fail('a11y.skip-link', 'the skip link target cannot take focus (no tabindex=-1)');
      }
    }
  }
  evaluated.add('a11y.landmarks');
  const mains = document.querySelectorAll('main, [role="main"]').length;
  const banners = Array.from(document.querySelectorAll('header, [role="banner"]'))
    .filter((el) => el.getAttribute('role') === 'banner' || !el.closest('article, aside, main, nav, section')).length;
  shell.mains = mains;
  shell.banners = banners;
  if (mains !== 1) fail('a11y.landmarks', 'expected one main landmark, found ' + mains);
  if (banners !== 1) fail('a11y.landmarks', 'expected one banner landmark, found ' + banners);
  const primaryNav = Array.from(document.querySelectorAll('nav')).find((nav) => (nav.getAttribute('aria-label') || '') === 'Primary');
  if (!primaryNav) fail('a11y.landmarks', 'no navigation landmark named Primary');

  // 8. At most one accent-filled action on the surface (§8.1), judged by what
  //    is painted rather than by a class name: the accent fills are resolved
  //    from the tokens and compared with each control's computed background. A
  //    control that reports a state rather than offering an action — pressed,
  //    selected, current — is a state indicator, not a primary.
  const resolveColor = (value) => {
    const probe = document.createElement('span');
    probe.style.backgroundColor = value;
    probe.style.display = 'none';
    document.body.appendChild(probe);
    const color = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return color;
  };
  const accentFills = new Set(['--accent-strong', '--accent-hover']
    .map((token) => root.getPropertyValue(token).trim()).filter(Boolean).map(resolveColor));
  // Every action on the surface counts, scrolled into view or not: a second
  // primary below the fold of a page-scrolling Record is still a second
  // primary. Rendered (laid out, painted, not hidden) is the test, not "on
  // screen". The paint check is crossed with the shared class, so a primary
  // whose token changed is still counted and an accent painted onto another
  // control is caught too.
  // Positioned outside the document altogether — the skip link parked above
  // the page until it is focused — is not on offer; anywhere the operator can
  // scroll to is.
  const rendered = (el) => {
    const r = el.getBoundingClientRect();
    const reachable = r.right > -window.scrollX && r.bottom > -window.scrollY;
    return r.width > 0 && r.height > 0 && reachable && painted(el) && !el.closest('[hidden]');
  };
  const actions = Array.from(document.querySelectorAll('button, a[href], [role="button"], input[type="submit"]'))
    .filter((el) => rendered(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true' && !el.closest('[inert]'))
    .filter((el) => !el.hasAttribute('aria-pressed') && !el.hasAttribute('aria-selected')
      && !el.hasAttribute('aria-current') && !el.hasAttribute('aria-checked'));
  if (actions.length) evaluated.add('surface.one-primary');
  const primaries = actions.filter((el) => accentFills.has(getComputedStyle(el).backgroundColor) || el.classList.contains('btn--primary'));
  shell.visiblePrimaries = primaries.map((el) => (el.textContent || el.getAttribute('aria-label') || '').trim());
  if (primaries.length > 1) {
    fail('surface.one-primary', primaries.length + ' accent-filled actions are visible at once: ' + shell.visiblePrimaries.join(', '));
  }
  shell.title = document.title;

  // 9. Text outside its box (§36.2, §16). A text-bearing block whose content
  //    is wider than its box either spills (overflow visible) or is cut with no
  //    ellipsis; a box that clips with an ellipsis is the sanctioned
  //    truncation, a box that scrolls is a scroll region, and visually-hidden
  //    text, SVG and form fields are not checked.
  const textBlocks = Array.from(document.querySelectorAll('body *')).filter((el) => {
    if (el.closest('svg, canvas, video, .visually-hidden, [aria-hidden="true"]')) return false;
    if (el.matches('input, select, textarea, option, script, style, br')) return false;
    if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim())) return false;
    const style = getComputedStyle(el);
    if (style.display === 'inline' || style.display === 'contents' || style.display === 'none') return false;
    return el.clientWidth > 0 && shown(el);
  });
  // Blocking in an S1 region; on a surface, as the manifest says for it.
  for (const el of textBlocks) (scopeOf(el) ? foundationEvaluated : evaluated).add('text.overflow');
  for (const el of textBlocks) {
    const style = getComputedStyle(el);
    // Across: a single line wider than its box.
    if (el.scrollWidth > el.clientWidth + 1 && !/(auto|scroll)/.test(style.overflowX)) {
      const clipped = style.overflowX !== 'visible';
      if (!(clipped && style.textOverflow === 'ellipsis')) {
        fail('text.overflow', (clipped ? 'text is cut off without an ellipsis in ' : 'text spills out of ') + describe(el)
          + ' (' + el.scrollWidth + 'px of text in a ' + el.clientWidth + 'px box)', scopeOf(el));
        continue;
      }
    }
    // Down: text that wrapped past a box of fixed height — a control or row
    // that took a second line under a wider font. A line clamp (its ellipsis
    // is the sanctioned truncation) and a scroll region are not overflow.
    if (el.scrollHeight > el.clientHeight + 2 && !/(auto|scroll)/.test(style.overflowY)) {
      const clamped = style.webkitLineClamp && style.webkitLineClamp !== 'none';
      if (clamped) continue;
      const clipped = style.overflowY !== 'visible';
      fail('text.overflow', (clipped ? 'text is cut off below in ' : 'text spills below ') + describe(el)
        + ' (' + el.scrollHeight + 'px of text in a ' + el.clientHeight + 'px box)', scopeOf(el));
    }
  }

  // 10. aria-pressed has a visible pressed treatment (§12). The proof is the
  //     control itself rendered in its other state and compared with how it
  //     looks now — its own, its descendants', its pseudo-elements' and its
  //     row's computed appearance — never a class name, an attribute or a
  //     peer's unrelated difference taken on trust.
  //
  //     The other state is the attribute flipped together with the classes the
  //     product pairs with it, read from evidence on the page: the nearest
  //     control of the same kind in the other state — in its group, else
  //     anywhere on the page — and the classes that differ between the two (the
  //     one with the fewest differences, so an unrelated class such as an
  //     "active revision" is not taken for the pressed one). With no such
  //     control, a pressed one loses its `is-` classes; an unpressed one gets
  //     the attribute alone. Identical readings are a finding — except for an
  //     unpressed control whose stylesheet does define `is-` states for it but
  //     whose pressed form the page never shows: that is unproven here, not
  //     passed, and a full sweep requires every such kind proven somewhere.
  //     Transitions are held off, and every attribute, class and style is put
  //     back exactly before anything paints.
  const SIGNATURE = ['backgroundColor', 'backgroundImage', 'borderTopColor', 'borderRightColor', 'borderBottomColor', 'borderLeftColor',
    'borderTopWidth', 'borderTopStyle', 'borderRadius', 'color', 'boxShadow', 'outlineStyle', 'outlineColor', 'opacity',
    'visibility', 'display', 'fill', 'stroke', 'textDecorationLine', 'fontWeight', 'transform', 'content'];
  // Where a selection may be painted besides the control: its list row, or
  // the element that wraps it.
  const rowOf = (el) => el.closest('li, [role="listitem"], [role="row"]') || el.parentElement;
  const looks = (el) => {
    const row = rowOf(el);
    const nodes = [el, ...el.querySelectorAll('*'), ...(row && row !== el ? [row] : [])];
    return nodes.map((node) => [null, '::before', '::after'].map((pseudo) => {
      const s = getComputedStyle(node, pseudo);
      return SIGNATURE.map((prop) => s[prop]).join('|');
    }).join('/')).join('#');
  };
  const classes = (node) => (node ? Array.from(node.classList) : []);
  const diff = (a, b) => a.filter((name) => !b.includes(name));
  const base = (node) => classes(node).filter((name) => !/^is-/.test(name)).sort().join('.');
  // A control's kind: what it is apart from its state.
  const kindOf = (el) => el.tagName.toLowerCase() + (base(el) ? '.' + base(el) : '') + ' in ' + (rowOf(el) ? rowOf(el).tagName.toLowerCase() + (base(rowOf(el)) ? '.' + base(rowOf(el)) : '') : '-');
  // Every `is-` class some style rule pairs with one of `node`'s own classes.
  const definedStates = (() => {
    const pairs = [];
    for (const sheet of Array.from(document.styleSheets)) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; }
      const walk = (list) => {
        for (const rule of Array.from(list || [])) {
          if (rule.cssRules && !rule.selectorText) { walk(rule.cssRules); continue; }
          for (const compound of String(rule.selectorText || '').split(/[\s>+~,()]+/)) {
            const names = (compound.match(/\.[A-Za-z0-9_-]+/g) || []).map((c) => c.slice(1));
            if (names.length > 1) pairs.push(names);
          }
        }
      };
      walk(rules);
    }
    return (node) => {
      if (!node) return [];
      const own = classes(node);
      const found = new Set();
      for (const names of pairs) {
        if (!names.some((name) => own.includes(name))) continue;
        for (const name of names) if (/^is-/.test(name) && !own.includes(name)) found.add(name);
      }
      return Array.from(found);
    };
  })();
  const pressables = Array.from(document.querySelectorAll('[aria-pressed]'))
    .filter((el) => shown(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true'
      && /^(true|false)$/.test(el.getAttribute('aria-pressed') || ''));
  if (pressables.length) evaluated.add('pressed.visible');
  const otherStates = (el) => {
    const state = el.getAttribute('aria-pressed');
    const row = rowOf(el);
    const kind = kindOf(el);
    const group = el.closest('[role="group"], [role="toolbar"], ul, ol, [role="list"]') || el.parentElement;
    const other = (scope) => Array.from(scope.querySelectorAll('[aria-pressed]')).filter((candidate) => candidate !== el
      && candidate.tagName === el.tagName && candidate.getAttribute('aria-pressed') !== state && shown(candidate));
    let peers = other(group);
    let source = 'peer';
    if (!peers.length) { peers = other(document).filter((candidate) => kindOf(candidate) === kind); source = 'page'; }
    if (peers.length) {
      const changes = peers.map((peer) => {
        const peerRow = rowOf(peer);
        return {
          el: { remove: diff(classes(el), classes(peer)), add: diff(classes(peer), classes(el)) },
          row: row && peerRow && row !== peerRow ? { remove: diff(classes(row), classes(peerRow)), add: diff(classes(peerRow), classes(row)) } : { remove: [], add: [] },
        };
      });
      const size = (c) => c.el.remove.length + c.el.add.length + c.row.remove.length + c.row.add.length;
      changes.sort((a, b) => size(a) - size(b));
      return { source, variants: [changes[0]] };
    }
    const none = { remove: [], add: [] };
    if (state === 'true') {
      return { source: 'self', variants: [{ el: { remove: classes(el).filter((c) => /^is-/.test(c)), add: [] }, row: { remove: classes(row).filter((c) => /^is-/.test(c)), add: [] } }] };
    }
    return { source: 'self', variants: [{ el: none, row: none }] };
  };
  const pressed = { proven: new Set(), unproven: [] };
  for (const el of pressables) {
    const row = rowOf(el);
    const touched = [el, ...el.querySelectorAll('*'), ...(row && row !== el ? [row] : [])];
    const savedStyle = touched.map((node) => node.getAttribute('style'));
    const savedClass = [el, row].map((node) => (node ? node.getAttribute('class') : null));
    const state = el.getAttribute('aria-pressed');
    touched.forEach((node) => { node.style.transition = 'none'; });
    const before = looks(el);
    const { source, variants } = otherStates(el);
    let distinct = false;
    for (const variant of variants) {
      el.setAttribute('aria-pressed', state === 'true' ? 'false' : 'true');
      variant.el.remove.forEach((name) => el.classList.remove(name));
      variant.el.add.forEach((name) => el.classList.add(name));
      if (row) { variant.row.remove.forEach((name) => row.classList.remove(name)); variant.row.add.forEach((name) => row.classList.add(name)); }
      const after = looks(el);
      el.setAttribute('aria-pressed', state);
      [el, row].forEach((node, index) => {
        if (!node) return;
        if (savedClass[index] === null) node.removeAttribute('class'); else node.setAttribute('class', savedClass[index]);
      });
      if (after !== before) { distinct = true; break; }
    }
    // Flush the restored appearance while transitions are still held, then put
    // every style attribute back exactly as it was found. Reading the attribute
    // first makes Chromium serialise the inline style it updates lazily, or
    // removing it would leave an empty `style=""` behind.
    looks(el);
    touched.forEach((node, index) => {
      node.getAttribute('style');
      if (savedStyle[index] === null) node.removeAttribute('style'); else node.setAttribute('style', savedStyle[index]);
    });
    const kind = kindOf(el);
    if (distinct) { pressed.proven.add(kind); continue; }
    if (source === 'self' && state === 'false' && (definedStates(el).length || definedStates(row).length)) {
      pressed.unproven.push({ kind, control: describe(el) });
      continue;
    }
    fail('pressed.visible', describe(el) + (source === 'self'
      ? ' looks the same pressed and unpressed (attribute flipped' + (state === 'true' ? ', its state classes removed' : '') + ')'
      : ' looks the same pressed and unpressed (its other state rendered as ' + (source === 'peer' ? 'the nearest peer' : 'the nearest control of its kind') + ' shows it)'));
  }

  // 11. Containment depth (§11): one contained surface, never a bordered panel
  //     inside a bordered panel. A frame is a block bordered on all four sides,
  //     large enough to contain something; alerts, controls, badges, media and
  //     placeholders are messages and objects, not containers.
  // A frame round nothing but media — an image, a video, a canvas, an
  // evidence placeholder — is that object's edge, not a containment level.
  // Not an icon (an svg) and not a frame that also holds text of its own.
  const MEDIA = 'img, picture, video, canvas, .evidence-placeholder';
  const mediaFrame = (el) => el.children.length > 0 && Array.from(el.children).every((child) => child.matches(MEDIA))
    && !Array.from(el.childNodes).some((node) => node.nodeType === 3 && node.textContent.trim());
  const framed = (el) => {
    // A control's own frame is not a containment level: `.file-input` is the
    // shared FileInput (§27) drawn like every other input, and a long file
    // name wraps inside it (the one statement of what is imported) until it is
    // as tall as a container — a control still (M3).
    if (el.matches('button, a, input, select, textarea, .file-input, img, video, canvas, svg, kbd, code, [role="alert"], [role="status"], .alert, .badge, .chip, .evidence-placeholder, .tooltip, .skip-link')) return false;
    if (mediaFrame(el)) return false;
    const s = getComputedStyle(el);
    if (s.display === 'inline') return false;
    const sides = ['Top', 'Right', 'Bottom', 'Left'];
    if (!sides.every((side) => parseFloat(s['border' + side + 'Width']) >= 1 && !/rgba\(.*,\s*0\)$/.test(s['border' + side + 'Color'])
      && s['border' + side + 'Style'] !== 'none')) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 120 && r.height >= 48 && painted(el);
  };
  // The workspace, and the overlays S1 owns wherever they are mounted.
  const frames = Array.from(new Set(document.querySelectorAll('main *, .dialog-host *, .shortcut-sheet *'))).filter(framed);
  for (const el of frames) (scopeOf(el) ? foundationEvaluated : evaluated).add('containment.depth');
  const nestedFrames = frames.filter((el) => frames.some((outer) => outer !== el && outer.contains(el)));
  const outerOf = (el) => frames.find((candidate) => candidate !== el && candidate.contains(el));
  // A nesting is S1's when the frame doing the containing is in an S1 region:
  // a surface's panel round an S1 presentation is the surface's choice.
  // Reported per scope, the first five of each in full.
  for (const scope of ['foundation', null]) {
    const nested = nestedFrames.filter((el) => scopeOf(outerOf(el)) === scope);
    for (const el of nested.slice(0, 5)) {
      const outer = outerOf(el);
      fail('containment.depth', 'a bordered container (' + (el.className || el.tagName) + ') sits inside another ('
        + (outer.className || outer.tagName) + ')', scope);
    }
    if (nested.length > 5) fail('containment.depth', (nested.length - 5) + ' more nested containers', scope);
  }

  // 12. State placement (§37.1, §14.1). A state presentation is content-sized
  //     — it never pads itself to fill the region it replaces — and the first
  //     thing in its region sits at that region's top.
  // A box that paints — a fill, a border, a hatching — stretched beyond its
  // content is the viewport-high presentation §37.1 forbids; a transparent
  // container a layout stretched paints nothing and is not one.
  const paintsBox = (el) => {
    const s = getComputedStyle(el);
    return s.backgroundImage !== 'none' || !/rgba\(.*,\s*0\)$|transparent/.test(s.backgroundColor)
      || ['Top', 'Right', 'Bottom', 'Left'].some((side) => parseFloat(s['border' + side + 'Width']) >= 1 && s['border' + side + 'Style'] !== 'none');
  };
  // The box's own content, plus its own bottom padding and border: those are
  // its geometry, not stretch.
  const contentHeight = (el) => {
    const kids = Array.from(el.children).filter((child) => {
      const cs = getComputedStyle(child);
      return cs.position !== 'absolute' && cs.display !== 'none' && cs.display !== 'contents';
    });
    if (!kids.length) return null;
    const s = getComputedStyle(el);
    return Math.max(...kids.map((child) => child.getBoundingClientRect().bottom)) - el.getBoundingClientRect().top
      + parseFloat(s.paddingBottom) + parseFloat(s.borderBottomWidth);
  };
  for (const region of Array.from(document.querySelectorAll('.state-region')).filter(shown)) {
    evaluated.add('state.placement');
    const box = region.getBoundingClientRect();
    for (const el of [region, ...region.children].filter(paintsBox)) {
      const used = contentHeight(el);
      const height = el.getBoundingClientRect().height;
      if (used !== null && height > used + 24) {
        fail('state.placement', 'a ' + (region.className.match(/state-region--[a-z]+/) || ['state'])[0]
          + ' presentation paints a ' + round(height) + 'px box around ' + round(used) + 'px of content: it fills its region');
        break;
      }
    }
    // Where the region it replaces begins: directly after the in-flow content
    // above it (with the layout's own gap and margins), or at the parent's
    // content top when nothing precedes it or what precedes it sits beside it.
    const parent = region.parentElement;
    if (parent) {
      const ps = getComputedStyle(parent);
      const rs = getComputedStyle(region);
      const inFlow = (el) => {
        const cs = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return cs.position !== 'absolute' && cs.position !== 'fixed' && cs.display !== 'none' && cs.display !== 'contents' && r.height > 1;
      };
      let prev = region.previousElementSibling;
      while (prev && !inFlow(prev)) prev = prev.previousElementSibling;
      const above = prev && prev.getBoundingClientRect().bottom <= box.top + 1 ? prev : null;
      let start;
      let where;
      if (above) {
        const qs = getComputedStyle(above);
        const laidOut = /flex|grid/.test(ps.display);
        const gap = laidOut ? (parseFloat(ps.rowGap) || 0) : 0;
        const margins = laidOut
          ? Math.max(0, parseFloat(qs.marginBottom)) + Math.max(0, parseFloat(rs.marginTop))
          : Math.max(0, parseFloat(qs.marginBottom), parseFloat(rs.marginTop));
        start = above.getBoundingClientRect().bottom + gap + margins;
        where = 'the content above it';
      } else {
        start = parent.getBoundingClientRect().top + parseFloat(ps.borderTopWidth) + parseFloat(ps.paddingTop);
        where = 'the top of the region it replaces';
      }
      if (box.top - start > 1.5) {
        fail('state.placement', 'a state presentation starts ' + round(box.top - start) + 'px below ' + where);
      }
      // ...and the presentation itself starts at the top of its own region:
      // a stretched transparent region must not centre it.
      let first = region.firstElementChild;
      while (first && !inFlow(first)) first = first.nextElementSibling;
      if (first) {
        const inner = box.top + parseFloat(rs.borderTopWidth) + parseFloat(rs.paddingTop) + Math.max(0, parseFloat(getComputedStyle(first).marginTop));
        const offset = first.getBoundingClientRect().top - inner;
        if (offset > 1.5) fail('state.placement', 'a state presentation sits ' + round(offset) + 'px below the top of its own region');
      }
    }
  }

  // 13. Tier composition rules (§25), evaluated at their own tier only; every
  //     one is measured/pending until S5 implements the compositions.
  if (input.tier === 'B') {
    evaluated.add('tier.b-shell');
    // §25 Tier B: collapsed by default, expandable as an overlay. Measured as
    // what it means for the operator: the rail never takes width from the
    // workspace — the workspace starts at the collapsed rail's edge — and a
    // rail drawn expanded is the open overlay, a modal dialog, never a column.
    const main = document.querySelector('main');
    if (main) {
      shell.workspaceLeft = Math.round(main.getBoundingClientRect().left);
      if (shell.workspaceLeft > 57) {
        fail('tier.b-shell', 'the rail takes ' + shell.workspaceLeft + 'px of width beside the workspace at Tier B; §25 collapses it by default and opens it as an overlay');
      }
    }
    if (rail && shell.railWidth > 56 && !(rail.getAttribute('role') === 'dialog' && rail.getAttribute('aria-modal') === 'true')) {
      fail('tier.b-shell', 'the rail is drawn expanded (' + shell.railWidth + 'px) without being the modal overlay §25 makes it at Tier B');
    }
    if (!toggle || !shown(toggle)) fail('tier.b-shell', 'the rail collapse control is not visible at Tier B');
    else if (!(toggle.getAttribute('aria-label') || toggle.textContent || '').trim()) fail('tier.b-shell', 'the rail collapse control is unlabelled');
    // §25 Tier B: "Context Bar 44px; its primary action keeps its label" — and
    // every action of the bar is inside it, none pushed off the edge.
    const bar = document.querySelector('.context-bar');
    if (bar) {
      const barBox = bar.getBoundingClientRect();
      // Rendered, not merely in view: an action pushed wholly off the page is
      // exactly the one this is for (a viewport-clipped "shown" missed it).
      const rendered = (el) => getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0;
      for (const action of Array.from(bar.querySelectorAll('.context-bar__actions button, .context-bar__actions a')).filter(rendered)) {
        const box = action.getBoundingClientRect();
        if (box.left < barBox.left - 0.5 || box.right > Math.min(barBox.right, doc.clientWidth) + 0.5) {
          fail('tier.b-shell', 'the Context Bar action ' + describe(action) + ' extends past the bar (' + Math.round(box.right) + ' > ' + Math.round(Math.min(barBox.right, doc.clientWidth)) + ')');
        }
        if (action.matches('.btn--primary')) {
          const label = Array.from(action.childNodes).some((node) => (node.nodeType === 3 && node.textContent.trim())
            || (node.nodeType === 1 && !node.matches('svg, .icon, .visually-hidden') && node.textContent.trim() && getComputedStyle(node).display !== 'none'));
          if (!label) fail('tier.b-shell', 'the Context Bar primary action ' + describe(action) + ' has lost its visible label at Tier B');
        }
      }
    }
  }
  if (input.tier === 'C') {
    evaluated.add('tier.c-shell');
    // §25 Tier C Shell row: "Rail is a top-of-page menu control opening an
    // overlay". The workspace has the viewport — no rail column beside it.
    const main = document.querySelector('main');
    if (main && main.getBoundingClientRect().width < doc.clientWidth - 1) {
      fail('tier.c-shell', 'the content is ' + Math.round(main.getBoundingClientRect().width) + 'px beside a '
        + (rail ? shell.railWidth : 0) + 'px rail column in a ' + doc.clientWidth + 'px viewport; §25 makes the rail a top-of-page menu');
    }
    const railModal = rail && rail.getAttribute('role') === 'dialog' && rail.getAttribute('aria-modal') === 'true';
    if (rail && shown(rail) && !railModal) {
      fail('tier.c-shell', 'the rail is drawn (' + shell.railWidth + 'px) without being the navigation overlay; at Tier C it exists only as the overlay the menu opens');
    }
    // The control: visible, named, announcing the navigation it controls, at
    // the top of the page — found by what it controls, not by its class.
    const nav = document.querySelector('nav[aria-label="Primary"]');
    const controls = nav && nav.id ? Array.from(document.querySelectorAll('[aria-controls]')).filter((el) => el.getAttribute('aria-controls') === nav.id) : [];
    const menu = controls.find((el) => shown(el) && !(rail && rail.contains(el)));
    shell.menuControl = menu ? describe(menu) : null;
    if (!railModal) {
      if (!menu) fail('tier.c-shell', 'no visible control opens the navigation at Tier C (§25: a top-of-page menu control)');
      else {
        const box = menu.getBoundingClientRect();
        if (!(menu.getAttribute('aria-label') || menu.textContent || '').trim()) fail('tier.c-shell', 'the navigation menu control is unnamed');
        if (!menu.hasAttribute('aria-expanded')) fail('tier.c-shell', 'the navigation menu control does not announce whether the navigation is open');
        if (box.top > 44) fail('tier.c-shell', 'the navigation menu control is ' + Math.round(box.top) + 'px down the page, not at its top');
        if (box.width < 31.5 || box.height < 31.5) fail('tier.c-shell', 'the navigation menu control is ' + Math.round(box.width) + 'x' + Math.round(box.height) + ', under the 32px rail control metric (§5)');
      }
    } else if (rail.getBoundingClientRect().right > doc.clientWidth + 0.5) {
      fail('tier.c-shell', 'the navigation overlay is wider than the viewport');
    }
    // The Context Bar at Tier C: one truncated identity line, every action in
    // the bar, the primary with its icon and label (§25 Tier C Shell row).
    const bar = document.querySelector('.context-bar');
    if (bar) {
      const barBox = bar.getBoundingClientRect();
      const crumbs = Array.from(bar.querySelectorAll('.context-bar__crumbs li')).filter(shown);
      if (bar.querySelector('.context-bar__crumbs') && !crumbs.some((li) => li.getBoundingClientRect().width >= 24)) {
        fail('tier.c-shell', 'the Context Bar shows no readable identity: every crumb is under 24px');
      }
      // A crumb that returns somewhere specific — a link carrying state
      // (Review's Search, back to the Investigation it came from) — is the
      // way back, and the menu offers only a fresh one: it stays drawn.
      for (const link of Array.from(bar.querySelectorAll('.context-bar__crumbs a[href*="?"]'))) {
        if (!shown(link)) fail('tier.c-shell', 'the Context Bar way back (' + link.textContent.trim() + ', to ' + link.getAttribute('href').slice(0, 40) + ') is not drawn at Tier C');
      }
      // §24: the zone a surface states is stated, visibly — it may truncate,
      // never be only a name for assistive technology or a tooltip.
      for (const zone of Array.from(bar.querySelectorAll('.zone-note code'))) {
        const r = zone.getBoundingClientRect();
        if (r.width < 24 || zone.closest('.visually-hidden') || zone.matches('.visually-hidden')) {
          fail('tier.c-shell', 'the Context Bar states its time zone only invisibly (' + Math.round(r.width) + 'px drawn); §24 states it in the bar');
        }
      }
      for (const item of Array.from(bar.querySelectorAll('.context-bar__crumbs li, .context-bar__status > *')).filter(shown)) {
        const box = item.getBoundingClientRect();
        if (box.right > Math.min(barBox.right, doc.clientWidth) + 0.5) fail('tier.c-shell', 'the Context Bar item ' + describe(item) + ' extends past the bar');
      }
      const rendered = (el) => getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0;
      for (const item of Array.from(bar.querySelectorAll('.context-bar__crumbs li, .context-bar__status > *')).filter(rendered)) {
        if (item.getBoundingClientRect().left > doc.clientWidth - 0.5) fail('tier.c-shell', 'the Context Bar item ' + describe(item) + ' is pushed off the page');
      }
      for (const action of Array.from(bar.querySelectorAll('.context-bar__actions button, .context-bar__actions a, .context-bar__actions input')).filter(rendered)) {
        const box = action.getBoundingClientRect();
        if (box.left < barBox.left - 0.5 || box.right > Math.min(barBox.right, doc.clientWidth) + 0.5) {
          fail('tier.c-shell', 'the Context Bar action ' + describe(action) + ' extends past the bar (' + Math.round(box.right) + ' > ' + Math.round(Math.min(barBox.right, doc.clientWidth)) + ')');
        }
        if (action.matches('.btn--primary')) {
          const label = Array.from(action.childNodes).some((node) => (node.nodeType === 3 && node.textContent.trim())
            || (node.nodeType === 1 && !node.matches('svg, .icon, .visually-hidden') && node.textContent.trim() && getComputedStyle(node).display !== 'none'));
          if (!label) fail('tier.c-shell', 'the Context Bar primary action ' + describe(action) + ' has lost its visible label at Tier C');
        } else if (!(action.getAttribute('aria-label') || action.textContent || '').trim()) {
          fail('tier.c-shell', 'the Context Bar action ' + describe(action) + ' is unnamed');
        }
      }
    }
    if (input.archetype === 'workbench') {
      evaluated.add('tier.c-workbench-unsupported');
      // §25 Tier C Workbench: the Context Bar, a read-only summary and one
      // statement that the operation needs at least 768px — and no editing
      // canvas, no stage or inspector, no mode strip, in the page at all.
      const canvas = document.querySelector('.workspace__stage canvas, .workspace__stage svg, [data-testid="scene-canvas"]');
      if (canvas && shown(canvas)) fail('tier.c-workbench-unsupported', 'the editing canvas renders at Tier C; §25 requires the unsupported-state statement instead');
      const regions = Array.from(document.querySelectorAll('.workspace__stage, .workspace__inspector, .workspace__band'));
      if (regions.length) fail('tier.c-workbench-unsupported', 'the Workbench still renders ' + regions.map((el) => el.className.split(' ')[0]).join(', ') + ' at Tier C');
      // A read-only summary offers no form control: an editing or analytical
      // control left in the unsupported state is a question nobody can ask.
      const workbench = document.querySelector('.workspace--workbench');
      const controls = workbench ? Array.from(workbench.querySelectorAll('input, select, textarea')).filter(shown) : [];
      if (controls.length) fail('tier.c-workbench-unsupported', 'the unsupported Workbench still offers ' + controls.length + ' form control(s): ' + controls.slice(0, 3).map(describe).join(', '));
      const page = document.querySelector('main');
      const unsupported = page && page.querySelector('.workspace__unsupported');
      if (!/at least 768px/.test(page ? page.innerText : '')) fail('tier.c-workbench-unsupported', 'no statement that the operation needs a display of at least 768px');
      // A Workbench whose camera or scene could not be read says so in its
      // page state instead (§37.1), which is not an unsupported state.
      if (!unsupported && !page.querySelector('.state-region')) fail('tier.c-workbench-unsupported', 'no read-only summary beside the statement');
      else if (unsupported && !Array.from(unsupported.children).some((el) => !el.matches('.workspace__unsupported-statement') && shown(el))) {
        fail('tier.c-workbench-unsupported', 'the unsupported state has its statement but no read-only summary');
      }
    }
  }

  // 14. Pointer targets (§10.1), reported: a canvas handle is legitimately
  //     small, so this stays measured until S6 settles its exceptions.
  const small = [];
  for (const el of Array.from(document.querySelectorAll('button, a[href], input, select')).filter(shown)) {
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) small.push(describe(el) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  }
  evaluated.add('a11y.target-size');
  if (small.length) fail('a11y.target-size', small.length + ' pointer target(s) under 24x24: ' + small.slice(0, 4).join(', '));

  return {
    findings, evaluated: Array.from(evaluated), foundationEvaluated: Array.from(foundationEvaluated), pageWidth, declaresFullWidth, shell,
    pressed: { proven: Array.from(pressed.proven), unproven: pressed.unproven },
  };
}

/**
 * Archetype conformance (§4): the rules only a rendered page can settle —
 * which element owns the scroll, how wide the regions came out, whether an
 * inspector is a column or a drawer.
 *
 * @param {{ tier: string, width: number, archetype: string }} input
 */
export function workspaceAssertions(input) {
  const findings = [];
  const evaluated = new Set();
  const fail = (rule, message) => findings.push({ rule, message });
  const doc = document.documentElement;
  const round = (n) => Math.round(n * 10) / 10;
  const named = (el) => (el.className && typeof el.className === 'string'
    ? '.' + el.className.trim().split(/\s+/).join('.') : el.tagName.toLowerCase());

  evaluated.add('archetype.rendered');
  const workspace = document.querySelector('.workspace');
  if (!workspace) {
    fail('archetype.rendered', 'expected the ' + input.archetype + ' archetype, rendered none (no .workspace element)');
    return { findings, evaluated: Array.from(evaluated), measured: null };
  }
  const archetype = Array.from(workspace.classList).find((c) => c.startsWith('workspace--')) || 'unknown';
  const working = workspace.getBoundingClientRect().width;
  const measured = { archetype: archetype.replace('workspace--', ''), workingWidth: round(working) };
  if (measured.archetype !== input.archetype) {
    fail('archetype.rendered', 'expected the ' + input.archetype + ' archetype, rendered ' + measured.archetype);
  }
  const column = workspace.closest('.main');
  measured.shellScroll = column ? column.getAttribute('data-scroll') : null;

  // A contained column clips in both directions (§26): with the column set to
  // contain, overflowing content is simply unreachable. Contained is what the
  // column *computes* — a declared policy the stylesheet lifts (a stacking
  // archetype at ≤1100, §25 Tier B) leaves a column that scrolls, and content
  // it can scroll to is reachable.
  measured.columnOverflowStyle = column ? getComputedStyle(column).overflowY : null;
  // A column that scrolls (a stacked archetype at ≤1100) still must not
  // scroll sideways: the page's own scroller is the content column, not the
  // document, so page.horizontal-overflow alone cannot see it.
  // Evaluated wherever there is such a column — a pass is recorded, not only
  // a failure (at Tier C every archetype reads down a scrolling column).
  if (column && !/^(hidden|clip)$/.test(measured.columnOverflowStyle)) evaluated.add('archetype.contained-clipping');
  if (column && !/^(hidden|clip)$/.test(measured.columnOverflowStyle) && column.scrollWidth > column.clientWidth + 1) {
    fail('archetype.contained-clipping', 'the content column scrolls sideways: ' + column.scrollWidth + 'px of content in '
      + column.clientWidth + 'px, a horizontal page scroll to the operator');
  }
  if (column && /^(hidden|clip)$/.test(measured.columnOverflowStyle)) {
    evaluated.add('archetype.contained-clipping');
    measured.columnOverflow = round(column.scrollHeight - column.clientHeight);
    measured.columnOverflowX = round(column.scrollWidth - column.clientWidth);
    if (column.scrollHeight > column.clientHeight + 1) {
      fail('archetype.contained-clipping', 'the shell column is contained but its content is ' + column.scrollHeight
        + 'px inside ' + column.clientHeight + 'px, so ' + measured.columnOverflow + 'px cannot be reached');
    }
    if (workspace.scrollHeight > workspace.clientHeight + 1) {
      fail('archetype.contained-clipping', 'the workspace is ' + workspace.scrollHeight + 'px inside '
        + workspace.clientHeight + 'px with no scroll owner for the difference');
    }
    if (column.scrollWidth > column.clientWidth + 1) {
      fail('archetype.contained-clipping', 'the shell column is contained but its content is ' + column.scrollWidth
        + 'px wide inside ' + column.clientWidth + 'px, so ' + measured.columnOverflowX + 'px is off the right edge');
    }
    if (workspace.scrollWidth > workspace.clientWidth + 1) {
      fail('archetype.contained-clipping', 'the workspace is ' + workspace.scrollWidth + 'px wide inside '
        + workspace.clientWidth + 'px with no scroll owner for the difference');
    }
  }

  const scrollers = Array.from(workspace.querySelectorAll('*')).filter((el) => {
    const style = getComputedStyle(el);
    return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 1;
  }).map(named);
  measured.scrollers = scrollers;

  const framedBlock = (el) => {
    const s = getComputedStyle(el);
    return ['Top', 'Right', 'Bottom', 'Left'].every((side) => parseFloat(s['border' + side + 'Width']) >= 1
      && s['border' + side + 'Style'] !== 'none') && el.getBoundingClientRect().height >= 48;
  };

  // --- Ledger (§4.1; S1d containment, S1e loading geometry) ------------------
  if (archetype === 'workspace--ledger' || archetype === 'workspace--ledger-summary') {
    const summary = archetype === 'workspace--ledger-summary';
    evaluated.add('ledger.scroll-ownership');
    // §4.1 and §25 Tier B: the body owns the scroll at every width — a Ledger
    // is one column and has nothing to stack — so the shell column is `body`,
    // never lifted, and the page never scrolls. At Tier C the Ledger is the
    // §25 single-column list, read down the page: the content column is the
    // one scroller, and the frame must not be a second one inside it.
    const narrowList = input.tier === 'C';
    if (measured.shellScroll !== 'body') {
      fail('ledger.scroll-ownership', 'the Ledger did not declare its body the scroll owner to the shell: the content column is "' + measured.shellScroll + '"');
    }
    if (doc.scrollHeight > doc.clientHeight + 1) {
      fail('ledger.scroll-ownership', 'the Ledger page scrolls: scrollHeight ' + doc.scrollHeight + ' > clientHeight ' + doc.clientHeight);
    }
    const region = workspace.querySelector(summary ? '.workspace__body--scroll' : '.workspace__body--ledger');
    if (!region) {
      fail('archetype.rendered', 'the Ledger is missing its body region');
      return { findings, evaluated: Array.from(evaluated), measured };
    }
    const table = region.querySelector('table');
    const frame = summary ? region : region.querySelector(':scope > .ledger-table');

    if (!summary) {
      evaluated.add('ledger.containment');
      const regionStyle = getComputedStyle(region);
      if (parseFloat(regionStyle.borderTopWidth) > 0 || /(auto|scroll)/.test(regionStyle.overflowY)) {
        fail('ledger.scroll-ownership', 'the Ledger body region is itself bordered or scrolling: the frame belongs to the table, not to the slot');
      }
      if (table && !frame) fail('ledger.containment', 'the Ledger table is not inside its containment frame');
      if (!table && region.querySelector('.ledger-table')) {
        fail('ledger.containment', 'a containment frame with no table in it: a state presentation is contained');
      }
      // The Ledger state presentation is in the body region it replaces, as
      // its first child, uncontained (§37.1).
      const presentation = region.querySelector(':scope > .state-region');
      if (presentation) {
        evaluated.add('state.placement');
        let node = presentation;
        while (node && node !== region) {
          if (framedBlock(node) && node !== presentation) {
            fail('state.placement', 'the Ledger state presentation is inside a bordered frame (' + named(node) + ')');
            break;
          }
          node = node.parentElement;
        }
        if (framedBlock(presentation)) fail('state.placement', 'the Ledger state presentation is itself drawn as a frame');
      } else if (!table && region.querySelector('.state-region')) {
        evaluated.add('state.placement');
        fail('state.placement', 'the Ledger state presentation is not a direct child of the body region it replaces');
      }

      evaluated.add('ledger.loading-geometry');
      const firstRow = table ? table.querySelector('tbody tr') : region.querySelector('.skeleton__row');
      if (firstRow) {
        measured.firstRowTop = round(firstRow.getBoundingClientRect().top);
        measured.firstRowKind = table ? 'table' : 'skeleton';
      }
      if (!table && region.querySelector('.skeleton__row') && !region.querySelector('.skeleton__head')) {
        fail('ledger.loading-geometry', 'the loading skeleton reserves no header region: the table header will push its rows down');
      }
      if (table) {
        const headRow = table.querySelector('thead tr');
        if (headRow) measured.headerHeight = round(headRow.getBoundingClientRect().height);
      }
    }

    if (table && frame) {
      const nested = Array.from(frame.querySelectorAll('*')).filter((el) => {
        const style = getComputedStyle(el);
        return /(auto|scroll)/.test(style.overflowY) || /(auto|scroll)/.test(style.overflowX);
      });
      measured.nestedScrollRegions = nested.map(named);
      if (nested.length) fail('ledger.scroll-ownership', 'a scrolling container inside the Ledger scroll owner: ' + measured.nestedScrollRegions.join(', '));
      if (!summary) {
        const innerFrames = Array.from(frame.querySelectorAll('*')).filter((el) => !el.matches('button, a, input, select, .badge') && framedBlock(el));
        if (innerFrames.length) fail('ledger.containment', 'a bordered frame inside the Ledger frame: ' + innerFrames.slice(0, 3).map(named).join(', '));
      }

      if (narrowList && /(auto|scroll)/.test(getComputedStyle(frame).overflowY)) {
        fail('ledger.scroll-ownership', 'the Ledger frame is a scroller inside the page at Tier C: a list read down the page has one scroll');
      }
      const th = narrowList ? null : table.querySelector('thead th');
      if (th) {
        measured.headerPosition = getComputedStyle(th).position;
        if (measured.headerPosition !== 'sticky') {
          fail('ledger.scroll-ownership', 'the Ledger header is "' + measured.headerPosition + '", not sticky, so it scrolls away with the rows');
        }
        let scroller = null;
        for (let node = th.parentElement; node; node = node.parentElement) {
          if (/(auto|scroll)/.test(getComputedStyle(node).overflowY)) { scroller = node; break; }
        }
        if (scroller !== frame) {
          fail('ledger.scroll-ownership', 'the Ledger header would stick to ' + (scroller ? named(scroller) : 'nothing') + ' rather than to the frame that owns the scroll');
        }
      }

      const tableRect = table.getBoundingClientRect();
      const frameRect = frame.getBoundingClientRect();
      measured.tableWidth = round(tableRect.width);
      measured.tableHeight = round(tableRect.height);
      measured.frameWidth = round(frameRect.width);
      measured.frameHeight = round(frameRect.height);
      measured.regionHeight = round(region.getBoundingClientRect().height);

      if (!summary) {
        // §4.1 amended: the frame ends where the table does, sideways and
        // downward — no viewport-high frame around a sparse table (F1).
        const scrollbarAllowance = 24;
        if (frameRect.width > tableRect.width + scrollbarAllowance) {
          fail('ledger.containment', 'the frame is ' + measured.frameWidth + 'px wide around a ' + measured.tableWidth + 'px table');
        }
        measured.frameScrolls = frame.scrollHeight > frame.clientHeight + 1;
        if (!measured.frameScrolls && frameRect.height > tableRect.height + scrollbarAllowance) {
          fail('ledger.containment', 'the frame is ' + measured.frameHeight + 'px tall around a ' + measured.tableHeight
            + 'px table that does not scroll: an empty bordered box below the rows');
        }

        // §16 amended: every visible data row 36-40px. The rows are the body
        // rows the operator reads — not the header, not a hidden or detail row
        // — and a table with a body but no measurable row is a finding, not a
        // pass: a selector that matches nothing has checked nothing. A Tier C
        // list item is several lines by design (tier.c-composition).
        if (!narrowList) {
          evaluated.add('ledger.row-pitch');
          const bodyRows = Array.from(table.querySelectorAll(':scope > tbody > tr'));
          const rows = bodyRows.filter((row) => {
            if (row.hidden || row.matches('[data-row="detail"], .is-detail')) return false;
            const r = row.getBoundingClientRect();
            return r.height > 0 && getComputedStyle(row).display !== 'none';
          });
          measured.rowCount = rows.length;
          if (bodyRows.length && !rows.length) fail('ledger.row-pitch', 'the Ledger has body rows but none is visible to measure');
          if (!bodyRows.length) fail('ledger.row-pitch', 'the Ledger table rendered with no body rows to measure');
          if (rows.length) {
            const pitches = rows.map((row) => row.getBoundingClientRect().height);
            measured.rowPitchMin = round(Math.min(...pitches));
            measured.rowPitchMax = round(Math.max(...pitches));
            if (measured.rowPitchMin < 35.5 || measured.rowPitchMax > 40.5) {
              fail('ledger.row-pitch', 'the Ledger row pitch is ' + measured.rowPitchMin + '-' + measured.rowPitchMax + 'px, outside 36-40px');
            }
          }
        }
        evaluated.add('ledger.row-primary');
        const rowPrimaries = table.querySelectorAll('tbody .btn--primary');
        if (rowPrimaries.length) fail('ledger.row-primary', 'Ledger rows carry ' + rowPrimaries.length + ' accent-filled primary action(s)');

        // §25 (M1): no clipped or unreachable row action, on every Ledger. The
        // table body MAY scroll sideways (§4.1), and below 1100 the page does
        // instead: an action a scrolling box can bring into view is reachable,
        // and that is not a finding. Unreachable is what no scrolling reveals
        // — an action cut by a box that clips without scrolling (R2's retry
        // behind a capped status line), at any level up to the document.
        evaluated.add('ledger.actions-reachable');
        measured.frameScrollWidth = frame.scrollWidth;
        measured.frameClientWidth = frame.clientWidth;
        const visibleLeft = frameRect.left + frame.clientLeft;
        const visibleRight = visibleLeft + frame.clientWidth;
        const actions = Array.from(table.querySelectorAll('tbody a, tbody button'))
          .filter((control) => control.getBoundingClientRect().width > 0);
        const outside = (r) => r.right > visibleRight + 0.5 || r.left < visibleLeft - 0.5;
        const scrolls = (value) => value === 'auto' || value === 'scroll';
        const unreachable = actions.filter((control) => {
          const c = control.getBoundingClientRect();
          let r = { left: c.left, right: c.right, top: c.top, bottom: c.bottom };
          for (let node = control.parentElement; node; node = node.parentElement) {
            const style = getComputedStyle(node);
            if (style.overflowX === 'visible' && style.overflowY === 'visible') continue;
            const box = node.getBoundingClientRect();
            // A scrolling box can bring the action to its own start; a box
            // that clips without scrolling hides whatever lies outside it.
            if (scrolls(style.overflowX)) r = { ...r, left: box.left, right: box.left + (r.right - r.left) };
            else if (r.left < box.left - 0.5 || r.right > box.right + 0.5) return true;
            if (scrolls(style.overflowY)) r = { ...r, top: box.top, bottom: box.top + (r.bottom - r.top) };
            else if (r.top < box.top - 0.5 || r.bottom > box.bottom + 0.5) return true;
          }
          return false;
        });
        if (unreachable.length) {
          fail('ledger.actions-reachable', unreachable.length + ' row action(s) are clipped where no scrolling of the frame reaches them');
        }

        // §4.1 "1366: all columns visible" as M1 accepts it for Cameras: its
        // supported columns fit at every Tier A anchor, so both row actions are
        // in view at rest. Scoped to Cameras rather than every Ledger, where
        // sideways scrolling remains permitted: an unbounded code or timezone
        // cell that pushes the actions out is this surface's defect.
        // Tier A only: below it the rule is not applicable (§25 lets a Ledger
        // scroll), and the ledger refuses an evaluation there.
        if (input.surface === 'cameras' && input.tier === 'A') {
          evaluated.add('cameras.actions-in-view');
          const offscreen = actions.filter((control) => outside(control.getBoundingClientRect()));
          if (offscreen.length) {
            fail('cameras.actions-in-view', offscreen.length + ' row action(s) lie outside the frame\'s visible width at rest (a '
              + frame.scrollWidth + 'px table in a ' + frame.clientWidth + 'px frame): the Camera columns do not fit');
          }
        }
      }

      if (!summary && doc.clientWidth >= 2400) {
        evaluated.add('ledger.ultrawide-alignment');
        if (working - tableRect.width < 200) {
          fail('ledger.ultrawide-alignment', 'the table is ' + measured.tableWidth + 'px inside a ' + round(working)
            + 'px workspace: a sparse table has been stretched rather than left-aligned');
        }
      }
    }
  }

  // --- Record (§4.2) -----------------------------------------------------------
  if (archetype === 'workspace--record') {
    evaluated.add('record.scroll-ownership');
    if (measured.shellScroll !== 'page') fail('record.scroll-ownership', 'the Record declared scroll policy "' + measured.shellScroll + '"; §4.2 gives the page the scroll');
    if (!workspace.querySelector('.workspace__record-grid')) fail('record.scroll-ownership', 'the Record is missing its primary/facts grid');
  }

  // --- Investigation (§4.4, §20) ----------------------------------------------
  if (archetype === 'workspace--investigation') {
    const grid = workspace.querySelector('.workspace__investigation-grid');
    const rail = workspace.querySelector('.workspace__rail');
    const results = workspace.querySelector('.workspace__results');
    if (!grid || !rail || !results) {
      fail('archetype.rendered', 'the Investigation is missing its rail, results or grid region');
      return { findings, evaluated: Array.from(evaluated), measured };
    }
    const railWidth = rail.getBoundingClientRect().width;
    const resultsWidth = results.getBoundingClientRect().width;
    measured.railWidth = round(railWidth);
    measured.resultsWidth = round(resultsWidth);
    measured.inspectorPlacement = getComputedStyle(workspace).getPropertyValue('--inspector-placement').trim() || null;
    evaluated.add('investigation.scroll-ownership');
    if (measured.shellScroll !== 'contain') fail('investigation.scroll-ownership', 'the Investigation did not declare no-page-scroll to the shell: the content column is "' + measured.shellScroll + '"');
    if (doc.clientWidth > 1100 && doc.scrollHeight > doc.clientHeight + 1) {
      fail('investigation.scroll-ownership', 'the Investigation page scrolls: scrollHeight ' + doc.scrollHeight + ' > clientHeight ' + doc.clientHeight);
    }
    if (doc.clientWidth > 1100) {
      evaluated.add('investigation.geometry');
      if (railWidth < 240 || railWidth > 264) fail('investigation.geometry', 'the rail is ' + measured.railWidth + 'px, not the fixed 252px of §4.4');
      if (!/(auto|scroll)/.test(getComputedStyle(rail).overflowY)) fail('investigation.scroll-ownership', 'the rail cannot scroll independently of the results');
      const railInner = Array.from(rail.querySelectorAll('*')).filter((el) => {
        const style = getComputedStyle(el);
        return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 1;
      });
      if (railInner.length) fail('investigation.scroll-ownership', 'the rail has a second scroll owner inside it: ' + railInner.map(named).join(', '));
      if (resultsWidth > 910) fail('investigation.geometry', 'the results column is ' + measured.resultsWidth + 'px, above the ~900px cap of §4.4');
      if (working - railWidth > 600 && resultsWidth < 555) {
        fail('investigation.geometry', 'the results column is ' + measured.resultsWidth + 'px inside a ' + round(working) + 'px workspace, below the ~560px floor of §4.4');
      }
      const list = results.querySelector('.results__list');
      if (list && !/(auto|scroll)/.test(getComputedStyle(list).overflowY)) fail('investigation.scroll-ownership', 'the results list does not own its scroll');
    }
    const inspector = workspace.querySelector('.workspace__inspector');
    if (inspector && doc.clientWidth > 1100) {
      const style = getComputedStyle(inspector);
      const inspectorWidth = inspector.getBoundingClientRect().width;
      measured.inspectorWidth = round(inspectorWidth);
      measured.inspectorPosition = style.position;
      if (measured.inspectorPlacement === 'in-place') {
        if (style.position === 'absolute') fail('investigation.geometry', 'the inspector is still a drawer at ' + doc.clientWidth + 'px, where the layout declares it in place');
        if (working - railWidth - resultsWidth > 40 && inspectorWidth < 320) {
          fail('investigation.geometry', 'the inspector is only ' + measured.inspectorWidth + 'px while '
            + round(working - railWidth - resultsWidth) + 'px of surplus exists: §4.4 gives the surplus to the inspector');
        }
      } else if (measured.inspectorPlacement === 'drawer') {
        if (style.position !== 'absolute') fail('investigation.geometry', 'the inspector is an in-flow column at ' + doc.clientWidth + 'px, where the layout declares it a drawer');
      } else {
        fail('investigation.geometry', 'the Investigation did not declare an inspector placement');
      }
      evaluated.add('overlay.drawer');
      const modal = inspector.getAttribute('role') === 'dialog' && inspector.getAttribute('aria-modal') === 'true';
      measured.inspectorModal = modal;
      if (style.position === 'absolute') {
        if (!modal) fail('overlay.drawer', 'the Investigation drawer at ' + doc.clientWidth + 'px is not a modal dialog: §20 requires the overlay to hold focus');
        else if (!inspector.getAttribute('aria-labelledby')) fail('overlay.drawer', 'the Investigation drawer has no programmatic name from its heading (§20)');
        for (const [name, region] of [['results', results], ['rail', rail]]) {
          if (!region.hasAttribute('inert')) fail('overlay.drawer', 'the Investigation ' + name + ' beside the drawer are not inert (§20)');
        }
      } else if (modal || workspace.querySelector('[role="dialog"], [aria-modal="true"], [inert]')) {
        fail('overlay.drawer', 'the in-place Investigation inspector claims modality: a permanent column is not a dialog (§20)');
      }
    }
  }

  // --- Workbench (§4.3) --------------------------------------------------------
  if (archetype === 'workspace--workbench') {
    const stage = workspace.querySelector('.workspace__stage');
    const inspector = workspace.querySelector('.workspace__inspector');
    // Below 768px the Workbench is its §25 unsupported state, judged by
    // tier.c-workbench-unsupported; its stage and inspector are not rendered.
    if (input.tier === 'C' && workspace.classList.contains('workspace--unsupported')) {
      return { findings, evaluated: Array.from(evaluated), measured };
    }
    if (!stage || !inspector) {
      fail('archetype.rendered', 'the Workbench is missing its stage or inspector region');
      return { findings, evaluated: Array.from(evaluated), measured };
    }
    const stageWidth = stage.getBoundingClientRect().width;
    const inspectorWidth = inspector.getBoundingClientRect().width;
    const share = working > 0 ? stageWidth / working : 0;
    measured.stageWidth = round(stageWidth);
    measured.inspectorWidth = round(inspectorWidth);
    measured.stageShare = round(share * 100);
    // Above the stacking threshold the inspector is a drawer in two cases,
    // each its own obligation: the frozen 1101-1149 band (§4.3.1, §25 Tier B:
    // "1101px up to the measured ~1150 threshold", measured in R4), and any
    // working width at which the stage could not keep its 65% floor beside a
    // 300px inspector. Both are derived here from the specification's figures,
    // the viewport and the measured working width — not from the product's
    // class — so a wrong class is a finding, not a silenced rule.
    measured.workbenchDrawer = workspace.classList.contains('is-drawer');
    const inBand = doc.clientWidth > 1100 && doc.clientWidth < 1150;
    const expectDrawer = doc.clientWidth > 1100 && (inBand || working < (300 + 12) / (1 - 0.65));
    measured.expectedWorkbenchDrawer = expectDrawer;
    if (doc.clientWidth > 1100) {
      evaluated.add('workbench.geometry');
      if (expectDrawer !== measured.workbenchDrawer) {
        fail('workbench.geometry', 'the Workbench is ' + (measured.workbenchDrawer ? 'a drawer' : 'side by side') + ' at ' + doc.clientWidth + 'px (working width '
          + round(working) + 'px), where ' + (inBand ? 'the frozen 1101-1149 band' : 'the 65% floor beside a 300px inspector') + ' makes it ' + (expectDrawer ? 'a drawer' : 'side by side'));
      }
      // The drawer composition, from rendered geometry: the stage keeps the
      // full working width, and the inspector is either shut (out of the
      // layout, its toggle shown) or open as the modal over the stage.
      if (expectDrawer) {
        if (stageWidth < working - 1) {
          fail('workbench.geometry', 'in the drawer band the stage is ' + measured.stageWidth + 'px of a ' + round(working) + 'px working width; the drawer exists so it keeps all of it');
        }
        const open = inspector.getAttribute('role') === 'dialog' && inspector.getAttribute('aria-modal') === 'true' && inspectorWidth > 0;
        const shut = getComputedStyle(inspector).display === 'none';
        const toggle = workspace.querySelector('.workspace__drawer-toggle');
        const toggleShown = toggle && getComputedStyle(toggle).display !== 'none' && toggle.getBoundingClientRect().width > 0;
        if (!open && !shut) fail('workbench.geometry', 'in the drawer band the inspector is neither shut nor the open modal drawer: it is ' + measured.inspectorWidth + 'px in flow');
        if (shut && !toggleShown) fail('workbench.geometry', 'the shut inspector drawer has no visible control to open it');
      }
    }
    const sideBySide = doc.clientWidth > 1100 && !measured.workbenchDrawer;
    if (sideBySide) {
      evaluated.add('workbench.geometry');
      evaluated.add('overlay.drawer');
      if (share < 0.65) fail('workbench.geometry', 'the stage is ' + measured.stageShare + '% of the working width, below the 65% floor');
      if (inspectorWidth < 299 || inspectorWidth > 361) fail('workbench.geometry', 'the inspector is ' + measured.inspectorWidth + 'px, outside the fixed 300-360 range');
      if (inspector.getAttribute('role') === 'dialog' || inspector.hasAttribute('aria-modal') || workspace.querySelector('[inert]')) {
        fail('overlay.drawer', 'the permanent Workbench inspector claims modality: only the is-drawer overlay is a drawer (§20)');
      }
    }
    const scrolledAncestors = [];
    for (let node = workspace.parentElement; node; node = node.parentElement) {
      if (!/(auto|scroll)/.test(getComputedStyle(node).overflowY)) continue;
      if (node.scrollHeight > node.clientHeight + 1) scrolledAncestors.push(named(node) + ' (' + node.scrollHeight + ' > ' + node.clientHeight + ')');
    }
    measured.scrolledAncestors = scrolledAncestors;
    // No page scroll wherever the Workbench is not stacked (§4.3.2): side by
    // side and drawer alike.
    if (doc.clientWidth > 1100) {
      evaluated.add('workbench.scroll-ownership');
      if (measured.shellScroll !== 'contain') fail('workbench.scroll-ownership', 'the Workbench did not declare no-page-scroll to the shell: the content column is "' + measured.shellScroll + '"');
      if (doc.scrollHeight > doc.clientHeight + 1) fail('workbench.scroll-ownership', 'the Workbench page scrolls: scrollHeight ' + doc.scrollHeight + ' > clientHeight ' + doc.clientHeight);
      for (const name of scrolledAncestors) fail('workbench.scroll-ownership', 'the Workbench scrolls inside ' + name + ', which is a page scroll to the operator');
      const stray = scrollers.filter((name) => !name.includes('inspector__body'));
      if (stray.length) fail('workbench.scroll-ownership', 'a scroll owner other than the inspector body: ' + stray.join(', '));
    }
  }

  // --- Review (§4.5, §18) ------------------------------------------------------
  if (archetype === 'workspace--review') {
    const player = workspace.querySelector('.workspace__player');
    const rail = workspace.querySelector('.workspace__review-rail');
    if (!player) {
      fail('archetype.rendered', 'the Review is missing its player region');
      return { findings, evaluated: Array.from(evaluated), measured };
    }
    const playerBox = player.getBoundingClientRect();
    measured.playerWidth = round(playerBox.width);
    measured.playerShare = working > 0 ? round((playerBox.width / working) * 100) : null;
    measured.reviewRailWidth = rail ? round(rail.getBoundingClientRect().width) : null;
    if (doc.clientWidth > 1100) {
      evaluated.add('review.composition');
      if (measured.playerShare !== null && measured.playerShare < 64.9) {
        fail('review.composition', 'the player has only ' + measured.playerShare + '% of the working width; §4.5 requires at least 65%');
      }
      if (doc.clientWidth >= 1900 && measured.playerShare !== null && measured.playerShare < 70) {
        fail('review.composition', 'the player has only ' + measured.playerShare + '% of the working width at ' + doc.clientWidth + 'px; §25 sends ultra-wide surplus to the player');
      }
    }
    // review.composition is not applicable at Tier C (the manifest): there
    // tier.c-composition judges the player, then the summary, then provenance.
    // The 384px height of a 200% zoom (T3) is the first Tier C view short
    // enough to reach the initial-viewport rule below, so the tier is said.
    const summary = rail ? rail.querySelector('.panel') : null;
    if (input.tier === 'C') {
      // judged by tier.c-composition
    } else if (!summary) {
      evaluated.add('review.composition');
      fail('review.composition', 'the Review is missing the primary evidence summary in its rail');
    } else if (doc.clientHeight <= 800) {
      evaluated.add('review.composition');
      const summaryBox = summary.getBoundingClientRect();
      measured.summaryTop = round(summaryBox.top);
      // §4.5.1: the player and the primary summary in the initial viewport is
      // the side-by-side composition's rule ("at 1366x768"); stacked (≤1100)
      // the rail goes below the player by the same section, and the summary
      // with it. The player itself starts in the initial viewport everywhere.
      if (doc.clientWidth > 1100 && summaryBox.top >= doc.clientHeight) fail('review.composition', 'the primary evidence summary starts at ' + measured.summaryTop + 'px, below the ' + doc.clientHeight + 'px initial viewport (§4.5.1)');
      if (playerBox.top >= doc.clientHeight) fail('review.composition', 'the Evidence Player starts below the initial viewport (§4.5.1)');
    }
    evaluated.add('review.sticky-declared');
    measured.playerSticky = getComputedStyle(player).position;
    if (doc.clientWidth > 1100 && measured.playerSticky !== 'sticky') {
      fail('review.sticky-declared', 'the Evidence Player column is ' + measured.playerSticky + ', not declared sticky (§4.5.1)');
    }
    if (doc.clientWidth <= 1100 && measured.playerSticky === 'sticky') {
      fail('review.sticky-declared', 'the stacked Review still pins its player; §4.5.1 releases that at 1100');
    }

    evaluated.add('review.timeline');
    measured.timelines = workspace.querySelectorAll('.evidence-timeline__track').length;
    if (measured.timelines !== 1) fail('review.timeline', 'the Review renders ' + measured.timelines + ' timelines; §18 allows exactly one');
    const hiddenEvidence = workspace.querySelectorAll('.evidence-timeline__item[aria-hidden]').length;
    if (hiddenEvidence > 0) fail('review.timeline', hiddenEvidence + ' timeline evidence items are hidden from assistive technology');
    measured.timelineItems = workspace.querySelectorAll('.evidence-timeline__item').length;
    const zoneBands = Array.from(workspace.querySelectorAll('.evidence-timeline__item[data-lane="zone"][data-drawn="true"]:not([data-shown])'));
    const overflowed = workspace.querySelectorAll('[data-lane="zone"][data-drawn="density"]');
    const shownBands = Array.from(workspace.querySelectorAll('.evidence-timeline__item[data-shown="true"]'));
    measured.shownOverflowed = shownBands.length;
    if (shownBands.length > 1) fail('review.timeline', shownBands.length + ' overflowed visits are drawn at once; only one can be singled out');
    const railTops = new Set(Array.from(workspace.querySelectorAll('.evidence-timeline__overflow')).map((band) => band.style.top));
    for (const band of shownBands) {
      if (railTops.size > 0 && !railTops.has(band.style.top)) fail('review.timeline', 'a singled-out overflowed visit is drawn off the overflow rail, adding a row to the zone lane');
    }
    measured.zoneBands = zoneBands.length;
    measured.zoneOverflowed = overflowed.length;
    const zoneRows = new Set(zoneBands.map((band) => band.style.top));
    measured.zoneRows = zoneRows.size;
    if (zoneRows.size > 3) fail('review.timeline', 'the zone lane uses ' + zoneRows.size + ' sub-rows; the cap is 3');
    for (let i = 0; i < zoneBands.length; i += 1) {
      for (let j = i + 1; j < zoneBands.length; j += 1) {
        if (zoneBands[i].style.top !== zoneBands[j].style.top) continue;
        const a = zoneBands[i].getBoundingClientRect();
        const b = zoneBands[j].getBoundingClientRect();
        if (a.left < b.right - 0.5 && b.left < a.right - 0.5) fail('review.timeline', 'two concurrent zone visits are drawn over each other on one sub-row');
      }
    }
    if (overflowed.length > 0 && !workspace.querySelector('.evidence-timeline__overflow-badge')) {
      fail('review.timeline', overflowed.length + ' zone visits are in the overflow rail with no count shown');
    }
    const bands = Array.from(workspace.querySelectorAll('.evidence-timeline__overflow'));
    measured.overflowBands = bands.length;
    for (let i = 0; i < bands.length; i += 1) {
      for (let j = i + 1; j < bands.length; j += 1) {
        const a = bands[i].getBoundingClientRect();
        const b = bands[j].getBoundingClientRect();
        if (a.left < b.right - 0.5 && b.left < a.right - 0.5) fail('review.timeline', 'two overflow density bands overlap');
      }
    }
    for (const track of workspace.querySelectorAll('.evidence-timeline__track')) {
      const onRail = track.querySelectorAll(':scope > li[data-drawn="overflow"]').length;
      if (onRail > 0) fail('review.timeline', onRail + ' overflowed visits are named on the rail as well as in the navigator');
    }
    const navigator = workspace.querySelector('.evidence-timeline__dense');
    if (navigator) {
      measured.denseControls = navigator.querySelectorAll('summary, button').length;
      if (measured.denseControls > 3) fail('review.timeline', 'dense evidence offers ' + measured.denseControls + ' controls; the navigator is a fixed three');
      if (navigator.querySelector('ul, ol')) fail('review.timeline', 'dense evidence has grown a second list beside the one timeline');
    }
    const markerButtons = Array.from(workspace.querySelectorAll('.evidence-timeline__marker-button'));
    measured.markerControls = markerButtons.length;
    const smallMarkers = markerButtons.filter((button) => {
      const box = button.getBoundingClientRect();
      return box.width < 23.5 || box.height < 23.5;
    });
    if (smallMarkers.length > 0) fail('review.timeline', smallMarkers.length + ' timeline marker controls are under the 24x24 minimum');
    for (let i = 0; i < markerButtons.length; i += 1) {
      for (let j = i + 1; j < markerButtons.length; j += 1) {
        const a = markerButtons[i].getBoundingClientRect();
        const b = markerButtons[j].getBoundingClientRect();
        if (a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5) {
          fail('review.timeline', 'two timeline marker controls overlap, so one of them cannot be clicked');
        }
      }
    }

    evaluated.add('review.analytical-geometry');
    const stage = workspace.querySelector('.evidence-player__stage');
    const geometry = workspace.querySelectorAll('[data-testid="evidence-zone"], [data-testid="evidence-line"], [data-testid="evidence-crossing"]');
    measured.analyticalGeometry = geometry.length;
    if (stage && geometry.length > 0) {
      const frame = stage.getBoundingClientRect();
      let outside = 0;
      for (const node of geometry) {
        const box = node.getBoundingClientRect();
        if (box.width === 0 && box.height === 0) continue;
        if (box.left < frame.left - 1 || box.right > frame.right + 1 || box.top < frame.top - 1 || box.bottom > frame.bottom + 1) outside += 1;
      }
      if (outside > 0) fail('review.analytical-geometry', outside + ' analytical overlay shapes fall outside the video content rectangle');
    }
    const directedLines = Array.from(workspace.querySelectorAll('[data-testid="evidence-line"]')).filter((group) => group.querySelector('.evidence-line__dir'));
    measured.directedLines = directedLines.length;
    for (const group of directedLines) {
      const segment = group.querySelector('.evidence-line__segment');
      if (!segment) continue;
      const lx = Number(segment.getAttribute('x2')) - Number(segment.getAttribute('x1'));
      const ly = Number(segment.getAttribute('y2')) - Number(segment.getAttribute('y1'));
      const cues = Array.from(group.querySelectorAll('.evidence-line__dir'));
      if (cues.length !== 2) fail('review.analytical-geometry', 'a directed trip line draws ' + cues.length + ' direction cues; both directions have to be shown');
      for (const cue of cues) {
        const ray = cue.querySelector('line');
        if (!ray) continue;
        const rx = Number(ray.getAttribute('x2')) - Number(ray.getAttribute('x1'));
        const ry = Number(ray.getAttribute('y2')) - Number(ray.getAttribute('y1'));
        const lengths = Math.hypot(lx, ly) * Math.hypot(rx, ry);
        if (lengths <= 0) continue;
        const degrees = Math.acos(Math.min(1, Math.max(-1, (lx * rx + ly * ry) / lengths))) * 180 / Math.PI;
        measured.directionAngle = Math.round(degrees * 10) / 10;
        if (Math.abs(degrees - 90) > 1) fail('review.analytical-geometry', 'a crossing direction cue is ' + Math.round(degrees) + ' degrees from its line, not perpendicular');
        if (!cue.querySelector('polygon')) fail('review.analytical-geometry', 'a crossing direction cue has no arrowhead, so which way it points depends on colour');
        const label = cue.querySelector('text');
        if (!label || label.textContent.trim() === '') fail('review.analytical-geometry', 'a crossing direction cue is unlabelled, so the two directions differ only by hue');
      }
    }
    if (workspace.querySelector('video[controls]')) fail('review.analytical-geometry', 'the Evidence Player is using native browser controls');
  }

  // --- Ledger column fold (§25 Tier B Ledger row, §4.1) -----------------------
  //     Each operational Ledger's stated fold priority, judged from the
  //     rendered table: which columns fold, where, into what, and back.
  if (archetype === 'workspace--ledger') {
    // The statement is the harness's own (T1's register), not the product's
    // markup: `below` is the region width under which the base inventory's
    // unfolded table no longer fits (the container-query floor).
    const STATED = {
      videos: { folds: ['Recorded', 'Duration'], keeps: ['File', 'Camera', 'Status', 'Actions'], below: 969, sortable: true },
      'processing-queue': { folds: ['Queued', 'Attempt', 'Tracks'], keeps: ['Video', 'Status', 'Analytics', 'Actions'], below: 1012 },
      cameras: { folds: ['Timezone'], keeps: ['Code', 'Name', 'State', 'Actions'], below: 686 },
    };
    const scroller = workspace.querySelector('.ledger-table');
    const table = scroller && scroller.querySelector('table');
    const heads = table ? Array.from(table.querySelectorAll('thead th')) : [];
    if (table && heads.length > 0) {
      evaluated.add('ledger.column-fold');
      const stated = STATED[input.surface];
      const text = (el) => el.textContent.replace(/\s+/g, ' ').trim();
      const shown = (el) => getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0;
      const head = (name) => heads.find((th) => text(th).startsWith(name));
      // A header's stated name, without the sort glyph a sortable header draws.
      const nameOf = (th) => [...(stated?.folds ?? []), ...(stated?.keeps ?? [])].find((name) => text(th).startsWith(name)) ?? text(th);
      if (!stated) {
        fail('ledger.column-fold', 'a standard Ledger on "' + input.surface + '" has no stated fold priority: its Tier B composition would pass untested');
      } else {
        const missing = [...stated.folds, ...stated.keeps].filter((name) => !head(name));
        if (missing.length) fail('ledger.column-fold', 'the stated column(s) ' + missing.join(', ') + ' are not in the table');
        // Identity, status, analytics and the row action never fold.
        const lostKeeps = stated.keeps.filter((name) => head(name) && !shown(head(name)));
        if (lostKeeps.length) fail('ledger.column-fold', 'the Ledger hides ' + lostKeeps.join(', ') + ', which never fold (§25: by stated priority into the primary cell)');
        const foldHeads = stated.folds.map(head).filter(Boolean);
        const folded = foldHeads.filter((th) => !shown(th));
        const cs = getComputedStyle(workspace);
        const region = workspace.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        measured.ledgerRegion = round(region);
        measured.ledgerFolded = folded.length + '/' + foldHeads.length;
        if (folded.length > 0 && folded.length < foldHeads.length) {
          fail('ledger.column-fold', 'the fold is partial: ' + folded.map(nameOf).join(', ') + ' folded but ' + foldHeads.filter(shown).map(nameOf).join(', ') + ' shown');
        }
        if (input.tier === 'A' && folded.length > 0) {
          fail('ledger.column-fold', 'the Ledger folds ' + folded.map(nameOf).join(', ') + ' at Tier A, where §4.1 shows every column');
        }
        if (input.tier !== 'A') {
          if (region <= stated.below && folded.length < foldHeads.length) {
            fail('ledger.column-fold', 'the Ledger region is ' + round(region) + 'px, at or under its stated ' + stated.below + 'px, and '
              + foldHeads.filter(shown).map(nameOf).join(', ') + ' have not folded');
          }
          if (folded.length < foldHeads.length && scroller.scrollWidth > scroller.clientWidth + 1) {
            fail('ledger.column-fold', 'the Ledger body scrolls sideways (' + scroller.scrollWidth + 'px in ' + scroller.clientWidth
              + 'px) while its stated fold column(s) ' + foldHeads.filter(shown).map(nameOf).join(', ') + ' are still shown');
          }
          // Back: above its stated width a Ledger folds only because its
          // rendered table would not fit. The measured fold is set aside for
          // one synchronous read (nothing is painted) to see whether it would.
          if (folded.length === foldHeads.length && folded.length > 0 && region > stated.below) {
            const mark = workspace.getAttribute('data-fold');
            workspace.removeAttribute('data-fold');
            const fits = foldHeads.every(shown) && scroller.scrollWidth <= scroller.clientWidth + 1;
            if (mark !== null) workspace.setAttribute('data-fold', mark);
            if (fits) {
              fail('ledger.column-fold', 'the Ledger keeps ' + folded.map(nameOf).join(', ') + ' folded in a ' + round(region)
                + 'px region where its unfolded table fits: the columns must return');
            }
          }
        }
        if (folded.length > 0) {
          // Every value a folded column holds in a row (an empty or "—" cell
          // holds none) is shown in that row's primary cell, named by its
          // header in text a screen reader reads (not hidden from it).
          const lost = [];
          const unnamed = [];
          for (const th of folded) {
            const index = heads.indexOf(th);
            const header = nameOf(th);
            for (const tr of Array.from(table.querySelectorAll('tbody tr'))) {
              const cell = tr.children[index];
              const value = cell ? text(cell) : '';
              if (value === '' || value === '—') continue;
              const carried = Array.from(tr.querySelectorAll('.ledger-primary .ledger-folded__value')).find((v) => {
                const name = v.querySelector('.visually-hidden');
                return name && text(name) !== '' && header.startsWith(text(name)) && shown(v);
              });
              if (!carried) {
                lost.push(header);
                continue;
              }
              const name = carried.querySelector('.visually-hidden');
              const nameStyle = getComputedStyle(name);
              if (carried.closest('[aria-hidden="true"]') || nameStyle.display === 'none' || nameStyle.visibility === 'hidden') unnamed.push(header);
            }
          }
          if (lost.length) {
            fail('ledger.column-fold', lost.length + ' folded value(s) (' + Array.from(new Set(lost)).join(', ')
              + ') are hidden with their column but not shown in the row\'s primary cell');
          }
          if (unnamed.length) fail('ledger.column-fold', 'the folded ' + Array.from(new Set(unnamed)).join(', ') + ' value(s) lost their header name for assistive technology');
          // A folded sort key stays operable: the Sort select stands in for
          // the headers that left, offering each of them.
          if (stated.sortable) {
            const select = workspace.querySelector('.ledger-sort select');
            const keys = folded.filter((th) => th.hasAttribute('aria-sort')).map(nameOf);
            // At Tier C the select is in the filters drawer (§25): reachable
            // when the drawer that holds it has a visible control to open it.
            const drawer = select && select.closest('.toolbar-band__controls');
            const behindOpener = Boolean(input.tier === 'C' && drawer && drawer.id && !shown(select)
              && Array.from(document.querySelectorAll('[aria-controls]')).some((c) => c.getAttribute('aria-controls') === drawer.id && shown(c)));
            if (!select || (!shown(select) && !behindOpener) || select.disabled) {
              fail('ledger.column-fold', 'the folded sort key(s) ' + keys.join(', ') + ' have no visible, enabled Sort select');
            } else {
              const options = Array.from(select.options).map(text);
              const unsortable = keys.filter((key) => !options.some((o) => o.startsWith(key)));
              if (unsortable.length) fail('ledger.column-fold', 'the Sort select offers no order by ' + unsortable.join(', '));
            }
          }
        }
      }
    }
  }

  // --- Tier C compositions (§25): each archetype's narrow composition, judged
  //     from where its regions render.
  if (input.tier === 'C') {
    const box = (el) => el.getBoundingClientRect();
    const visible = (el) => el && getComputedStyle(el).display !== 'none' && box(el).width > 0 && box(el).height > 0;
    const modal = (el) => el && el.getAttribute('role') === 'dialog' && el.getAttribute('aria-modal') === 'true';
    const vw = doc.clientWidth;
    const fullWidth = (el) => box(el).left <= 0.5 && box(el).right >= vw - 0.5;
    const opener = (el) => el && el.id && Array.from(document.querySelectorAll('[aria-controls]'))
      .some((c) => c.getAttribute('aria-controls') === el.id && visible(c));
    if (archetype === 'workspace--ledger') {
      const table = workspace.querySelector('.ledger-table table');
      if (table) {
        evaluated.add('tier.c-composition');
        // "A single-column list of the primary cell plus status; the row's
        // action is reachable": no multi-column header drawn, each row one
        // item — its cells one column, its action beside them.
        const head = table.querySelector('thead');
        if (head && box(head).height > 1.5 && getComputedStyle(head).clipPath === 'none') {
          fail('tier.c-composition', 'the Ledger draws a ' + Math.round(box(head).height) + 'px column header at Tier C: it is still a multi-column table');
        }
        // The header is not drawn, so nothing in it may take keyboard focus:
        // a tab stop the operator cannot see is the defect.
        const hiddenStops = head ? Array.from(head.querySelectorAll('a[href], button, input, select, [tabindex]'))
          .filter((el) => el.tabIndex >= 0 && !el.disabled && getComputedStyle(el).display !== 'none') : [];
        if (head && getComputedStyle(head).clipPath !== 'none' && hiddenStops.length) {
          fail('tier.c-composition', 'the Ledger header is not drawn but holds ' + hiddenStops.length + ' tab stop(s): ' + hiddenStops.slice(0, 3).map((el) => el.textContent.trim().slice(0, 16)).join(', '));
        }
        const rows = Array.from(table.querySelectorAll('tbody tr')).filter(visible).slice(0, 40);
        measured.listRows = rows.length;
        rows.forEach((row, index) => {
          const cells = Array.from(row.children).filter(visible);
          const action = row.lastElementChild && visible(row.lastElementChild) ? row.lastElementChild : null;
          const column = cells.filter((cell) => cell !== action);
          const where = 'row ' + (index + 1);
          if (!column.length) return;
          const left = box(column[0]).left;
          for (let i = 1; i < column.length; i += 1) {
            if (Math.abs(box(column[i]).left - left) > 1 || box(column[i]).top < box(column[i - 1]).bottom - 1) {
              fail('tier.c-composition', 'the Ledger ' + where + ' lays its values out side by side at Tier C, not as one column');
              break;
            }
          }
          if (!column[0].textContent.trim()) fail('tier.c-composition', 'the Ledger ' + where + ' has no identity in its first line');
          if (!Array.from(row.querySelectorAll('.badge')).some(visible)) fail('tier.c-composition', 'the Ledger ' + where + ' shows no status');
          const controls = action ? Array.from(action.querySelectorAll('button, a[href]')).filter(visible) : [];
          if (!controls.length) fail('tier.c-composition', 'the Ledger ' + where + ' has no reachable action');
          for (const control of controls) {
            if (box(control).right > vw + 0.5 || box(control).left < -0.5) fail('tier.c-composition', 'the Ledger ' + where + ' action ' + control.textContent.trim().slice(0, 20) + ' is outside the viewport');
          }
          if (action && column.some((cell) => box(cell).right > box(action).left + 1)) {
            fail('tier.c-composition', 'the Ledger ' + where + ' values run under its action');
          }
        });
      }
      // "Filters move into a drawer": the band's controls are behind a
      // visible control at Tier C, or open as the full-width modal drawer.
      const filters = workspace.querySelector('.toolbar-band__controls');
      if (filters && filters.querySelector('input, select')) {
        evaluated.add('tier.c-composition');
        if (modal(filters)) {
          if (!fullWidth(filters)) fail('tier.c-composition', 'the open Ledger filter drawer is ' + Math.round(box(filters).width) + 'px, not the full width (§20 Tier C)');
        } else if (visible(filters)) {
          fail('tier.c-composition', 'the Ledger filters are in the band at Tier C; §25 moves them into a drawer');
        } else if (!opener(filters)) {
          fail('tier.c-composition', 'the Ledger filters are in a drawer with no visible control to open it');
        }
      }
    }
    if (archetype === 'workspace--ledger-summary') {
      // "Attention list only, then counts."
      evaluated.add('tier.c-composition');
      const attention = workspace.querySelector('.attention');
      const counts = workspace.querySelector('.summary-band');
      const others = Array.from(workspace.querySelectorAll('.panel')).filter((panel) => visible(panel) && !panel.matches('.attention') && !(attention && attention.contains(panel)));
      if (others.length) fail('tier.c-composition', 'the Overview draws ' + others.length + ' panel(s) besides the attention list at Tier C: ' + others.map((p) => (p.querySelector('.panel__title') || p).textContent.trim().slice(0, 24)).join(', '));
      if (attention && counts && visible(attention) && visible(counts) && box(counts).top < box(attention).bottom - 1) {
        fail('tier.c-composition', 'the Overview counts come before the attention list at Tier C');
      }
    }
    if (archetype === 'workspace--record') {
      const primary = workspace.querySelector('.workspace__record-primary');
      const facts = workspace.querySelector('.workspace__record-facts');
      if (primary && facts && visible(primary) && visible(facts)) {
        evaluated.add('tier.c-composition');
        // §4.2: the facts rail stacks above the primary when it carries the
        // record's identity — stated per surface here, not read from the page.
        const FACTS_FIRST = { 'processing-detail': true };
        const factsFirst = Boolean(FACTS_FIRST[input.surface]);
        const stackedBelow = box(facts).top >= box(primary).bottom - 1;
        const stackedAbove = box(primary).top >= box(facts).bottom - 1;
        if (!stackedBelow && !stackedAbove) fail('tier.c-composition', 'the Record facts rail is beside the primary column at Tier C, not stacked');
        else if (factsFirst && !stackedAbove) fail('tier.c-composition', 'the Record facts rail carries the identity but is below the primary column (§4.2 Tier C: above)');
        else if (!factsFirst && !stackedBelow) fail('tier.c-composition', 'the Record facts rail is above the primary column, though it does not carry the identity');
        // Reading and focus order are the order shown.
        const domFactsFirst = Boolean(facts.compareDocumentPosition(primary) & Node.DOCUMENT_POSITION_FOLLOWING);
        if (domFactsFirst !== stackedAbove) fail('tier.c-composition', 'the Record regions are shown in a different order from the one they are read in');
      }
    }
    if (archetype === 'workspace--investigation') {
      const results = workspace.querySelector('.workspace__results');
      if (results) {
        evaluated.add('tier.c-composition');
        const grid = Array.from(document.querySelectorAll('button, [role="radio"]')).find((el) => /Grid view/.test(el.getAttribute('aria-label') || el.textContent || '') && visible(el));
        if (grid) fail('tier.c-composition', 'grid view is offered at Tier C (§25: unavailable)');
        if (workspace.querySelector('.track-grid')) fail('tier.c-composition', 'the results are drawn as the grid at Tier C');
        if (box(results).width < working - 1) fail('tier.c-composition', 'the results are ' + round(box(results).width) + 'px of a ' + round(working) + 'px working width at Tier C');
        for (const [name, el] of [['filter rail', workspace.querySelector('.workspace__rail')], ['inspector', workspace.querySelector('.workspace__inspector')]]) {
          if (!el || !visible(el)) continue;
          if (!modal(el)) fail('tier.c-composition', 'the Investigation ' + name + ' is in flow at Tier C; §25 makes it a drawer');
          else if (!fullWidth(el)) fail('tier.c-composition', 'the Investigation ' + name + ' drawer is ' + Math.round(box(el).width) + 'px, not the full width (§20 Tier C)');
        }
      }
    }
    if (archetype === 'workspace--review') {
      const player = workspace.querySelector('.workspace__player');
      if (player && visible(player)) {
        evaluated.add('tier.c-composition');
        // "Player full width, then the summary, then provenance; transport
        // keeps every control at ≥24px effective target."
        if (box(player).width < working - 1) fail('tier.c-composition', 'the Evidence Player is ' + round(box(player).width) + 'px of a ' + round(working) + 'px working width at Tier C');
        if (getComputedStyle(player).position === 'sticky') fail('tier.c-composition', 'the Evidence Player is still sticky at Tier C');
        const panel = (title) => Array.from(workspace.querySelectorAll('.panel')).find((p) => visible(p) && (p.querySelector('.panel__title') || {}).textContent?.trim() === title);
        const summary = panel('Track summary');
        const provenance = panel('Processing provenance');
        if (summary && box(summary).top < box(player).bottom - 1) fail('tier.c-composition', 'the Track summary is not below the Evidence Player at Tier C');
        if (summary && provenance && box(provenance).top < box(summary).bottom - 1) fail('tier.c-composition', 'provenance comes before the Track summary at Tier C');
        const small = Array.from(player.querySelectorAll('button, select, input')).filter((el) => visible(el) && (box(el).width < 23.5 || box(el).height < 23.5));
        if (small.length) fail('tier.c-composition', small.length + ' Evidence Player control(s) under the 24px effective target at Tier C: ' + small.slice(0, 3).map((el) => (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 16)).join(', '));
      }
    }
  }

  // --- Tier B compositions (§25): each archetype's designed transition ------
  //     at the stacking threshold, judged from where the regions render.
  if (input.tier === 'B') {
    const vw = doc.clientWidth;
    const stacked = vw <= 1100;
    const box = (el) => el.getBoundingClientRect();
    const below = (lower, upper) => box(lower).top >= box(upper).bottom - 1;
    const beside = (right, left) => box(right).left >= box(left).right - 1 && Math.abs(box(right).top - box(left).top) <= 1;
    const visible = (el) => el && getComputedStyle(el).display !== 'none' && box(el).width > 0;
    const modal = (el) => el && el.getAttribute('role') === 'dialog' && el.getAttribute('aria-modal') === 'true';
    if (archetype === 'workspace--workbench') {
      const stage = workspace.querySelector('.workspace__stage');
      const inspector = workspace.querySelector('.workspace__inspector');
      if (stage && inspector) {
        evaluated.add('tier.b-composition');
        if (stacked && !below(inspector, stage)) fail('tier.b-composition', 'the Workbench is not stacked at ' + vw + 'px: §25 puts the stage first and the inspector below at 768-1100');
        // 1101-1149: the frozen drawer band — never an in-flow column beside
        // the stage. 1150-1365: side by side (the floor holds there under the
        // Tier B shell; workbench.geometry judges the floor itself).
        const band = !stacked && vw < 1150;
        if (band && visible(inspector) && !modal(inspector) && beside(inspector, stage)) {
          fail('tier.b-composition', 'the Workbench inspector is a column beside the stage at ' + vw + 'px, inside the frozen 1101-1149 drawer band (§25)');
        }
        if (!stacked && !band && !beside(inspector, stage)) {
          fail('tier.b-composition', 'the Workbench inspector is not beside the stage at ' + vw + 'px (§25: side by side from 1150)');
        }
      }
    }
    if (archetype === 'workspace--investigation') {
      const rail = workspace.querySelector('.workspace__rail');
      const results = workspace.querySelector('.workspace__results');
      if (rail && results) {
        evaluated.add('tier.b-composition');
        if (stacked) {
          // The filters are a drawer opened from the results header.
          if (visible(rail) && !modal(rail)) fail('tier.b-composition', 'the Investigation filter rail is in flow at ' + vw + 'px; §25 makes it a drawer at 768-1100');
          if (!visible(rail) && !results.querySelector('.workspace__rail-toggle')) fail('tier.b-composition', 'the closed filter drawer has no control in the results header to open it');
          if (box(results).width < working - 1) fail('tier.b-composition', 'the results are ' + round(box(results).width) + 'px of a ' + round(working) + 'px working width; stacked, they take it all');
        } else if (modal(rail) || !visible(rail)) {
          fail('tier.b-composition', 'the Investigation filter rail is not in place at ' + vw + 'px; §25 keeps it beside the results down to 1101');
        }
      }
    }
    if (archetype === 'workspace--record') {
      const primary = workspace.querySelector('.workspace__record-primary');
      const facts = workspace.querySelector('.workspace__record-facts');
      if (primary && facts) {
        evaluated.add('tier.b-composition');
        measured.factsWidth = round(box(facts).width);
        if (stacked && !below(facts, primary)) fail('tier.b-composition', 'the Record facts rail is not stacked below the primary column at ' + vw + 'px (§25)');
        if (!stacked) {
          if (!beside(facts, primary)) fail('tier.b-composition', 'the Record facts rail is not beside the primary column at ' + vw + 'px (§25: the composition is fluid down to 1101)');
          else if (box(facts).width < 279.5) fail('tier.b-composition', 'the Record facts rail is ' + measured.factsWidth + 'px, below its 280px minimum (§25)');
        }
      }
    }
    if (archetype === 'workspace--review') {
      const main = workspace.querySelector('.workspace__review-main');
      const rail = workspace.querySelector('.workspace__review-rail');
      if (main && rail) {
        evaluated.add('tier.b-composition');
        if (stacked && !below(rail, main)) fail('tier.b-composition', 'the Review rail is not stacked below the player at ' + vw + 'px (§25)');
        if (!stacked && !beside(rail, main)) fail('tier.b-composition', 'the Review rail is not beside the player at ' + vw + 'px (§25: the composition is fluid down to 1101)');
      }
    }
  }

  return { findings, evaluated: Array.from(evaluated), measured };
}

/**
 * Focus visibility, by actually focusing every practical control. Every
 * focusable element is checked or skipped for a named reason, and the run
 * fails coverage that does not add up. Focus is then left on the first
 * checked control, so each capture carries one real ring for the human pass.
 */
export function focusAssertions() {
  const findings = [];
  const skipped = {};
  const skip = (reason) => { skipped[reason] = (skipped[reason] || 0) + 1; };
  const candidates = Array.from(document.querySelectorAll(
    'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]',
  ));
  // Focusing a control scrolls it into view. The pass must not leave the page
  // scrolled to wherever its last control was — the capture, and the
  // rendered-stickiness measurement after it, are of the state as reached —
  // so every scroll position is put back afterwards.
  const scrolled = [document.scrollingElement, ...document.querySelectorAll('*')]
    .filter((el) => el && (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth))
    .map((el) => [el, el.scrollTop, el.scrollLeft]);
  // Focus too is put back: the state as reached may hold it inside an open
  // overlay, and leaving it on the pass's first control — the skip link,
  // outside every overlay — would change what Escape and the capture see.
  const before = document.activeElement;
  let checked = 0;
  for (const el of candidates) {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') { skip('disabled'); continue; }
    if (el.closest('[inert]')) { skip('inside an inert subtree'); continue; }
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (rect.width === 0 || rect.height === 0) { skip('zero-sized'); continue; }
    if (style.visibility === 'hidden' || style.display === 'none') { skip('not visible'); continue; }
    if (rect.width <= 1 && rect.height <= 1) { skip('visually hidden'); continue; }
    el.focus();
    if (document.activeElement !== el) { skip('refused focus'); continue; }
    checked += 1;
    const focused = getComputedStyle(el);
    const ring = focused.outlineStyle !== 'none' && parseFloat(focused.outlineWidth) > 0;
    const shadow = focused.boxShadow && focused.boxShadow !== 'none';
    if (!ring && !shadow) {
      findings.push({
        rule: 'a11y.focus-visible',
        message: 'no visible focus on <' + el.tagName.toLowerCase() + '> "'
          + (el.textContent || el.getAttribute('aria-label') || el.getAttribute('name') || '').trim().slice(0, 32) + '"',
      });
    }
  }
  if (before instanceof HTMLElement && before !== document.body && before.isConnected) before.focus({ preventScroll: true });
  else if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  for (const [el, top, left] of scrolled) { el.scrollTop = top; el.scrollLeft = left; }
  return { findings, evaluated: checked ? ['a11y.focus-visible'] : [], discovered: candidates.length, checked, skipped };
}

/**
 * Rendered stickiness (§4.5.1; R6 owns the fix, this is the measurement).
 * The computed `position: sticky` says nothing about whether the player stays
 * on screen: scroll the page by what it can scroll, and look again.
 */
export async function stickyProbe() {
  const player = document.querySelector('.workspace--review .workspace__player');
  const scroller = document.querySelector('.main');
  if (!player || !scroller) return { evaluated: false, why: 'no Review player' };
  if (document.documentElement.clientWidth <= 1100) return { evaluated: false, why: 'stacked Review: §4.5.1 releases the pin' };
  const distance = Math.min(600, scroller.scrollHeight - scroller.clientHeight);
  if (distance < 40) return { evaluated: false, why: 'the page has nothing to scroll' };
  const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const start = scroller.scrollTop;
  const before = player.getBoundingClientRect();
  scroller.scrollTop = start + distance;
  await frame();
  const after = player.getBoundingClientRect();
  const viewport = scroller.getBoundingClientRect();
  const visible = Math.max(0, Math.min(after.bottom, viewport.bottom) - Math.max(after.top, viewport.top));
  // Pinned clear of the Context Bar. Review's bar is in the shell's band above
  // the scroller, but a bar inside it would be sticky over the same pixels: a
  // player at that position is on screen and still hidden.
  const bar = document.querySelector('.context-bar');
  const barBottom = bar ? bar.getBoundingClientRect().bottom : viewport.top;
  const underBar = Math.max(0, Math.round(barBottom - after.top));
  // Release at the end of the column is not measured here: sticky positioning
  // cannot carry the player past its containing block, and that the player is
  // sticky (not fixed) is review.sticky-declared's assertion.
  scroller.scrollTop = start;
  await frame();
  const fraction = after.height > 0 ? visible / after.height : 0;
  return {
    evaluated: true,
    scrolled: distance,
    topBefore: Math.round(before.top),
    topAfter: Math.round(after.top),
    visibleFraction: Math.round(fraction * 100) / 100,
    underBar,
    pinned: fraction >= 0.5,
  };
}

/**
 * Is the evidence overlay genuinely on screen, over a decoded frame? A capture
 * taken before the media decoded validates nothing while looking like a pass.
 */
export function overlayReady() {
  const video = document.querySelector('.evidence-player__video');
  if (!video) return { ok: false, why: 'no player video element' };
  if (video.readyState < 2) return { ok: false, why: 'media not decoded (readyState ' + video.readyState + ')' };
  if (!(video.videoWidth > 0)) return { ok: false, why: 'media reports no frame size' };
  if (!(video.currentTime > 0)) return { ok: false, why: 'player never left the first frame' };
  const marks = Array.from(document.querySelectorAll('.evidence-player__stage rect, .evidence-player__stage polyline'));
  const drawn = marks.filter((m) => { const r = m.getBoundingClientRect(); return r.width > 1 && r.height > 1; });
  if (drawn.length === 0) return { ok: false, why: 'no overlay geometry drawn at this frame' };
  const overlay = document.querySelector('.evidence-player__stage');
  const filter = overlay ? getComputedStyle(overlay).filter : 'none';
  if (!filter || filter === 'none') return { ok: false, why: 'overlay layer carries no halo' };
  return { ok: true, why: '', drawn: drawn.length };
}

/**
 * The open modal overlay the Escape probe will close, remembered on the page,
 * and the rule its exit is judged under; null when none is open.
 */
export function overlayOpened() {
  const modal = document.querySelector('[role="dialog"][aria-modal="true"]');
  window.__vqaModal = modal;
  return modal ? (modal.classList.contains('dialog') ? 'overlay.dialog' : 'overlay.drawer') : null;
}

/**
 * Where focus is after a real key press inside an open overlay (§15, §20, §23:
 * Tab and Shift+Tab stay inside the topmost modal). Read a frame after the key,
 * so the browser's own focus navigation has happened.
 */
export async function overlayFocusProbe() {
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  const modals = Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).filter((m) => !m.closest('[inert]'));
  const modal = modals[modals.length - 1] ?? null;
  const active = document.activeElement;
  const name = (el) => {
    if (!el || !el.tagName) return null;
    const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '';
    const label = (el.getAttribute('aria-label') || el.textContent || '').trim();
    return el.tagName.toLowerCase() + cls + (label ? ' "' + label.slice(0, 40) + '"' : '');
  };
  return { open: Boolean(modal), inside: Boolean(modal && active && modal.contains(active)), documentFocused: document.hasFocus(), focus: name(active) };
}

/**
 * After Escape (§15, §20): did the overlay close, and did focus go back to the
 * control that opened it — the invoker the observers recorded as focus first
 * entered this overlay — with nothing left inert?
 */
export async function overlayExitProbe() {
  const end = performance.now() + 3000;
  const open = () => document.querySelector('[role="dialog"][aria-modal="true"]');
  while (open() && performance.now() < end) await new Promise((resolve) => requestAnimationFrame(() => resolve()));
  const name = (el) => {
    if (!el || !el.tagName) return null;
    const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '';
    const label = (el.getAttribute('aria-label') || el.textContent || '').trim();
    return el.tagName.toLowerCase() + cls + (label ? ' "' + label.slice(0, 40) + '"' : '');
  };
  const vqa = window.__vqa;
  const invoker = vqa && window.__vqaModal && vqa.invokerFor === window.__vqaModal ? vqa.invoker : null;
  const active = document.activeElement;
  return {
    closed: !open(),
    focus: name(active),
    invoker: name(invoker),
    restored: Boolean(invoker && invoker.isConnected && active === invoker),
    inertLeft: document.querySelectorAll('[inert]').length,
  };
}

// --- T3: 200% browser page zoom (§23, §25) -------------------------------------

/**
 * The page's own account of the zoom it is laid out at (T3): the CSS viewport,
 * devicePixelRatio, the visual viewport (pinch scale), the tier media queries
 * and the text sizes, so the harness can show that the page — not only the
 * browser — is at the zoom the case claims (engine.zoomQualification).
 */
export function zoomEnvironment() {
  // The same piece of Context Bar text at every step of a zoom change, so its
  // size is compared with itself (the band recomposes across the tiers).
  const bar = document.querySelector('.context-bar');
  const kept = window.__vqaZoomText;
  const text = kept && kept.isConnected ? kept
    : bar && Array.from(bar.querySelectorAll('*')).find((el) => Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim()) && el.getBoundingClientRect().width > 1);
  window.__vqaZoomText = text ?? null;
  return {
    innerWidth, innerHeight,
    clientWidth: document.documentElement.clientWidth, clientHeight: document.documentElement.clientHeight,
    dpr: window.devicePixelRatio,
    visual: { width: visualViewport.width, height: visualViewport.height, scale: visualViewport.scale },
    media: { narrow: matchMedia('(width < 768px)').matches, compact: matchMedia('(width < 1366px)').matches },
    rootFontPx: parseFloat(getComputedStyle(document.documentElement).fontSize),
    bodyFontPx: parseFloat(getComputedStyle(document.body).fontSize),
    barTextPx: text ? parseFloat(getComputedStyle(text).fontSize) : null,
  };
}

/**
 * What 200% zoom adds to the Tier C rules (T3, §23 "no lost control", §25).
 * A Tier C composition proven at 390x844 can still lose a control to the
 * 384px height of a zoomed 1366x768 display, so on a zoom capture:
 *
 * - every offered control (visible, enabled, outside an inert region) can be
 *   brought into view, and is then on screen, not clipped by a box that does
 *   not scroll, and not covered by anything else — focus is never obscured
 *   (WCAG 2.4.11) — and no box that clips had to be scrolled by focus to show
 *   it (a pointer cannot scroll such a box);
 * - an open drawer or dialog fits the viewport;
 * - text grows with the page: no font size is set in viewport units, directly
 *   or through a custom property;
 * - visually truncated text keeps its full value within the keyboard's reach
 *   (§16): it is the text of a link or button that leads to the row's detail
 *   or inspector — the full-value home — or, focusable on its own, focus
 *   describes it with its full value (the Tooltip's aria-describedby);
 * - the Evidence Player is not drawn distorted (an object-fit that stretches
 *   it into a box of another aspect ratio).
 *
 * It also records whether the capture is a Workbench's §25 unsupported
 * state — at 200% that is §23's documented WCAG 1.4.4 exception, reported as
 * such, never passed silently.
 *
 * Focus and every scroll position are put back afterwards, as the focus pass
 * does, so the capture and the probes after it see the state as reached.
 */
export function zoomAssertions(input) {
  const findings = [];
  const fail = (message) => findings.push({ rule: 'a11y.zoom-200', message });
  const describe = (el) => {
    if (!el || !el.tagName) return String(el);
    const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '';
    const label = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ');
    return '<' + el.tagName.toLowerCase() + cls + '>' + (label ? ' "' + label.slice(0, 40) + '"' : '');
  };
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;

  // Text grows with the page (WCAG 1.4.4): a font sized in viewport units does
  // not — the CSS viewport halves as the zoom doubles.
  // A custom property carries viewport units as well as a declaration does
  // (`--title: 3vw; font-size: var(--title)`), so those are found first, to a
  // fixed point through properties that refer to them.
  const VIEWPORT_UNITS = /(?:^|[\s(,*/+-])-?(?:\d*\.)?\d+(?:[sld]?v(?:w|h|i|b|min|max))\b/;
  const styleRules = [];
  const collect = (list) => {
    for (const rule of Array.from(list ?? [])) {
      if (rule.style) styleRules.push({ style: rule.style, where: '"' + rule.selectorText + '"' });
      if (rule.cssRules) collect(rule.cssRules);
    }
  };
  for (const sheet of Array.from(document.styleSheets)) {
    try { collect(sheet.cssRules); } catch { /* a cross-origin sheet: the product has none */ }
  }
  for (const el of Array.from(document.querySelectorAll('[style]'))) styleRules.push({ style: el.style, where: describe(el) + ' (inline)' });
  const customs = [];
  for (const { style } of styleRules) {
    for (let i = 0; i < style.length; i += 1) if (style[i].startsWith('--')) customs.push([style[i], style.getPropertyValue(style[i])]);
  }
  const viewportProps = new Set();
  const refersTo = (value) => Array.from(viewportProps).some((name) => value.includes('var(' + name + ')') || value.includes('var(' + name + ',') || new RegExp('var\\(\\s*' + name + '\\s*[,)]').test(value));
  for (let grew = true; grew;) {
    grew = false;
    for (const [name, value] of customs) {
      if (!viewportProps.has(name) && (VIEWPORT_UNITS.test(value) || refersTo(value))) { viewportProps.add(name); grew = true; }
    }
  }
  for (const { style, where } of styleRules) {
    const size = (style.getPropertyValue('font-size') + ' ' + style.getPropertyValue('font')).trim();
    if (size && (VIEWPORT_UNITS.test(size) || refersTo(size))) fail(where + ' sets its font size in viewport units (' + size + '): its text does not grow with page zoom');
  }
  const rulesRead = styleRules.length;

  // Drawers and dialogs fit the effective viewport.
  const modals = Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).filter((m) => !m.closest('[inert]'));
  for (const modal of modals) {
    const r = modal.getBoundingClientRect();
    if (r.left < -1 || r.top < -1 || r.right > vw + 1 || r.bottom > vh + 1) {
      fail(describe(modal) + ' is ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' at (' + Math.round(r.left) + ', ' + Math.round(r.top) + ') and does not fit the ' + vw + 'x' + vh + ' viewport');
    }
  }

  // Every offered control is reachable, on screen, unclipped and unobscured.
  const clips = (style) => style.overflowX !== 'visible' || style.overflowY !== 'visible';
  const scrollsByUser = (style) => /^(auto|scroll)$/.test(style.overflowX) || /^(auto|scroll)$/.test(style.overflowY);
  const scrolled = [document.scrollingElement, ...document.querySelectorAll('*')]
    .filter((el) => el && (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth))
    .map((el) => [el, el.scrollTop, el.scrollLeft]);
  const before = document.activeElement;
  // The page itself is a box that clips without scrolling when the root (or
  // the body, propagated to the viewport) hides its overflow.
  const rootStyle = getComputedStyle(document.documentElement);
  const viewportStyle = rootStyle.overflowX === 'visible' && rootStyle.overflowY === 'visible' ? getComputedStyle(document.body) : rootStyle;
  const pageScrolls = { x: !/^(hidden|clip)$/.test(viewportStyle.overflowX), y: !/^(hidden|clip)$/.test(viewportStyle.overflowY) };
  const root = document.scrollingElement || document.documentElement;
  // What paints at a point, under every layer — one that lets the pointer
  // through (pointer-events: none) still hides what is under it.
  const reveal = document.createElement('style');
  reveal.textContent = '*, *::before, *::after { pointer-events: auto !important; }';
  const opaque = (color) => {
    const m = /rgba?\(([^)]+)\)/.exec(color || '');
    if (!m) return Boolean(color) && color !== 'transparent';
    const parts = m[1].split(/[,\s/]+/).filter(Boolean);
    return parts.length < 4 || parseFloat(parts[3]) > 0.05;
  };
  const paints = (node) => {
    if (/^(IMG|VIDEO|CANVAS|IFRAME|SVG|INPUT|SELECT|TEXTAREA|BUTTON)$/i.test(node.tagName)) return true;
    for (const pseudo of [null, '::before', '::after']) {
      const s = getComputedStyle(node, pseudo);
      if (pseudo && (s.content === 'none' || s.content === 'normal')) continue;
      if (s.visibility === 'hidden' || parseFloat(s.opacity) < 0.05) continue;
      if (opaque(s.backgroundColor) || s.backgroundImage !== 'none') return true;
    }
    return Array.from(node.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
  };
  const candidates = Array.from(document.querySelectorAll(
    'button, a[href], input, select, textarea, summary, video[controls], [tabindex]:not([tabindex="-1"]), [contenteditable="true"]',
  ));
  let checked = 0;
  for (const el of candidates) {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.closest('[inert]')) continue;
    if (el.type === 'hidden' || !el.getClientRects().length) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden') continue;
    const r0 = el.getBoundingClientRect();
    if (r0.width <= 1 && r0.height <= 1) continue; // visually hidden until focused (the skip link)
    // The boxes between the control and the page that clip it, with where
    // each stood before focus moved it.
    const boxes = [];
    let hiddenIn = null;
    for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (clips(s)) boxes.push({ el: a, user: scrollsByUser(s), top: a.scrollTop, left: a.scrollLeft });
      const ar = a.getBoundingClientRect();
      if (!hiddenIn && (clips(s) || s.clipPath !== 'none') && ar.width <= 1 && ar.height <= 1) hiddenIn = a;
      if (s.position === 'fixed') break;
    }
    // A control inside a visually-hidden region is offered only if the
    // keyboard can reach it (then it must show when focused, judged below); one
    // taken out of the tab order there — the Tier C Ledger's hidden header
    // sort buttons (T2) — is not offered at all.
    if (hiddenIn && el.tabIndex < 0) continue;
    const rootAt = { top: root.scrollTop, left: root.scrollLeft };
    el.focus({ focusVisible: false });
    if (document.activeElement !== el) continue;
    checked += 1;
    const forced = boxes.find((b) => !b.user && (Math.abs(b.el.scrollTop - b.top) > 0.5 || Math.abs(b.el.scrollLeft - b.left) > 0.5));
    if (forced) fail(describe(el) + ' is shown only by focus scrolling ' + describe(forced.el) + ', which clips without scrolling: a pointer cannot reach it');
    else if ((!pageScrolls.y && Math.abs(root.scrollTop - rootAt.top) > 0.5) || (!pageScrolls.x && Math.abs(root.scrollLeft - rootAt.left) > 0.5)) {
      fail(describe(el) + ' is shown only by focus scrolling the page, which hides its overflow: a pointer cannot reach it');
    }
    // The part of the control on screen once focus has brought it into view.
    const r = el.getBoundingClientRect();
    let left = Math.max(r.left, 0); let top = Math.max(r.top, 0);
    let right = Math.min(r.right, vw); let bottom = Math.min(r.bottom, vh);
    let clipper = null;
    for (const b of boxes) {
      const c = b.el.getBoundingClientRect();
      const nl = Math.max(left, c.left + b.el.clientLeft); const nt = Math.max(top, c.top + b.el.clientTop);
      const nr = Math.min(right, c.left + b.el.clientLeft + b.el.clientWidth); const nb = Math.min(bottom, c.top + b.el.clientTop + b.el.clientHeight);
      if (!clipper && Math.max(0, nr - nl) * Math.max(0, nb - nt) < Math.max(0, right - left) * Math.max(0, bottom - top) - 1) clipper = b.el;
      left = nl; top = nt; right = nr; bottom = nb;
    }
    const shown = Math.max(0, right - left) * Math.max(0, bottom - top);
    const area = Math.max(1, Math.min(r.width, vw) * Math.min(r.height, vh));
    if (shown < 1) {
      fail(describe(el) + ' cannot be brought into the ' + vw + 'x' + vh + ' view: focused, it is at (' + Math.round(r.left) + ', ' + Math.round(r.top) + ')' + (clipper ? ', cut off by ' + describe(clipper) : ''));
      continue;
    }
    if (shown < area * 0.5) fail(describe(el) + ' is ' + Math.round((1 - shown / area) * 100) + '% cut off even when focused' + (clipper ? ', by ' + describe(clipper) : ' by the viewport'));
    // What is drawn at the middle of the part on screen. What a pointer hits
    // there must be the control (or its label, or its own tooltip). And a
    // layer the pointer passes through (pointer-events: none) still hides it
    // when it paints and floats over the page — fixed or sticky, or an
    // ancestor's positioned ::before/::after (elementsFromPoint reports that
    // layer as the ancestor). A pass-through face drawn over a transparent
    // control in the same composition (a grid card's evidence over its
    // stretched select button) is the control's face, not a cover.
    const own = (node) => node === el || el.contains(node) || (el.labels && Array.from(el.labels).some((label) => label.contains(node))) || Boolean(node.closest('.tooltip, [role="tooltip"]'));
    const x = (left + right) / 2; const y = (top + bottom) / 2;
    const hit = document.elementFromPoint(x, y);
    if (!hit || !own(hit)) {
      fail(describe(el) + ' is covered by ' + describe(hit) + ' when focused');
      continue;
    }
    const floats = (node) => {
      for (let n = node; n && n !== document.documentElement; n = n.parentElement) {
        if (n.contains(el)) return false;
        if (/^(fixed|sticky)$/.test(getComputedStyle(n).position)) return true;
      }
      return false;
    };
    const pseudoLayer = (node) => node !== el && node.contains(el) && ['::before', '::after'].some((pseudo) => {
      const s = getComputedStyle(node, pseudo);
      return s.content !== 'none' && s.content !== 'normal' && /^(absolute|fixed)$/.test(s.position);
    });
    document.head.appendChild(reveal);
    const stack = document.elementsFromPoint(x, y);
    reveal.remove();
    const layer = stack.find((node) => own(node) || ((floats(node) || pseudoLayer(node)) && paints(node)));
    if (layer && !own(layer)) fail(describe(el) + ' is hidden under ' + describe(layer) + ' when focused (a layer the pointer passes through still covers it)');
  }
  if (before instanceof HTMLElement && before !== document.body && before.isConnected) before.focus({ preventScroll: true });
  else if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  for (const [el, top, left] of scrolled) { el.scrollTop = top; el.scrollLeft = left; }

  // Focus order follows the visual order (§23 "tab order follows reading
  // order"): a control the keyboard reaches later is never drawn before an
  // earlier one on the same line. Judged in the Context Bar — the one-row
  // band a live zoom change recomposes (the menu control it adds must lead it
  // in the document, not only on screen) — and, in the single-column Tier C
  // composition, among the controls of the open overlay or, with none open,
  // the workspace (side by side, at Tier A, a column is read before the next).
  const inOrder = (scope, label) => {
    if (!scope) return;
    const controls = Array.from(scope.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])'))
      .filter((el) => !el.disabled && el.tabIndex >= 0 && !el.closest('[inert]') && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.width > 1 && r.height > 1);
    for (let i = 1; i < controls.length; i += 1) {
      const a = controls[i - 1]; const b = controls[i];
      const sameLine = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top) > Math.min(a.r.height, b.r.height) / 2;
      if (sameLine && b.r.right <= a.r.left + 1) {
        fail('in ' + label + ' the keyboard reaches ' + describe(b.el) + ' after ' + describe(a.el) + ', but it is drawn before it on the same line: focus order is not the visual order');
        return;
      }
    }
  };
  inOrder(document.querySelector('.context-bar'), 'the Context Bar');
  if (input?.tier === 'C') {
    const topModal = modals[modals.length - 1];
    inOrder(topModal ?? document.querySelector('main .workspace, main .page'), topModal ? 'the open overlay' : 'the workspace');
  }

  // Truncated text keeps its full value within reach of the keyboard (§16).
  let truncated = 0;
  for (const el of Array.from(document.querySelectorAll('body *'))) {
    if (el.closest('[inert], [aria-hidden="true"], svg')) continue;
    const s = getComputedStyle(el);
    if (s.textOverflow !== 'ellipsis' || el.scrollWidth <= el.clientWidth + 1 || !el.getClientRects().length) continue;
    truncated += 1;
    const full = el.textContent.trim().replace(/\s+/g, ' ');
    const focusable = el.closest('a[href], button, summary, select, input, textarea, [tabindex]:not([tabindex="-1"])');
    // §16: a link or button leads to the row's detail or inspector, where the
    // full value lives. Text focusable only to be read (TruncatedText) must
    // say the whole of it on focus: the Tooltip describes its anchor
    // (aria-describedby) with the full value and shows it then.
    const leads = Boolean(focusable) && /^(A|BUTTON|SUMMARY)$/.test(focusable.tagName);
    // Compared by its letters and digits: the drawn value may set a code apart
    // from a name that the tooltip joins with a separator ("CAM-02 · North").
    const letters = (text) => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
    const described = Boolean(focusable) && [focusable, el].some((node) => (node.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean)
      .some((id) => letters(document.getElementById(id)?.textContent || '').includes(letters(full))));
    if (!focusable) fail('truncated text "' + full.slice(0, 40) + '" in ' + describe(el) + ' cannot be focused to show its full value');
    else if (!leads && !described) fail('truncated text "' + full.slice(0, 40) + '" in ' + describe(el) + ' can be focused, but focus does not show its full value');
  }

  // The Evidence Player keeps its footage's aspect ratio.
  const video = document.querySelector('.evidence-player__video');
  if (video && video.videoWidth > 0 && video.videoHeight > 0) {
    const r = video.getBoundingClientRect();
    const fit = getComputedStyle(video).objectFit;
    const box = r.width / Math.max(1, r.height);
    const source = video.videoWidth / video.videoHeight;
    if (!/^(contain|scale-down|none)$/.test(fit) && Math.abs(box / source - 1) > 0.02) {
      fail('the Evidence Player draws ' + video.videoWidth + 'x' + video.videoHeight + ' footage in a ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' box with object-fit ' + fit + ': the picture is distorted');
    }
  }
  // §23's documented exception, reported where it applies: a Workbench at
  // 200% is its §25 unsupported state (Scene editing; Camera Analytics'
  // chart, heatmap and figures), with the statement it gives.
  const unsupported = document.querySelector('.workspace--unsupported');
  const exception = unsupported ? (unsupported.querySelector('.workspace__unsupported-statement')?.textContent || unsupported.textContent || '').trim().slice(0, 200) : null;
  return { findings, evaluated: ['a11y.zoom-200'], measured: { controls: checked, modals: modals.length, truncated, cssRulesRead: rulesRead, workbenchException: exception } };
}

/** Before a live zoom change: remember where focus is (T3). */
export function zoomBeforeChange() {
  window.__vqaZoomFocus = document.activeElement;
  const a = document.activeElement;
  if (!a || a === document.body) return null;
  const label = (a.getAttribute('aria-label') || a.textContent || '').trim().replace(/\s+/g, ' ');
  return '<' + a.tagName.toLowerCase() + '>' + (label ? ' "' + label.slice(0, 40) + '"' : '');
}

/**
 * After a live zoom change (T3, §20, §23): focus is not lost to the document
 * and not left on anything hidden or inert; an overlay still open holds it;
 * and nothing is left inert with no overlay open.
 */
export async function zoomTransitionProbe() {
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  const findings = [];
  const fail = (message) => findings.push({ rule: 'a11y.zoom-200', message });
  const describe = (el) => {
    if (!el || !el.tagName) return 'nothing';
    const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '';
    const label = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ');
    return '<' + el.tagName.toLowerCase() + cls + '>' + (label ? ' "' + label.slice(0, 40) + '"' : '');
  };
  const before = window.__vqaZoomFocus;
  const active = document.activeElement;
  const lost = !active || active === document.body || active === document.documentElement;
  if (lost && before && before !== document.body && before !== document.documentElement) {
    fail('focus fell to the document when the zoom changed (it was on ' + describe(before) + ')');
  } else if (!lost) {
    const style = getComputedStyle(active);
    const r = active.getBoundingClientRect();
    const main = active === document.querySelector('main');
    if (!active.isConnected || !active.getClientRects().length || style.visibility === 'hidden' || (!main && r.width <= 1 && r.height <= 1)) {
      fail('focus is left on ' + describe(active) + ', which the new composition does not show');
    } else if (active.closest('[inert]')) {
      fail('focus is left on ' + describe(active) + ', inside an inert region');
    }
  }
  const modals = Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).filter((m) => !m.closest('[inert]'));
  const top = modals[modals.length - 1];
  if (top && !(active && top.contains(active))) fail(describe(top) + ' is still open after the zoom change, but focus is on ' + describe(active) + ', outside it');
  const inert = document.querySelectorAll('[inert]').length;
  if (!top && inert) fail(inert + ' region(s) are left inert after the zoom change with no overlay open');
  return { findings, focus: describe(active), modals: modals.length };
}
