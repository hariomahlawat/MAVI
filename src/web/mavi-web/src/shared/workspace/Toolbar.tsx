import type { ReactNode } from 'react';

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
 */
export default function Toolbar({
  label,
  children,
  actions,
  hint,
}: {
  /** Names the band for assistive technology. */
  label: string;
  /** Grouped controls, left. */
  children?: ReactNode;
  /** Actions, pushed right. */
  actions?: ReactNode;
  /** One line belonging to the band: an instruction, a count, a refusal. */
  hint?: ReactNode;
}) {
  return (
    <div className="toolbar-band" role="group" aria-label={label}>
      <div className="toolbar-band__row">
        {children}
        {hint ? <div className="toolbar-band__hint">{hint}</div> : null}
        <div className="toolbar-band__spacer" />
        {actions ? <div className="toolbar-band__actions">{actions}</div> : null}
      </div>
    </div>
  );
}
