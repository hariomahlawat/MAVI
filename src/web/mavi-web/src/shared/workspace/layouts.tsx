import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import Button from '../components/Button';
import Drawer from '../overlay/Drawer';
import { OVERLAY_QUERIES, useMediaQuery } from '../overlay/useMediaQuery';
import { useScrollPolicy } from './surfaceSlot';

/**
 * The five workspace archetypes of §4, with exactly one implementation each.
 *
 * They are deliberately five named components rather than one
 * `<Workspace type="…">`: the set is closed (§4 freezes it, and a sixth is
 * explicitly not designed), so a parameterised layout engine would be a
 * mechanism for inventing the sixth. Each takes only the regions its archetype
 * actually has, which is what stops a page composing something else.
 *
 * Scroll ownership (§4, frozen and authoritative) is carried by the archetype,
 * not by the page, in two halves that have to agree. `workspace.css` says which
 * element inside the archetype scrolls; `useScrollPolicy` tells the shell
 * whether its content column may scroll at all. The second half exists because
 * the shell's `.main` is `overflow: auto` for every surface, so without it the
 * Workbench's frozen no-page-scroll rule held only while its content happened
 * to fit. Both halves are declared by the layout component itself, which is
 * what a page cannot opt out of.
 *
 * Every archetype begins with the Context Bar, which the shell renders and an
 * archetype's page fills through `<ContextBar>` — so it is not a region here.
 */

/**
 * **Ledger** — scan, filter and act on many records of one kind.
 * Full width; the table body owns vertical scroll and the page does not.
 */
export function LedgerLayout({
  toolbar,
  notices,
  editor,
  children,
}: {
  /** The filter row: one band, few controls (§4.1). */
  toolbar?: ReactNode;
  /** Page-scope conditions that must not scroll away with the rows. */
  notices?: ReactNode;
  /**
   * A transient editable region belonging to this Ledger — the draft of a
   * record being created, shown only while one is being created.
   *
   * §21 rules out both of the alternatives a Ledger otherwise has: routine
   * create must not require a modal, and an inline form is preferred over the
   * permanent second card beside the list that Cameras carried before UI-3. So
   * the archetype gains one optional region rather than each list page
   * inventing somewhere to put a form.
   *
   * It sits above the scroll owner, not inside it, for the same reason the
   * toolbar does: a form that scrolls away while it is being filled is a form
   * the operator has to hunt for. A Ledger that creates nothing passes nothing
   * and renders nothing.
   */
  editor?: ReactNode;
  /** The table or list. Owns vertical scroll. */
  children: ReactNode;
}) {
  // §4.1: "The table body. The page does not scroll."
  useScrollPolicy('contain');
  return (
    <section className="workspace workspace--ledger">
      {toolbar ? <div className="workspace__band">{toolbar}</div> : null}
      {notices ? <div className="workspace__notices">{notices}</div> : null}
      {editor ? <div className="workspace__editor">{editor}</div> : null}
      <div className="workspace__body workspace__body--scroll">{children}</div>
    </section>
  );
}

/**
 * **Overview only** — the §4.1.1 Ledger-summary exception.
 *
 * Overview is a summary and attention surface rather than a dense operational
 * table, and it alone MAY stay centred at `--content-max`. This is a separate
 * named component precisely so the exception cannot be reached by passing a
 * prop: a page that wants it has to import the component that says Overview on
 * the tin, and `workspace.test.tsx` asserts only Overview does.
 */
export function LedgerSummaryLayout({
  notices,
  children,
}: {
  notices?: ReactNode;
  children: ReactNode;
}) {
  // §4's scroll-ownership table is frozen and lists Overview under Ledger, and
  // §4.1.1 grants this variant a *width* exception and nothing else — so the
  // Ledger's grammar holds here: this body owns vertical scroll and the page
  // does not. An earlier version declared `page` because this layout had no
  // scrolling region to be the owner, which was a gap in the layout rather
  // than an allowance in the specification; the region is the fix.
  useScrollPolicy('contain');
  return (
    <section className="workspace workspace--ledger-summary">
      {notices ? <div className="workspace__notices">{notices}</div> : null}
      <div className="workspace__body workspace__body--scroll">{children}</div>
    </section>
  );
}

/**
 * **Record** — everything known about one object.
 * Centred reading surface; the page owns scroll. The facts rail *is* the
 * inspector, not an addition to one, so it is a region rather than a slot for
 * `<Inspector>`.
 */
export function RecordLayout({
  notices,
  children,
  facts,
}: {
  notices?: ReactNode;
  /** The primary column, roughly 70%. */
  children: ReactNode;
  /** The facts rail, roughly 30%. Stacks below the primary at ≤1100 (§4.2). */
  facts?: ReactNode;
}) {
  // §4.2: the page is the scroll owner on a Record.
  useScrollPolicy('page');
  return (
    <section className="workspace workspace--record">
      {notices ? <div className="workspace__notices">{notices}</div> : null}
      <div className="workspace__record-grid">
        <div className="workspace__record-primary">{children}</div>
        {facts ? <div className="workspace__record-facts">{facts}</div> : null}
      </div>
    </section>
  );
}

/**
 * **Workbench** — direct manipulation of spatial content.
 *
 * The one archetype with a hard no-page-scroll rule (§4.3.2): a scrolled canvas
 * is a broken canvas. The stage absorbs all residual width after the rail, the
 * fixed inspector and the gutters; the inspector never becomes resizable and
 * the stage is never compressed below 65% of the working width (§4.3.1).
 */
export function WorkbenchLayout({
  modes,
  notices,
  stage,
  inspector,
  inspectorLabel = 'Inspector',
  footer,
}: {
  /** The mode strip: which tool is armed. */
  modes?: ReactNode;
  notices?: ReactNode;
  /** The canvas. Grows; never scrolls. */
  stage: ReactNode;
  /** Fixed 300–360px. Its body owns the only scroll on this surface. */
  inspector: ReactNode;
  /** Names the drawer's toggle in the narrow band where it becomes one. */
  inspectorLabel?: string;
  /** Optional strip below the stage, such as revision history. */
  footer?: ReactNode;
}) {
  // §4.3.2, the one archetype with a hard no-page-scroll rule: a scrolled
  // canvas is a broken canvas, so the shell's content column must not be able
  // to scroll this surface at desktop widths either.
  useScrollPolicy('contain');

  // Between 1101 and 1149 the inspector is a drawer over the stage (§4.3.1):
  // the stage keeps the full working width instead of being compressed below
  // its floor. A drawer that cannot be shut is not a drawer — it is a panel
  // parked on top of the canvas — so it starts closed and has a way out.
  //
  // At every other width the inspector is in flow. Leaving the band closes the
  // drawer, so a drawer opened at 1120 is never found open — and modal — when
  // the window comes back into the band later.
  const overlay = useMediaQuery(OVERLAY_QUERIES.workbench);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const inspectorId = useId();
  // Everything in the workspace beside the drawer: inert while it is open as
  // an overlay, so the modal it declares is the modal the operator gets.
  const bandRef = useRef<HTMLDivElement | null>(null);
  const noticesRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!overlay) setDrawerOpen(false);
  }, [overlay]);

  const toggle = (
    <Button
      size="sm"
      variant="ghost"
      className="workspace__drawer-toggle"
      aria-expanded={drawerOpen}
      aria-controls={inspectorId}
      onClick={() => setDrawerOpen((open) => !open)}
    >
      {inspectorLabel}
    </Button>
  );

  return (
    <section className={`workspace workspace--workbench${drawerOpen ? ' has-open-drawer' : ''}`}>
      {modes ? (
        <div className="workspace__band" ref={bandRef}>{modes}{toggle}</div>
      ) : (
        <div className="workspace__band workspace__band--drawer-only" ref={bandRef}>{toggle}</div>
      )}
      {notices ? <div className="workspace__notices" ref={noticesRef}>{notices}</div> : null}
      <div className="workspace__stage-grid">
        <div className="workspace__stage" ref={stageRef}>{stage}</div>
        {/* §20: a drawer only in the overlay band and only while open; an
            ordinary column everywhere else. */}
        <Drawer
          open={drawerOpen}
          overlay={overlay}
          onClose={() => setDrawerOpen(false)}
          covers={[bandRef, noticesRef, stageRef]}
          id={inspectorId}
          className="workspace__inspector"
        >
          <Button
            size="sm"
            variant="ghost"
            icon="x"
            iconOnly
            className="workspace__drawer-close"
            onClick={() => setDrawerOpen(false)}
          >
            {`Close ${inspectorLabel.toLowerCase()}`}
          </Button>
          {inspector}
        </Drawer>
      </div>
      {footer ? <div className="workspace__footer">{footer}</div> : null}
    </section>
  );
}

/**
 * **Investigation** — form a query, scan candidates, inspect one without losing
 * the set. The results list and the inspector body scroll independently; the
 * page does not.
 *
 * Open decisions 3 and 4 closed in UI-4: the inspector goes in place at 1600px
 * and is a drawer below it, never narrower than 440px in place, and an
 * ultra-wide display grows the inspector rather than the results column. Both
 * are settled in `workspace.css` rather than here, because both are geometry —
 * and the threshold is written there once, beside the property the §26 harness
 * reads it back from.
 *
 * The results cap holds whether or not a Track is selected. An Investigation
 * with nothing selected is still a scan surface, and a 2000px result row is no
 * easier to read because there is no inspector beside it.
 */
export function InvestigationLayout({
  rail,
  notices,
  children,
  inspector,
  onCloseInspector,
}: {
  /** The filter rail, 252px (§4.4). */
  rail: ReactNode;
  notices?: ReactNode;
  /** The results column. Owns its own scroll. */
  children: ReactNode;
  /** Appears on selection; its body scrolls independently. */
  inspector?: ReactNode;
  /**
   * Closes the inspector — Escape and a click on the covered results while it
   * is a drawer. The surface returns focus itself, to the selected result.
   */
  onCloseInspector?: () => void;
}) {
  // §4.4: results and inspector scroll independently; the page does not.
  useScrollPolicy('contain');
  // §20, amended in v2.0: below 1600px the inspector covers the results and is
  // a drawer — focus moves into it, stays there, and the results it covers are
  // inert until it closes. The rail is inert with them: a modal drawer that
  // left the filters live would be modal to the keyboard and to assistive
  // technology but not to the pointer. At 1600px and above it is an in-place
  // column and claims none of that.
  const overlay = useMediaQuery(OVERLAY_QUERIES.investigation);
  const noticesRef = useRef<HTMLDivElement | null>(null);
  const railRef = useRef<HTMLDivElement | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);
  return (
    <section className={`workspace workspace--investigation${inspector ? ' has-inspector' : ''}`}>
      {notices ? <div className="workspace__notices" ref={noticesRef}>{notices}</div> : null}
      <div className="workspace__investigation-grid">
        <div className="workspace__rail" ref={railRef}>{rail}</div>
        <div className="workspace__results" ref={resultsRef}>{children}</div>
        {inspector ? (
          <Drawer
            open
            overlay={overlay}
            onClose={() => onCloseInspector?.()}
            covers={[noticesRef, railRef, resultsRef]}
            restoreFocusOnClose={false}
            className="workspace__inspector"
          >
            {inspector}
          </Drawer>
        ) : null}
      </div>
    </section>
  );
}

/**
 * **Review** — evidence-dominant record.
 *
 * The page owns scroll here, deliberately: provenance and attestation
 * legitimately run below the fold (§4.5.1). The player region is sticky within
 * its column so a fact about evidence is never read while the evidence itself
 * is off screen; at ≤1100 the rail stacks and the stickiness is released.
 *
 * UI-2 builds this layout. UI-5 migrates the Review page onto it and owns every
 * change to the player itself.
 */
export function ReviewLayout({
  notices,
  player,
  rail,
  children,
}: {
  notices?: ReactNode;
  /** The Evidence Player region. Sticky within its column above 1100px. */
  player: ReactNode;
  /** Summary, the Track Evidence Set, provenance. */
  rail?: ReactNode;
  /** Evidence content below the player, in the same column. */
  children?: ReactNode;
}) {
  // §4.5.1: the page owns scroll here deliberately — provenance and
  // attestation legitimately run below the fold.
  useScrollPolicy('page');
  return (
    <section className="workspace workspace--review">
      {notices ? <div className="workspace__notices">{notices}</div> : null}
      <div className="workspace__review-grid">
        <div className="workspace__review-main">
          <div className="workspace__player">{player}</div>
          {children ? <div className="workspace__review-body">{children}</div> : null}
        </div>
        {rail ? <div className="workspace__review-rail">{rail}</div> : null}
      </div>
    </section>
  );
}
