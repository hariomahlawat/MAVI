import { useSyncExternalStore } from 'react';

/**
 * Whether a CSS media query currently matches, kept in step with the window.
 *
 * Used only where JavaScript has to know which presentation CSS chose — an
 * inspector that is an overlay at one width and a column at another — so the
 * query strings are the stylesheet's own breakpoints, and `workspace.test.tsx`
 * asserts they are. Where `matchMedia` does not exist (a test environment), the
 * answer is "no": the layout behaves as its in-flow presentation.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {};
      const list = window.matchMedia(query);
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    },
    () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : false),
    () => false,
  );
}

/** The widths at which an inspector is drawn over the workspace (workspace.css, §25). */
export const OVERLAY_QUERIES = {
  /** Investigation: a drawer from the stacking threshold up to the in-place threshold (§4.4). */
  investigation: '(min-width: 1101px) and (max-width: 1599px)',
  /** Workbench: a drawer only in the band where the stage cannot keep its floor beside it (§4.3.1). */
  workbench: '(min-width: 1101px) and (max-width: 1149px)',
} as const;
