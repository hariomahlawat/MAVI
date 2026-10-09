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

/**
 * The shell's Tier B composition (§25 Shell row): below the Tier A workstation
 * width the rail is collapsed by default and opens as an overlay. This is the
 * one place the shell reads a tier: §25 states the rail's default per tier, so
 * the boundary is the frozen row's own, not a layout breakpoint (layout.css).
 */
export const SHELL_QUERIES = {
  compact: '(max-width: 1365px)',
} as const;

/** The widths at which an inspector is drawn over the workspace (workspace.css, §25). */
export const OVERLAY_QUERIES = {
  /**
   * Investigation: a drawer at every width below the in-place threshold (§4.4;
   * §25 Tier B: "inspector as a drawer" in both the 1101-1365 and the
   * 768-1100 compositions).
   */
  investigation: '(max-width: 1599px)',
  /**
   * Investigation, stacked (§25 Tier B, 768-1100): the filter rail leaves the
   * grid and becomes a drawer opened from the results header. The shared §4
   * stacking threshold, unchanged.
   */
  investigationStacked: '(max-width: 1100px)',
  /**
   * Workbench, stacked (§4 shared rule, §25 Tier B 768-1100): stage first,
   * inspector below. Whether the inspector is a drawer *above* this is not a
   * viewport question — it is the §4.3.1 floor, decided from the measured
   * working width (`WORKBENCH_SIDE_BY_SIDE_MIN`, layouts.tsx).
   */
  workbenchStacked: '(max-width: 1100px)',
} as const;
