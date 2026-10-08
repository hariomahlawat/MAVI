import type { ButtonHTMLAttributes, ReactNode } from 'react';
import Icon from './Icon';

/**
 * An on/off chip: a native button carrying `aria-pressed`, with a filled
 * pressed state (§12, §27).
 *
 * §27.1 promotion: the Evidence Player's layer toggles are its caller, and the
 * Evidence Player is itself shared by Review and the Search inspector — so
 * every chip means the same thing (a layer is shown or not), is operated the
 * same way (one press toggles it), is announced the same way (a button that is
 * pressed or not) and has no reason to pull apart from the others. A
 * single-select group of modes is not this component; that is `Segmented`.
 *
 * What it guarantees:
 * - a native `<button type="button">`, so Enter and Space press it and it is in
 *   the tab order with the global 2px focus ring;
 * - `aria-pressed` is always `true` or `false`, never absent: a chip that does
 *   not say whether it is on is a defect (§12);
 * - the pressed state is not colour alone: the leading mark is an empty box
 *   when off and a filled box with a check when on, a difference of shape and
 *   fill that reads in greyscale (§23);
 * - it is drawn by the shared Button rules (`.btn`), so hover is a surface and
 *   border step that never repaints text, the transition is the one standard
 *   duration, and disabled is the one disabled contract — the three disabled
 *   tokens and `not-allowed`, never an opacity — including when it is pressed.
 *
 * It takes no tooltip. A reason the chip is unavailable is the caller's to
 * state beside it and bind with `aria-describedby` (§12), because a disabled
 * control receives no pointer events and a hint on one would never be seen.
 */
export default function ToggleChip({
  pressed,
  className,
  children,
  ...rest
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type' | 'aria-pressed'> & {
  /** Whether the thing this chip controls is on. */
  pressed: boolean;
  /** The visible name of what is toggled. */
  children: ReactNode;
}) {
  return (
    <button
      {...rest}
      type="button"
      aria-pressed={pressed}
      className={['btn btn--sm toggle-chip', className].filter(Boolean).join(' ')}
    >
      <span className="toggle-chip__mark" aria-hidden="true">
        {pressed ? <Icon name="check" size="sm" /> : null}
      </span>
      {children}
    </button>
  );
}
