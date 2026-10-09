/**
 * The focus mechanics the overlay primitives share (specification §15, §20,
 * §23): which elements can take focus, how Tab is kept inside an overlay, and
 * how the content an overlay covers is made inert and given back.
 *
 * Nothing here renders. Dialog and Drawer own their semantics; this owns only
 * the parts that would otherwise be written twice and drift.
 */

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'summary',
  'video[controls]',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(',');

/** The elements Tab can reach inside `container`, in document order. */
export function focusableWithin(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => !element.closest('[inert]') && !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true',
  );
}

/**
 * Keep a Tab press inside `container`: from the last element it wraps to the
 * first, from the first (with Shift) to the last, and from anywhere outside it
 * comes back in. Returns whether it handled the event.
 */
export function containTab(event: KeyboardEvent, container: HTMLElement): boolean {
  if (event.key !== 'Tab') return false;
  const focusable = focusableWithin(container);
  const active = document.activeElement as HTMLElement | null;
  if (focusable.length === 0) {
    event.preventDefault();
    container.focus();
    return true;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const inside = active !== null && container.contains(active);
  if (!inside) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
    return true;
  }
  if (event.shiftKey && (active === first || active === container)) {
    event.preventDefault();
    last.focus();
    return true;
  }
  if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
    return true;
  }
  return false;
}

/**
 * Make `elements` inert and return the function that gives them back.
 *
 * Only elements this call made inert are restored, so two overlays that touch
 * the same region — a dialog opened over a drawer — never un-inert something
 * the other still holds.
 */
export function makeInert(elements: readonly (HTMLElement | null | undefined)[]): () => void {
  const changed: HTMLElement[] = [];
  for (const element of elements) {
    if (!element || element.hasAttribute('inert')) continue;
    element.setAttribute('inert', '');
    changed.push(element);
  }
  return () => {
    for (const element of changed) element.removeAttribute('inert');
  };
}

/** Move focus to `target` if it is still in the document; otherwise leave focus where it is. */
export function restoreFocus(target: Element | null): void {
  if (target instanceof HTMLElement && target.isConnected && !target.closest('[inert]')) {
    target.focus();
  }
}

/**
 * Whether an open modal overlay other than the surface's own holds the
 * keyboard (§20: nothing behind an open overlay answers it). A surface's
 * window-level shortcuts — the Scene Editor's Delete and nudge, Search's J and
 * K — consult this first: the navigation overlay, an Investigation filter
 * drawer and a Dialog all cover the surface, and a key pressed in one of them
 * is not a key pressed on it. `own` names the surface's own overlay (its
 * inspector drawer), whose keys are the surface's by design.
 */
export function keyboardHeldElsewhere(own?: string): boolean {
  return Array.from(document.querySelectorAll('[aria-modal="true"]')).some((modal) => !(own && modal.matches(own)));
}
