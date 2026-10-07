import { cloneElement, useEffect, useId, useRef, useState, type FocusEvent, type ReactElement } from 'react';

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

  // §36.3: shown after one motion-token delay (`--dur`, 120ms by default) on
  // hover and on focus, so a pointer merely crossing the controls does not
  // flash hints. Leaving or blurring before the delay cancels it.
  const timers = useRef<{ hover?: number; focus?: number }>({});
  const cancel = (channel: 'hover' | 'focus') => {
    window.clearTimeout(timers.current[channel]);
    timers.current[channel] = undefined;
  };
  const arm = (channel: 'hover' | 'focus', set: (value: boolean) => void) => {
    cancel(channel);
    timers.current[channel] = window.setTimeout(() => set(true), tooltipDelayMs());
  };
  const disarm = (channel: 'hover' | 'focus', set: (value: boolean) => void) => {
    cancel(channel);
    set(false);
  };
  useEffect(() => () => {
    cancel('hover');
    cancel('focus');
  }, []);

  useEffect(() => {
    if (!shown) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // Dismissed until the next pointer entry or focus, whichever comes.
      disarm('hover', setHovered);
      disarm('focus', setFocused);
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
      onPointerEnter={() => arm('hover', setHovered)}
      onPointerLeave={() => disarm('hover', setHovered)}
      onFocus={() => arm('focus', setFocused)}
      onBlur={(event: FocusEvent<HTMLSpanElement>) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) disarm('focus', setFocused);
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

/** The motion token the delay is defined by, read from the stylesheet; 120ms where it is not loaded. */
function tooltipDelayMs(): number {
  const raw = typeof document === 'undefined'
    ? ''
    : getComputedStyle(document.documentElement).getPropertyValue('--dur').trim();
  const ms = raw.endsWith('ms') ? parseFloat(raw) : raw.endsWith('s') ? parseFloat(raw) * 1000 : NaN;
  return Number.isFinite(ms) && ms >= 0 ? ms : 120;
}
