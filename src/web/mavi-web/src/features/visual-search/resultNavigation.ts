import { isInsideEvidencePlayer } from '../../shared/evidence/EvidencePlayer';
import type { TrackSearchItem } from '../../api/tracks';

/** Position of the selected Track in the loaded results, or -1. */
export function selectedIndex(items: readonly TrackSearchItem[], selectedId: string | null): number {
  if (!selectedId) return -1;
  const wanted = selectedId.toLowerCase();
  return items.findIndex((item) => item.id.toLowerCase() === wanted);
}

/**
 * The neighbouring Track id in the given direction, or null at either edge.
 * Moving past the last loaded item is the caller's cue to fetch the next page.
 */
export function neighbourId(
  items: readonly TrackSearchItem[],
  selectedId: string | null,
  direction: 1 | -1,
): string | null {
  const index = selectedIndex(items, selectedId);
  if (index === -1) return items.length > 0 && direction === 1 ? items[0].id.toLowerCase() : null;
  const next = index + direction;
  if (next < 0 || next >= items.length) return null;
  return items[next].id.toLowerCase();
}

/** Prefetch the next page when the operator is within `margin` rows of the end. */
export function nearEnd(items: readonly TrackSearchItem[], selectedId: string | null, margin = 3): boolean {
  const index = selectedIndex(items, selectedId);
  return index >= 0 && items.length - index <= margin;
}

/**
 * Whether a keyboard event should drive result navigation. Typing in a form
 * control must never be hijacked.
 *
 * Neither must the Evidence Player. Result navigation binds `j` and `k` on the
 * window and the player's frozen grammar binds `J` and `L` for one second
 * either way, so a key press inside the player would otherwise both nudge the
 * media and move the selection. The player's subtree is refused here, which
 * leaves each key with exactly one meaning depending on where focus is.
 */
export function isNavigationTarget(target: EventTarget | null): boolean {
  // Before the HTML check, because the player's overlay stage is SVG.
  if (isInsideEvidencePlayer(target)) return false;
  return isDismissTarget(target);
}

/**
 * Whether Escape may close the inspector from this target.
 *
 * Wider than {@link isNavigationTarget} by exactly the evidence subtree. The
 * subtree is refused for navigation because the player's grammar owns J and L,
 * but no evidence grammar binds Escape, so refusing it there only left the
 * operator unable to close the inspector while focus was on the player or on
 * the Evidence Set (S1.3 plan §20.2). Typing contexts still keep the key.
 */
export function isDismissTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return true;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'VIDEO') return false;
  return !target.isContentEditable;
}
