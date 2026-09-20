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
 */
export function isNavigationTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return true;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'VIDEO') return false;
  return !target.isContentEditable;
}
