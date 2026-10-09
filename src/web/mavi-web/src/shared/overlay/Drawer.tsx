import { useEffect, useId, useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react';
import { containTab, focusableWithin, makeInert, restoreFocus } from './focus';

/**
 * An inspector that is, at the current width, an overlay (specification §20).
 *
 * The Investigation inspector below 1600px and the Workbench inspector between
 * 1101 and 1149px cover part of the workspace. While they do, they are a
 * drawer, and §20's contract applies:
 * - opening moves focus to the drawer's heading, which names it;
 * - Tab and Shift+Tab stay inside it;
 * - Escape closes it;
 * - the content it covers is inert — nothing behind it can be clicked or
 *   focused — and a click on that covered area closes the drawer;
 * - closing returns focus to the control that opened it (or the surface does,
 *   where it has a better target: the Investigation returns it to the
 *   selected result).
 *
 * At every other width the same element is an ordinary in-place column and
 * claims none of this — no dialog role, no trap, nothing inert — because a
 * permanent inspector is not modal. The presentation can change under an open
 * inspector (a window resized across the threshold) and its content is never
 * remounted for it: only the attributes change.
 */
export default function Drawer({
  open,
  overlay,
  onClose,
  covers,
  restoreFocusOnClose = true,
  id,
  className,
  panelRef: externalPanelRef,
  coversViewport = false,
  children,
}: {
  /** Whether the inspector is showing. */
  open: boolean;
  /** Whether, at the current width, it is drawn over the workspace rather than beside it. */
  overlay: boolean;
  onClose: () => void;
  /** The regions behind the drawer; inert while it is open as an overlay. */
  covers: readonly RefObject<HTMLElement | null>[];
  /**
   * The drawer is drawn over the whole viewport (§25 Tier B: the shell rail's
   * overlay, a stacked Investigation's drawers), so everything outside it is
   * covered — the shell rail and the Context Bar included — and inert, not
   * only the named regions. Its own scrim stays live: it is how a click closes it.
   */
  coversViewport?: boolean;
  /** False where the surface returns focus itself. */
  restoreFocusOnClose?: boolean;
  id?: string;
  className: string;
  /** The panel element, for an owner that names it as a region elsewhere. */
  panelRef?: RefObject<HTMLDivElement | null>;
  children: ReactNode;
}) {
  const ownPanelRef = useRef<HTMLDivElement | null>(null);
  const panelRef = externalPanelRef ?? ownPanelRef;
  const invokerRef = useRef<Element | null>(null);
  const headingFallbackId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  /** Every inert this drawer applied while open, released together on close. */
  const releasesRef = useRef<Array<() => void>>([]);
  /** Whether this opening has taken its invoker and moved focus yet. */
  const openedRef = useRef(false);
  const modal = open && overlay;
  useEffect(() => {
    if (!modal) openedRef.current = false;
  }, [modal]);

  // Before paint, so the first frame of the drawer is already the modal one.
  useLayoutEffect(() => {
    if (!modal) return undefined;
    const panel = panelRef.current;
    if (!panel) return undefined;
    // Re-run when the drawer changes anchoring under an open panel (a window
    // resized across the stacking threshold): the inert set and the name are
    // re-derived, but the invoker and focus are taken once per opening — the
    // operator's place in the panel survives the resize.
    if (!openedRef.current) {
      openedRef.current = true;
      invokerRef.current = document.activeElement;
      focusHeading(panel, headingFallbackId);
    } else {
      nameByHeading(panel, headingFallbackId);
    }
    releasesRef.current = [makeInert(coversViewport ? outsideOf(panel) : covers.map((ref) => ref.current))];

    const onKeyDown = (event: KeyboardEvent) => {
      // Only the topmost modal answers: a drawer another modal has made inert
      // (the navigation overlay opened over an inspector drawer) holds
      // nothing — its Tab trap would find no focusable and its Escape would
      // close it behind the one the operator is in.
      if (panel.closest('[inert]')) return;
      // A dialog opened over the drawer owns the keyboard until it closes:
      // its Escape cancels the dialog, never the drawer beneath it.
      if (document.querySelector('.dialog-host')) return;
      if (event.key === 'Escape') {
        // §20: Escape closes an overlay drawer from anywhere inside it,
        // fields included — the documented way out must not depend on where
        // focus happens to be. Captured at the window, so the drawer takes it
        // before the surface does. (A native select's open list and a
        // full-screen player consume Escape in the browser before it gets here.)
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (containTab(event, panel)) event.stopPropagation();
    };
    window.addEventListener('keydown', onKeyDown, true);

    return () => {
      window.removeEventListener('keydown', onKeyDown, true);
      for (const release of releasesRef.current) release();
      releasesRef.current = [];
      panel.removeAttribute('aria-labelledby');
    };
    // `covers` is read when the drawer opens; a new array identity per render
    // must not re-run the trap. Regions that appear later are caught below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modal, headingFallbackId, coversViewport]);

  // A covered region can mount while the drawer is open — a notice that
  // appears when a supporting request fails behind it. It is made inert (and
  // so dimmed) on the commit that mounts it, before paint, and released with
  // the rest; nothing operable may appear beside a modal drawer.
  useLayoutEffect(() => {
    if (!modal) return;
    const late = covers
      .map((ref) => ref.current)
      .filter((element): element is HTMLElement => element !== null && !element.hasAttribute('inert'));
    if (late.length > 0) releasesRef.current.push(makeInert(late));
  });

  // Focus goes back after the commit, not in the layout cleanup above: React
  // re-focuses whatever held focus before a commit once its mutations are done,
  // which would silently undo a restoration made during them.
  useEffect(() => {
    if (!modal || !restoreFocusOnClose) return undefined;
    const panel = panelRef.current;
    const invoker = invokerRef.current;
    return () => {
      const active = document.activeElement;
      // Only where focus would otherwise be lost: if the operator has already
      // moved it somewhere real, that choice stands.
      if (!active || active === document.body || (panel?.contains(active) ?? false)) {
        restoreFocus(invoker);
        // The window crossed out of the overlay range and took the invoker
        // with it (the Investigation filters' header control), while the
        // panel stays, in place: keep focus in the panel, not on the document.
        const now = document.activeElement;
        if ((!now || now === document.body) && panel?.isConnected) focusableWithin(panel)[0]?.focus();
      }
    };
  }, [modal, restoreFocusOnClose]);

  // The drawer's content can be replaced while it is open — the Investigation
  // inspector remounts for each Track the operator steps to. Focus that was on
  // a removed element falls to the document; it is put back on the heading so
  // the trap still has somewhere to hold it.
  useEffect(() => {
    if (!modal) return;
    const panel = panelRef.current;
    if (panel && (document.activeElement === document.body || document.activeElement === null)) {
      focusHeading(panel, headingFallbackId);
    }
  });

  return (
    <>
      {modal ? (
        // Pointer counterpart of Escape over the covered region. Hidden from
        // assistive technology: the drawer's own close control is the named one.
        <div className="drawer-scrim" aria-hidden="true" onClick={() => onCloseRef.current()} />
      ) : null}
      <div
        ref={panelRef}
        id={id}
        className={className}
        // Focusable by script while modal, so a click on plain text inside the
        // drawer leaves focus on the drawer rather than dropping it to the
        // document (which the effect above would answer by jumping to the heading).
        {...(modal ? { role: 'dialog', 'aria-modal': true as const, tabIndex: -1 } : {})}
      >
        {children}
      </div>
    </>
  );
}

/**
 * Everything outside the panel, by the siblings of each of its ancestors up to
 * the document body — except the drawer's own scrim, which must stay live for
 * a click on it to close the drawer.
 */
function outsideOf(panel: HTMLElement): HTMLElement[] {
  const outside: HTMLElement[] = [];
  for (let node: HTMLElement | null = panel; node && node !== document.body; node = node.parentElement) {
    const parent: HTMLElement | null = node.parentElement;
    if (!parent) break;
    for (const sibling of Array.from(parent.children) as Element[]) {
      if (sibling === node || !(sibling instanceof HTMLElement) || sibling.classList.contains('drawer-scrim')) continue;
      outside.push(sibling);
    }
  }
  return outside;
}

/**
 * Focus the drawer's heading — the first heading inside it — and name the
 * drawer by it. The heading takes focus programmatically (tabindex -1) without
 * joining the Tab sequence.
 */
function focusHeading(panel: HTMLElement, fallbackId: string): void {
  const heading = nameByHeading(panel, fallbackId);
  if (!heading) {
    panel.setAttribute('tabindex', '-1');
    panel.focus();
    return;
  }
  heading.focus();
}

/** Name the drawer by its first heading; the heading, or null when it has none. */
function nameByHeading(panel: HTMLElement, fallbackId: string): HTMLElement | null {
  const heading = panel.querySelector<HTMLElement>('h1, h2, h3');
  if (!heading) return null;
  if (!heading.id) heading.id = fallbackId;
  if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
  panel.setAttribute('aria-labelledby', heading.id);
  return heading;
}
