import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import Button from '../components/Button';
import Drawer from '../overlay/Drawer';
import { SHELL_QUERIES, useMediaQuery } from '../overlay/useMediaQuery';

/**
 * The toolbar band: the row of controls that acts on what is below it.
 *
 * §27.1 promotion: the Ledger filter row and the Workbench mode strip are the
 * same structural thing — a 32px band, controls grouped left, actions pushed
 * right, compact density — and every archetype that has one wants it to look
 * and measure identically. What they put in it is theirs; the band is shared.
 *
 * It carries no page logic. `hint` exists because a mode strip needs to explain
 * an armed mode next to the mode, and a filter row needs to say what it matched;
 * both are one line of text belonging to the band, not to the content below.
 *
 * `drawer` is the §25 Tier C Ledger row ("filters move into a drawer"): below
 * 768px the grouped controls leave the band for the shared Drawer — full
 * width, modal, opened from the band — and the band keeps its hint. The
 * controls are the same elements at every width (the Drawer is simply not an
 * overlay above Tier C), so a value being typed survives a resize.
 */
export default function Toolbar({
  label,
  children,
  actions,
  hint,
  drawer,
}: {
  /** Names the band for assistive technology. */
  label: string;
  /** Grouped controls, left. */
  children?: ReactNode;
  /** Actions, pushed right. */
  actions?: ReactNode;
  /** One line belonging to the band: an instruction, a count, a refusal. */
  hint?: ReactNode;
  /**
   * At Tier C the controls move into a drawer named `label`, opened from the
   * band by a control saying so and how many of them are in effect.
   */
  drawer?: { label: string; active?: number };
}) {
  const narrow = useMediaQuery(SHELL_QUERIES.narrow) && Boolean(drawer) && Boolean(children);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  // Whether the drawer's toggle holds focus. Leaving Tier C unmounts it in
  // the same commit, so it is recorded as it happens, not read afterwards.
  const toggleFocusedRef = useRef(false);
  const panelId = useId();

  // Leaving Tier C closes the drawer (its controls go back into the band),
  // and entering it with focus on one of them — about to be shut away in the
  // closed drawer — moves focus, before paint, to the control that opens it.
  useLayoutEffect(() => {
    if (!narrow) {
      setOpen(false);
      // The toggle that held focus is gone; the controls it opened are back
      // in the band, so focus goes to the first of them.
      if (toggleFocusedRef.current && (document.activeElement === document.body || !document.activeElement)) {
        panelRef.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus();
      }
      toggleFocusedRef.current = false;
      return;
    }
    if (!open && panelRef.current?.contains(document.activeElement)) toggleRef.current?.focus();
    // The crossing alone: `open` is read, not watched.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [narrow]);

  const active = drawer?.active ?? 0;
  // A band with no Tier C drawer (a Workbench mode strip, the analytics
  // window) keeps its controls exactly where they always were.
  const controls = !drawer ? children : children ? (
    <Drawer
      open={narrow && open}
      overlay={narrow}
      coversViewport={narrow}
      covers={[]}
      onClose={() => setOpen(false)}
      className={`toolbar-band__controls${narrow ? ' toolbar-band__controls--drawer' : ''}`}
      id={panelId}
      panelRef={panelRef}
    >
      {narrow && drawer ? (
        <div className="workspace__rail-head">
          <h2>{drawer.label}</h2>
          <Button size="sm" variant="ghost" icon="x" iconOnly onClick={() => setOpen(false)}>
            {`Close ${drawer.label.toLowerCase()}`}
          </Button>
        </div>
      ) : null}
      {children}
    </Drawer>
  ) : null;

  return (
    <div className={`toolbar-band${narrow ? ' toolbar-band--narrow' : ''}`} role="group" aria-label={label}>
      <div className="toolbar-band__row">
        {narrow && drawer ? (
          <Button
            ref={toggleRef}
            size="sm"
            icon="filter"
            className="toolbar-band__drawer-toggle"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen(true)}
            onFocus={() => { toggleFocusedRef.current = true; }}
            onBlur={() => { toggleFocusedRef.current = false; }}
          >
            {active > 0 ? `${drawer.label} · ${active}` : drawer.label}
          </Button>
        ) : null}
        {controls}
        {hint ? <div className="toolbar-band__hint">{hint}</div> : null}
        <div className="toolbar-band__spacer" />
        {actions ? <div className="toolbar-band__actions">{actions}</div> : null}
      </div>
    </div>
  );
}
