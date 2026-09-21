import { useEffect, useRef } from 'react';

/**
 * One selection contract for both result presentations.
 *
 * List and Grid show the same set in two shapes, and before UI-4 they did not
 * agree on what selecting a result *is*. A row selected through a real button
 * carrying a class the page's key handler knew by name; a card selected through
 * an `onClick` on its `<article>`, which cannot be reached from a keyboard at
 * all and told assistive technology nothing. The keyboard shortcuts therefore
 * worked in one view and half-worked in the other, and the page's Enter handler
 * had a special case naming one view's private class.
 *
 * So the contract is stated here once and both views implement it: selecting a
 * result is pressing a button that carries `result-select` and the Track's
 * identifier. The page asks this module whether a control is such a button
 * rather than knowing either view's markup, which is what lets a third
 * presentation exist later without touching the key handler.
 */

/**
 * Keep the selected result in view.
 *
 * Part of the selection contract rather than of either view's markup: `j` and
 * `k` step the selection without moving focus, so the only thing that tells the
 * operator where they are is the selected result being on screen. The List had
 * this and the Grid did not, which meant the same keystroke in a dense Grid
 * updated the URL, the inspector and the highlight while scrolling none of them
 * into view (§22).
 *
 * `nearest` in both axes is what confines it: a result already visible is not
 * scrolled at all, and one that is not is brought in by the smallest movement
 * of the nearest scrollable ancestor — the results list. The page cannot be
 * scrolled by it, because §4.4 gives the Investigation shell `contain`.
 */
export function useKeepSelectedVisible<T extends HTMLElement>(selected: boolean) {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [selected]);
  return ref;
}

/** Marks the control whose purpose is "select this Track". */
export const SELECT_CONTROL_CLASS = 'result-select';

/** The identifier the control selects, on the control itself. */
export const TRACK_ID_ATTRIBUTE = 'data-track-id';

/** The props every selection control carries, whatever it looks like. */
export function selectControlProps(trackId: string, accessibleName: string, onSelect: (id: string) => void) {
  const id = trackId.toLowerCase();
  return {
    type: 'button' as const,
    className: SELECT_CONTROL_CLASS,
    [TRACK_ID_ATTRIBUTE]: id,
    'aria-label': accessibleName,
    onClick: () => onSelect(id),
  };
}

/**
 * Is this the selection control of the Track that is already selected?
 *
 * Enter opens the full review of the selected Track, and must not steal Enter
 * from a link, a filter button or the inspector's own controls. The one place
 * an operator presses Enter meaning "open this" is the control they just used
 * to select it — so that control, and only that one, passes.
 */
export function isSelectedResultControl(control: Element, selectedId: string | null): boolean {
  if (!selectedId) return false;
  return control.classList.contains(SELECT_CONTROL_CLASS)
    && control.getAttribute(TRACK_ID_ATTRIBUTE) === selectedId;
}

/** The selection control for a Track, if it is currently rendered. */
export function findSelectControl(selectedId: string | null, root: ParentNode = document): HTMLElement | null {
  if (!selectedId) return null;
  return root.querySelector<HTMLElement>(
    `.${SELECT_CONTROL_CLASS}[${TRACK_ID_ATTRIBUTE}="${CSS.escape(selectedId)}"]`,
  );
}
