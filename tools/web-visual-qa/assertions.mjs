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
    if (el.matches('button, a, input, select, textarea, img, video, canvas, svg, kbd, code, [role="alert"], [role="status"], .alert, .badge, .chip, .evidence-placeholder, .tooltip, .skip-link')) return false;
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
    if (rail && !shell.railCollapsed && shell.railWidth > 56) {
      fail('tier.b-shell', 'the rail is expanded (' + shell.railWidth + 'px) by default at Tier B; §25 collapses it');
    }
    if (!toggle || !shown(toggle)) fail('tier.b-shell', 'the rail collapse control is not visible at Tier B');
    else if (!(toggle.getAttribute('aria-label') || toggle.textContent || '').trim()) fail('tier.b-shell', 'the rail collapse control is unlabelled');
  }
  if (input.tier === 'C') {
    evaluated.add('tier.c-shell');
    const main = document.querySelector('main');
    if (main && main.getBoundingClientRect().width < doc.clientWidth - 1) {
      fail('tier.c-shell', 'the content is ' + Math.round(main.getBoundingClientRect().width) + 'px beside a '
        + (rail ? shell.railWidth : 0) + 'px rail column in a ' + doc.clientWidth + 'px viewport; §25 makes the rail a top-of-page menu');
    }
    if (input.archetype === 'workbench') {
      evaluated.add('tier.c-workbench-unsupported');
      const canvas = document.querySelector('.workspace__stage canvas, .workspace__stage svg, [data-testid="scene-canvas"]');
      if (canvas && shown(canvas)) fail('tier.c-workbench-unsupported', 'the editing canvas renders at Tier C; §25 requires the unsupported-state statement instead');
      if (!/768/.test(document.body.innerText)) fail('tier.c-workbench-unsupported', 'no statement that editing needs a display of at least 768px');
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
  // contain, overflowing content is simply unreachable.
  if (measured.shellScroll === 'contain' && column) {
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
    if (measured.shellScroll !== 'contain') {
      fail('ledger.scroll-ownership', 'the Ledger did not declare no-page-scroll to the shell: the content column is "' + measured.shellScroll + '"');
    }
    if (doc.clientWidth > 1100 && doc.scrollHeight > doc.clientHeight + 1) {
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

      const th = table.querySelector('thead th');
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
        // pass: a selector that matches nothing has checked nothing.
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
    if (doc.clientWidth >= 1150) {
      evaluated.add('workbench.geometry');
      evaluated.add('overlay.drawer');
      if (share < 0.65) fail('workbench.geometry', 'the stage is ' + measured.stageShare + '% of the working width, below the 65% floor');
      if (inspectorWidth < 299 || inspectorWidth > 361) fail('workbench.geometry', 'the inspector is ' + measured.inspectorWidth + 'px, outside the fixed 300-360 range');
      if (inspector.getAttribute('role') === 'dialog' || inspector.hasAttribute('aria-modal') || workspace.querySelector('[inert]')) {
        fail('overlay.drawer', 'the permanent Workbench inspector claims modality: only the 1101-1149 overlay is a drawer (§20)');
      }
    }
    const scrolledAncestors = [];
    for (let node = workspace.parentElement; node; node = node.parentElement) {
      if (!/(auto|scroll)/.test(getComputedStyle(node).overflowY)) continue;
      if (node.scrollHeight > node.clientHeight + 1) scrolledAncestors.push(named(node) + ' (' + node.scrollHeight + ' > ' + node.clientHeight + ')');
    }
    measured.scrolledAncestors = scrolledAncestors;
    if (doc.clientWidth >= 1150) {
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
    const summary = rail ? rail.querySelector('.panel') : null;
    if (!summary) {
      evaluated.add('review.composition');
      fail('review.composition', 'the Review is missing the primary evidence summary in its rail');
    } else if (doc.clientHeight <= 800) {
      evaluated.add('review.composition');
      const summaryBox = summary.getBoundingClientRect();
      measured.summaryTop = round(summaryBox.top);
      if (summaryBox.top >= doc.clientHeight) fail('review.composition', 'the primary evidence summary starts at ' + measured.summaryTop + 'px, below the ' + doc.clientHeight + 'px initial viewport (§4.5.1)');
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
