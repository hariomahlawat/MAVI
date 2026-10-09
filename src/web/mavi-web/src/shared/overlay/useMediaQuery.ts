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
  compact: '(width < 1366px)',
  /**
   * Tier C (§25: 390px ≤ width < 768px): the rail is a top-of-page menu
   * control opening the navigation as an overlay. The tier's own boundary —
   * the legacy 760px narrow shell is gone, so 761-767 is Tier C like the rest.
   */
  narrow: '(width < 768px)',
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
   * inspector below.
   */
  workbenchStacked: '(max-width: 1100px)',
  /**
   * Workbench, the frozen drawer band (§4.3.1, §25 Tier B: "1101px up to the
   * measured ~1150 threshold", measured in R4 as 1150): the inspector is an
   * overlay drawer here whatever the shell's rail does. The §4.3.1 floor is a
   * separate obligation, decided from the measured working width
   * (`WORKBENCH_SIDE_BY_SIDE_MIN`, layouts.tsx), and also makes it a drawer
   * wherever the stage could not keep 65% beside it.
   */
  workbenchDrawerBand: '(width > 1100px) and (width < 1150px)',
} as const;
