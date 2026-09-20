import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

/**
 * The shell owns exactly one Context Bar.
 *
 * §5 says the topbar *becomes* the Context Bar — not that a page grows a second
 * bar underneath one. So the shell renders a single 44px band at the top of the
 * content column and hands its element to the page through this context; an
 * archetype renders its identity, state and actions *into* that band.
 *
 * A page that has not been migrated onto an archetype publishes nothing, and
 * the shell falls back to the section name it has always shown. The claim count
 * is how the shell knows which case it is in, and is what makes "exactly one
 * bar" a property of the architecture rather than a convention.
 */

/**
 * The one state a whole surface can put its Context Bar into. It is not a
 * palette: `caution` says this surface is not the live thing it usually is —
 * a past revision open for reading — which is §27.1's read-only pattern, and
 * the only case the product has.
 */
export type ContextTone = 'caution';

type SurfaceSlot = {
  /** The shell's Context Bar element, once it exists. */
  element: HTMLElement | null;
  /** True while a surface is rendering into the bar. */
  claimed: boolean;
  /** Set by the surface; the shell, which owns the band, applies it. */
  tone: ContextTone | null;
  claim: () => void;
  release: () => void;
  setTone: (tone: ContextTone | null) => void;
};

const SurfaceSlotContext = createContext<SurfaceSlot | null>(null);

export function useSurfaceSlot(): SurfaceSlot | null {
  return useContext(SurfaceSlotContext);
}

export function SurfaceSlotProvider({
  children,
}: {
  /** Receives the ref callback to attach to the shell's Context Bar element. */
  children: (
    attach: (element: HTMLElement | null) => void,
    claimed: boolean,
    tone: ContextTone | null,
  ) => ReactNode;
}) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [claims, setClaims] = useState(0);
  const [tone, setTone] = useState<ContextTone | null>(null);

  const claim = useCallback(() => setClaims((count) => count + 1), []);
  const release = useCallback(() => setClaims((count) => Math.max(0, count - 1)), []);

  const value = useMemo<SurfaceSlot>(
    () => ({ element, claimed: claims > 0, tone, claim, release, setTone }),
    [element, claims, tone, claim, release],
  );

  return (
    <SurfaceSlotContext.Provider value={value}>
      {children(setElement, claims > 0, tone)}
    </SurfaceSlotContext.Provider>
  );
}
