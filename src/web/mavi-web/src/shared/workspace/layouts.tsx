import { useEffect, useId, useState, type ReactNode } from 'react';
import Button from '../components/Button';

/**
 * The five workspace archetypes of §4, with exactly one implementation each.
 *
 * They are deliberately five named components rather than one
 * `<Workspace type="…">`: the set is closed (§4 freezes it, and a sixth is
 * explicitly not designed), so a parameterised layout engine would be a
 * mechanism for inventing the sixth. Each takes only the regions its archetype
 * actually has, which is what stops a page composing something else.
 *
 * Scroll ownership (§4, frozen and authoritative) is carried by the archetype
 * class, not by the page. A page cannot opt out of it, and `workspace.css` is
 * the single place it is expressed.
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
  children,
}: {
  /** The filter row: one band, few controls (§4.1). */
  toolbar?: ReactNode;
  /** Page-scope conditions that must not scroll away with the rows. */
  notices?: ReactNode;
  /** The table or list. Owns vertical scroll. */
  children: ReactNode;
}) {
  return (
    <section className="workspace workspace--ledger">
      {toolbar ? <div className="workspace__band">{toolbar}</div> : null}
      {notices ? <div className="workspace__notices">{notices}</div> : null}
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
  return (
    <section className="workspace workspace--ledger-summary">
      {notices ? <div className="workspace__notices">{notices}</div> : null}
      <div className="workspace__body">{children}</div>
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
  // Between 1101 and 1149 the inspector is a drawer over the stage (§4.3.1):
  // the stage keeps the full working width instead of being compressed below
  // its floor. A drawer that cannot be shut is not a drawer — it is a panel
  // parked on top of the canvas — so it starts closed and has a way out.
  //
  // The state is only ever consulted inside that band, by CSS. At every other
  // width the inspector is in flow and this is inert, which is what stops a
  // drawer closed at 1120 from hiding the inspector at 1920.
  const [drawerOpen, setDrawerOpen] = useState(false);
  const inspectorId = useId();

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // Captured at the window, so an open drawer takes Escape before the
      // surface's own handler does: closing what is covering the canvas is
      // what the operator meant, not cancelling what they were drawing on it.
      event.stopPropagation();
      setDrawerOpen(false);
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [drawerOpen]);

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
        <div className="workspace__band">{modes}{toggle}</div>
      ) : (
        <div className="workspace__band workspace__band--drawer-only">{toggle}</div>
      )}
      {notices ? <div className="workspace__notices">{notices}</div> : null}
      <div className="workspace__stage-grid">
        <div className="workspace__stage">{stage}</div>
        <div className="workspace__inspector" id={inspectorId}>
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
        </div>
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
 * The inspector's in-place threshold and the ultra-wide split ratio are open
 * decisions 3 and 4, which UI-4 closes; this layout carries the structure they
 * will be decided against and does not pre-empt either.
 */
export function InvestigationLayout({
  rail,
  notices,
  children,
  inspector,
}: {
  /** The filter rail, 252px (§4.4). */
  rail: ReactNode;
  notices?: ReactNode;
  /** The results column. Owns its own scroll. */
  children: ReactNode;
  /** Appears on selection; its body scrolls independently. */
  inspector?: ReactNode;
}) {
  return (
    <section className={`workspace workspace--investigation${inspector ? ' has-inspector' : ''}`}>
      {notices ? <div className="workspace__notices">{notices}</div> : null}
      <div className="workspace__investigation-grid">
        <div className="workspace__rail">{rail}</div>
        <div className="workspace__results">{children}</div>
        {inspector ? <div className="workspace__inspector">{inspector}</div> : null}
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
  /** Summary, representative frame, provenance. */
  rail?: ReactNode;
  /** Evidence content below the player, in the same column. */
  children?: ReactNode;
}) {
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
