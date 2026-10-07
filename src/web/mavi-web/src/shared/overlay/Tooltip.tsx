import { cloneElement, useEffect, useId, useState, type FocusEvent, type ReactElement } from 'react';

/**
 * Non-essential information about a control, shown on hover and on keyboard
 * focus (specification §23, §27).
 *
 * What it may carry is narrow: a hint the operator can do without — a
 * shortcut, the full value of a truncated identity. It is never a control's
 * only name (the control keeps its own accessible name; the tooltip is its
 * description, through `aria-describedby`), it never carries an instruction a
 * task depends on, and it never takes focus. Escape dismisses it without moving
 * focus; the key still reaches the surface, so on the inspector's controls the
 * same Escape also closes the inspector, as it would with no tooltip shown.
 */
export default function Tooltip({
  content,
  children,
}: {
  /** The hint. Plain text: a tooltip is not a place for controls. */
  content: string;
  /** One element that can take focus and already has its own accessible name. */
  children: ReactElement<{ 'aria-describedby'?: string; disabled?: boolean; 'aria-disabled'?: boolean | 'true' | 'false' }>;
}) {
  const id = useId();
  // Two channels, tracked apart: leaving one must not hide a hint the other
  // still holds open (pointer still over a focused trigger, or focus still on
  // a trigger the pointer has left).
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  // §36.3: never on a disabled control — a hint for an action that cannot be
  // taken advertises it. The wrapper stays, so the control is not remounted
  // when it becomes enabled again.
  const inactive = Boolean(children.props.disabled)
    || children.props['aria-disabled'] === true || children.props['aria-disabled'] === 'true';
  const shown = (hovered || focused) && !inactive;

  useEffect(() => {
    if (!shown) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // Dismissed until the next pointer entry or focus, whichever comes.
      setHovered(false);
      setFocused(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [shown]);

  const existing = children.props['aria-describedby'];
  const trigger = cloneElement(children, {
    'aria-describedby': [existing, inactive ? null : id].filter(Boolean).join(' ') || undefined,
  });

  return (
    <span
      className="tooltip-anchor"
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(event: FocusEvent<HTMLSpanElement>) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false);
      }}
    >
      {trigger}
      {/* Always in the document so the description is there before it is
          shown; `hidden` keeps it off screen and out of the reading order. */}
      <span className="tooltip" role="tooltip" id={id} hidden={!shown}>
        {content}
      </span>
    </span>
  );
}
