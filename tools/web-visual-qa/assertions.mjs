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

  /**
   * The overlay an element sits inside, if any.
   *
   * A drawer is *supposed* to cover what is behind it — §4.4's Investigation
   * inspector below its threshold, §4.3.1's Workbench inspector in its narrow
   * band — so a pair where exactly one side is inside a positioned overlay is
   * the archetype working, not a defect. Reporting those would have meant
   * either 40 findings per drawer state or a per-state exemption, and an
   * exemption cannot tell a drawer from a layout that genuinely collided.
   *
   * Two elements inside the *same* overlay are still compared with each other,
   * which is what keeps the drawer's own contents honest.
   */
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
    // One is inside an overlay the other is not inside: the overlay covers it.
    if (oa && !oa.contains(b)) return true;
    if (ob && !ob.contains(a)) return true;
    return false;
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
      if (deliberatelyLayered(a, b)) continue;
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
      if (deliberatelyLayered(a, b)) continue;
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

  // What the shell was told about this surface. The archetype declares it and
  // the shell applies it to the content column; reading it back here checks the
  // declaration actually arrived, rather than assuming it did.
  const column = workspace.closest('.main');
  measured.shellScroll = column ? column.getAttribute('data-scroll') : null;

  // Containment must not become clipping. With the column set to contain it
  // can no longer scroll, so content that overflows it is simply unreachable —
  // and, unlike a scrolling column, nothing about the page says so. This is the
  // check that keeps "the page does not scroll" from quietly becoming "the rest
  // of the page is gone".
  if (measured.shellScroll === 'contain' && column) {
    measured.columnOverflow = round(column.scrollHeight - column.clientHeight);
    if (column.scrollHeight > column.clientHeight + 1) {
      problems.push('content is clipped: the shell column is contained but its content is '
        + column.scrollHeight + 'px inside ' + column.clientHeight + 'px, so ' + measured.columnOverflow
        + 'px cannot be reached');
    }
    if (workspace.scrollHeight > workspace.clientHeight + 1) {
      problems.push('content is clipped: the workspace is ' + workspace.scrollHeight
        + 'px inside ' + workspace.clientHeight + 'px with no scroll owner for the difference');
    }
    // Sideways too, and this half is the one that bites. A contained column
    // clips horizontally without ever giving the document a horizontal
    // scrollbar, so a grid whose columns do not fit simply loses its right
    // edge — controls and all — and every other check here still passes. It is
    // how an Investigation at 1500px lost the inspector's Open and Close
    // buttons while reporting no page overflow at all.
    measured.columnOverflowX = round(column.scrollWidth - column.clientWidth);
    if (column.scrollWidth > column.clientWidth + 1) {
      problems.push('content is clipped sideways: the shell column is contained but its content is '
        + column.scrollWidth + 'px inside ' + column.clientWidth + 'px, so ' + measured.columnOverflowX
        + 'px is off the right edge with no way to reach it');
    }
    if (workspace.scrollWidth > workspace.clientWidth + 1) {
      problems.push('content is clipped sideways: the workspace is ' + workspace.scrollWidth
        + 'px inside ' + workspace.clientWidth + 'px with no scroll owner for the difference');
    }
  }

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

  // --- Ledger and Record (UI-3) -----------------------------------------
  //
  // The rules a rendered page settles that a unit test cannot: which element
  // actually owns the scroll, whether the sticky header sticks to that element,
  // and whether a full-width workspace stretched a sparse table across the
  // display.
  if (archetype === 'workspace--ledger' || archetype === 'workspace--ledger-summary') {
    const body = workspace.querySelector('.workspace__body--scroll');
    if (!body) {
      problems.push('Ledger is missing its scrolling body region');
      return { problems, measured };
    }

    // §4.1: the table body owns vertical scroll and the page does not.
    if (measured.shellScroll !== 'contain') {
      problems.push('Ledger did not declare no-page-scroll to the shell: the content column is "'
        + measured.shellScroll + '", so the page may scroll instead of the table body');
    }
    if (doc.clientWidth > 1100 && doc.scrollHeight > doc.clientHeight + 1) {
      problems.push('Ledger page scrolls: scrollHeight ' + doc.scrollHeight + ' > clientHeight ' + doc.clientHeight);
    }

    // Exactly one scrolling ancestor for the rows. A legacy .table-wrap inside
    // the body would be a second, and the sticky header would stick to it.
    const nested = Array.from(body.querySelectorAll('*')).filter((el) => {
      const style = getComputedStyle(el);
      return /(auto|scroll)/.test(style.overflowY) || /(auto|scroll)/.test(style.overflowX);
    });
    measured.nestedScrollRegions = nested.map((el) => (typeof el.className === 'string' && el.className
      ? '.' + el.className.trim().split(/\s+/).join('.')
      : el.tagName.toLowerCase()));
    if (nested.length) {
      problems.push('Ledger has a scrolling container inside its scroll owner: '
        + measured.nestedScrollRegions.join(', '));
    }

    const table = body.querySelector('table');
    if (table) {
      // The sticky header has to stick to the element the operator scrolls.
      const th = table.querySelector('thead th');
      if (th) {
        const position = getComputedStyle(th).position;
        measured.headerPosition = position;
        if (position !== 'sticky') {
          problems.push('Ledger header is "' + position + '", not sticky, so it scrolls away with the rows');
        }
        let scroller = null;
        for (let node = th.parentElement; node; node = node.parentElement) {
          const style = getComputedStyle(node);
          if (/(auto|scroll)/.test(style.overflowY)) { scroller = node; break; }
        }
        if (scroller !== body) {
          problems.push('Ledger header would stick to ' + (scroller ? scroller.className : 'nothing')
            + ' rather than to the body that owns the scroll');
        }
      }

      // §4.1: "left-aligned and not stretched". At the ultra-wide acceptance
      // width a sparse inventory must not become a band of text across the
      // display; the standard Ledger fixtures are all sparse.
      const tableWidth = table.getBoundingClientRect().width;
      measured.tableWidth = round(tableWidth);
      if (archetype === 'workspace--ledger' && doc.clientWidth >= 2400 && working - tableWidth < 200) {
        problems.push('Ledger table is ' + measured.tableWidth + 'px inside a ' + round(working)
          + 'px workspace: a sparse table has been stretched rather than left-aligned');
      }
    }
  }

  if (archetype === 'workspace--record') {
    // §4.2: the page is the scroll owner on a Record, so the shell column must
    // be allowed to scroll it.
    if (measured.shellScroll !== 'page') {
      problems.push('Record declared scroll policy "' + measured.shellScroll + '"; §4.2 gives the page the scroll');
    }
    if (!workspace.querySelector('.workspace__record-grid')) {
      problems.push('Record is missing its primary/facts grid');
    }
  }

  // --- Investigation (UI-4) ---------------------------------------------
  //
  // The rules a rendered page settles and a unit test cannot: which element
  // actually owns the scroll in each column, how wide the results column is at
  // this viewport, and whether the inspector is a third column or a drawer over
  // the results.
  //
  // The threshold itself is deliberately not written here. The archetype
  // publishes its --inspector-placement custom property beside the media query
  // that decides it; this reads that back and checks the geometry agrees — so
  // moving the threshold from 1500 to 1600 is an edit to workspace.css and to
  // nothing in the harness. A number carried here could only confirm itself.
  if (archetype === 'workspace--investigation') {
    const grid = workspace.querySelector('.workspace__investigation-grid');
    const rail = workspace.querySelector('.workspace__rail');
    const results = workspace.querySelector('.workspace__results');
    if (!grid || !rail || !results) {
      problems.push('Investigation is missing its rail, results or grid region');
      return { problems, measured };
    }

    const railWidth = rail.getBoundingClientRect().width;
    const resultsWidth = results.getBoundingClientRect().width;
    measured.railWidth = round(railWidth);
    measured.resultsWidth = round(resultsWidth);
    measured.inspectorPlacement =
      getComputedStyle(workspace).getPropertyValue('--inspector-placement').trim() || null;

    // §4.4: results and inspector scroll independently; the page does not.
    if (measured.shellScroll !== 'contain') {
      problems.push('Investigation did not declare no-page-scroll to the shell: the content column is "'
        + measured.shellScroll + '", so the page may scroll instead of the results');
    }
    if (doc.clientWidth > 1100 && doc.scrollHeight > doc.clientHeight + 1) {
      problems.push('Investigation page scrolls: scrollHeight ' + doc.scrollHeight
        + ' > clientHeight ' + doc.clientHeight);
    }

    if (doc.clientWidth > 1100) {
      // The rail is 252px and scrolls on its own. A rail that has handed its
      // scroll to an inner box is the defect UI-4 fixed, and it is invisible
      // until the rail is taller than the viewport — so the ownership is
      // checked, not the fact that something happened to fit.
      if (railWidth < 240 || railWidth > 264) {
        problems.push('Investigation rail is ' + measured.railWidth + 'px, not the fixed 252px of §4.4');
      }
      if (!/(auto|scroll)/.test(getComputedStyle(rail).overflowY)) {
        problems.push('Investigation rail cannot scroll independently of the results');
      }
      const railInner = Array.from(rail.querySelectorAll('*')).filter((el) => {
        const style = getComputedStyle(el);
        return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 1;
      });
      if (railInner.length) {
        problems.push('Investigation rail has a second scroll owner inside it: '
          + railInner.map((el) => '.' + String(el.className).trim().split(/\s+/).join('.')).join(', '));
      }

      // §4.4: never compressed below ~560px, never grown beyond ~900px —
      // whether or not a Track is selected. The floor applies only where there
      // is room for it; below that the archetype has already stacked.
      if (resultsWidth > 910) {
        problems.push('Investigation results column is ' + measured.resultsWidth
          + 'px, above the ~900px cap of §4.4: surplus width belongs to the inspector');
      }
      if (working - railWidth > 600 && resultsWidth < 555) {
        problems.push('Investigation results column is ' + measured.resultsWidth
          + 'px inside a ' + round(working) + 'px workspace, below the ~560px floor of §4.4');
      }

      // The rows scroll, not the column around them.
      const list = results.querySelector('.results__list');
      if (list && !/(auto|scroll)/.test(getComputedStyle(list).overflowY)) {
        problems.push('Investigation results list does not own its scroll');
      }
    }

    // The inspector, when there is one: a third column at and above the
    // threshold the layout declares, an overlay drawer below it — and never a
    // modal, whichever shape it is in (§20).
    const inspector = workspace.querySelector('.workspace__inspector');
    if (inspector && doc.clientWidth > 1100) {
      const style = getComputedStyle(inspector);
      const inspectorWidth = inspector.getBoundingClientRect().width;
      measured.inspectorWidth = round(inspectorWidth);
      measured.inspectorPosition = style.position;

      if (measured.inspectorPlacement === 'in-place') {
        if (style.position === 'absolute') {
          problems.push('Investigation inspector is still a drawer at ' + doc.clientWidth
            + 'px, where the layout declares it in place');
        }
        // In place, the inspector is what the surplus was saved for: at a wide
        // viewport it must be the column that grew, not the results.
        if (working - railWidth - resultsWidth > 40 && inspectorWidth < 320) {
          problems.push('Investigation inspector is only ' + measured.inspectorWidth
            + 'px while ' + round(working - railWidth - resultsWidth)
            + 'px of surplus exists: §4.4 gives the surplus to the inspector');
        }
      } else if (measured.inspectorPlacement === 'drawer') {
        if (style.position !== 'absolute') {
          problems.push('Investigation inspector is an in-flow column at ' + doc.clientWidth
            + 'px, where the layout declares it a drawer — the results are compressed instead of covered');
        }
      } else {
        problems.push('Investigation did not declare an inspector placement; the harness has '
          + 'nothing to check the rendered geometry against');
      }

      // §20: a drawer, not a dialog. No modality, no trap, nothing inert.
      if (workspace.querySelector('[role="dialog"], [aria-modal="true"], [inert]')) {
        problems.push('Investigation inspector claims modality: §20 makes it a non-modal drawer '
          + 'so the results stay readable underneath');
      }
    }
  }

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
      // §4.3.2 is a rule about the architecture, not about whether today's
      // fixtures happen to fit: the shell must have been told not to scroll
      // this surface, whatever is in it.
      if (measured.shellScroll !== 'contain') {
        problems.push('Workbench did not declare no-page-scroll to the shell: the content column is "'
          + measured.shellScroll + '", so it may scroll the canvas as soon as content grows');
      }
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

  // --- Review (UI-5) ----------------------------------------------------
  //
  // Section 4.5.1's rule is a rendered-page fact: Review may page-scroll, but at
  // 1366x768 the Evidence Player and the primary evidence summary must both be
  // in the initial viewport, and the player stays pinned in its column while
  // provenance scrolls past it. None of that can be settled without layout.
  if (archetype === 'workspace--review') {
    const player = workspace.querySelector('.workspace__player');
    const rail = workspace.querySelector('.workspace__review-rail');
    if (!player) {
      problems.push('Review is missing its player region');
      return { problems, measured };
    }

    const playerBox = player.getBoundingClientRect();
    measured.playerWidth = round(playerBox.width);
    measured.playerShare = working > 0 ? round((playerBox.width / working) * 100) : null;

    // The evidence dominates: the player column takes at least 65% of the
    // working width wherever the two columns stand side by side. The gate is
    // the frozen figure, not a softer one — a threshold of 60 that reports
    // itself as 65 is how a 65fr track quietly delivering 63.7% went unnoticed.
    // The only slack is a tenth of a point for sub-pixel rounding.
    if (doc.clientWidth > 1100 && measured.playerShare !== null && measured.playerShare < 64.9) {
      problems.push('Review gives the player only ' + measured.playerShare
        + '% of the working width; section 4.5 requires at least 65%');
    }

    measured.reviewRailWidth = rail ? round(rail.getBoundingClientRect().width) : null;

    // Section 25: on a wide display the surplus goes to the player, as it does
    // to the stage on the Workbench and the inspector on Investigation. A
    // player pinned at exactly the 65% floor hands better than a third of every
    // extra pixel to a rail that has a readable maximum and no use for more, so
    // the floor alone is not the whole rule and cannot be tested as if it were.
    if (doc.clientWidth >= 1900 && measured.playerShare !== null && measured.playerShare < 70) {
      problems.push('Review gives the player only ' + measured.playerShare
        + '% of the working width at ' + doc.clientWidth
        + 'px; section 25 sends ultra-wide surplus to the player, not to the rail');
    }

    // The primary evidence summary is the first panel in the rail.
    const summary = rail ? rail.querySelector('.panel') : null;
    if (!summary) {
      problems.push('Review is missing the primary evidence summary in its rail');
    } else if (doc.clientHeight <= 800) {
      const summaryBox = summary.getBoundingClientRect();
      measured.summaryTop = round(summaryBox.top);
      // Its top edge, not the whole panel: long provenance legitimately runs
      // below the fold, but the operator must be able to start reading the
      // summary without scrolling first.
      if (summaryBox.top >= doc.clientHeight) {
        problems.push('the primary evidence summary starts at ' + measured.summaryTop
          + 'px, below the ' + doc.clientHeight + 'px initial viewport (section 4.5.1)');
      }
      if (playerBox.top >= doc.clientHeight) {
        problems.push('the Evidence Player starts below the initial viewport (section 4.5.1)');
      }
    }

    measured.playerSticky = getComputedStyle(player).position;
    if (doc.clientWidth > 1100 && measured.playerSticky !== 'sticky') {
      problems.push('the Evidence Player column is ' + measured.playerSticky
        + ', so a fact about evidence can be read while the evidence is off screen (section 4.5.1)');
    }
    if (doc.clientWidth <= 1100 && measured.playerSticky === 'sticky') {
      problems.push('the stacked Review still pins its player; section 4.5.1 releases that at 1100');
    }

    // One timeline. Two scrub bars on one surface is a defect (section 18.3).
    measured.timelines = workspace.querySelectorAll('.evidence-timeline__track').length;
    if (measured.timelines !== 1) {
      problems.push('Review renders ' + measured.timelines + ' timelines; section 18 allows exactly one');
    }
    // The timeline's evidence must not be hidden from assistive technology, and
    // must not be shadowed by a second description of itself.
    const hiddenEvidence = workspace.querySelectorAll('.evidence-timeline__item[aria-hidden]').length;
    if (hiddenEvidence > 0) {
      problems.push(hiddenEvidence + ' timeline evidence items are hidden from assistive technology');
    }
    measured.timelineItems = workspace.querySelectorAll('.evidence-timeline__item').length;

    // Native controls occupy the band where evidence is drawn (section 18.1).
    if (workspace.querySelector('video[controls]')) {
      problems.push('the Evidence Player is using native browser controls');
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
})()`;
