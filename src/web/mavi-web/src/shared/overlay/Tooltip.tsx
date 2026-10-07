import { cloneElement, useEffect, useId, useLayoutEffect, useRef, useState, type FocusEvent, type ReactElement } from 'react';

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
  enabled = true,
  children,
}: {
  /** The hint. Plain text: a tooltip is not a place for controls. */
  content: string;
  /**
   * Whether there is anything to say. A truncated value's full text is worth a
   * hint only while it is actually cut off (§16): a hint that repeats what is
   * fully visible is noise. The wrapper stays either way, so toggling this
   * never remounts the trigger or changes the layout that decided it.
   */
  enabled?: boolean;
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
  const inactive = !enabled || Boolean(children.props.disabled)
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

  // Centred under its trigger unless that would cut it off: a trigger near the
  // edge of what clips it (the inspector's Close at the right of the content
  // column) gets a hint aligned to that edge instead. Measured before paint,
  // each time it opens, and again while open if anything scrolls or resizes.
  const tipRef = useRef<HTMLSpanElement | null>(null);
  useLayoutEffect(() => {
    const tip = tipRef.current;
    if (!shown || !tip) return undefined;
    const place = () => {
      tip.removeAttribute('data-align');
      tip.removeAttribute('data-place');
      tip.removeAttribute('data-float');
      tip.style.left = '';
      tip.style.top = '';
      const bounds = clippingBounds(tip);
      const rect = tip.getBoundingClientRect();
      const anchor = (tip.parentElement ?? tip).getBoundingClientRect();
      const height = rect.bottom - rect.top;
      const fitsAcross = rect.right - rect.left <= bounds.right - bounds.left;
      const fitsBelow = rect.bottom <= bounds.bottom;
      const fitsAbove = anchor.top - (rect.top - anchor.bottom) - height >= bounds.top;
      if (fitsAcross && (fitsBelow || fitsAbove)) {
        if (rect.right > bounds.right) tip.setAttribute('data-align', 'end');
        else if (rect.left < bounds.left) tip.setAttribute('data-align', 'start');
        // Below the trigger unless that is cut off — the last row of a
        // scrolled Ledger, whose frame clips what hangs below it.
        if (!fitsBelow) tip.setAttribute('data-place', 'above');
        return;
      }
      // A hint that cannot fit inside what clips it on either side — the full
      // value of a long truncated file name inside a Ledger frame — would be
      // cut off wherever it is aligned, so it leaves that box: it wraps, and is
      // placed against the viewport beside its trigger (§16: the full value
      // must be readable).
      tip.setAttribute('data-float', '');
      const floated = tip.getBoundingClientRect();
      const width = floated.right - floated.left;
      const tall = floated.bottom - floated.top;
      const margin = FLOAT_MARGIN_PX;
      const left = Math.min(
        Math.max(anchor.left + (anchor.right - anchor.left) / 2 - width / 2, margin),
        Math.max(margin, window.innerWidth - margin - width),
      );
      const below = anchor.bottom + margin / 2;
      const top = below + tall <= window.innerHeight - margin
        ? below
        : Math.max(margin, anchor.top - margin / 2 - tall);
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [shown]);

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
      {/* In the document whenever there is something to say, so the
          description is there before it is shown; `hidden` keeps it off screen
          and out of the reading order. With nothing to say — a disabled
          control, a value that is not cut off — there is no hint element at
          all, and so no second copy of the trigger's own text. */}
      {inactive ? null : (
        <span ref={tipRef} className="tooltip" role="tooltip" id={id} hidden={!shown}>
          {content}
        </span>
      )}
    </span>
  );
}

/** The gap a floated hint keeps from the viewport edge. */
const FLOAT_MARGIN_PX = 8;

/** The motion token the delay is defined by, read from the stylesheet; 120ms where it is not loaded. */
function tooltipDelayMs(): number {
  const raw = typeof document === 'undefined'
    ? ''
    : getComputedStyle(document.documentElement).getPropertyValue('--dur').trim();
  const ms = raw.endsWith('ms') ? parseFloat(raw) : raw.endsWith('s') ? parseFloat(raw) * 1000 : NaN;
  return Number.isFinite(ms) && ms >= 0 ? ms : 120;
}

/** The extent a hint may occupy: the viewport, narrowed by every ancestor that clips it. */
function clippingBounds(element: HTMLElement): { left: number; right: number; top: number; bottom: number } {
  let left = 0;
  let top = 0;
  let right = typeof window === 'undefined' ? Number.POSITIVE_INFINITY : window.innerWidth;
  let bottom = typeof window === 'undefined' ? Number.POSITIVE_INFINITY : window.innerHeight;
  for (let node = element.parentElement; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    const clipsX = /(hidden|auto|scroll|clip)/.test(style.overflowX);
    const clipsY = /(hidden|auto|scroll|clip)/.test(style.overflowY);
    if (!clipsX && !clipsY) continue;
    const rect = node.getBoundingClientRect();
    if (clipsX) {
      left = Math.max(left, rect.left);
      right = Math.min(right, rect.right);
    }
    // jsdom lays nothing out; a zero-height box clips nothing.
    if (clipsY && rect.height > 0) {
      top = Math.max(top, rect.top);
      bottom = Math.min(bottom, rect.bottom);
    }
  }
  return { left, right, top, bottom };
}
