import {
  createContext,
  useCallback,
  useContext,
  useId,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

/**
 * The shell owns exactly one Context Bar.
 *
 * §5 says the topbar *becomes* the Context Bar — not that a page grows a second
 * bar underneath one. So the shell renders a single 44px band at the top of the
 * content column and hands its element to the page through this context; an
 * archetype renders its identity, state and actions *into* that band.
 *
 * A page that has not been migrated onto an archetype publishes nothing, and
 * the shell falls back to the section name it has always shown. The register of
 * owners is how the shell knows which case it is in, and is what makes "exactly
 * one bar" a property of the architecture rather than a convention.
 *
 * **Ownership is registered in the layout phase, not a passive effect.** The
 * first version claimed the slot from `useEffect`, which left the two halves of
 * one fact — "a surface published into the band" and "the shell has stopped
 * drawing its fallback" — in different commits. Between them the browser was
 * free to paint: two crumb trails on the way in, an empty band on the way out.
 * Registering from `useLayoutEffect` closes that, because React flushes state
 * updates scheduled during the layout phase before the browser paints, so the
 * intermediate commit exists but is never painted. The tests commit with
 * `flushSync` and read the DOM before passive effects run — which is the state
 * a paint would have shown, and is why they fail against the passive version.
 *
 * Ownership is keyed by a stable id rather than counted. A counter has to be
 * incremented and decremented in matching pairs, which turns StrictMode's
 * double invocation and any asymmetric cleanup into arithmetic that can drift;
 * a keyed register is idempotent under both, and cannot go negative because
 * there is no number to go negative.
 */

/**
 * The one state a whole surface can put its Context Bar into. It is not a
 * palette: `caution` says this surface is not the live thing it usually is —
 * a past revision open for reading — which is §27.1's read-only pattern, and
 * the only case the product has.
 */
export type ContextTone = 'caution';

/**
 * Which element is allowed to scroll a surface vertically (§4).
 *
 * `page` — the shell's content column scrolls, as it always has.
 * `contain` — it must not: this archetype names its own scroll owner, and the
 * page scrolling would break the grammar rather than extend it.
 *
 * This exists because the shell's `.main` is `overflow: auto` for every
 * surface, which left the Workbench's frozen no-page-scroll rule (§4.3.2)
 * true only for as long as its content happened to fit. The rule now lives in
 * the structure: the archetype declares the policy, the shell applies it, and
 * a page cannot reach it — the declaration is made by the layout component,
 * not by anything the page passes in.
 */
export type ScrollPolicy = 'page' | 'contain';

type SurfaceSlot = {
  /** The shell's Context Bar element, once it exists. */
  element: HTMLElement | null;
  /** True while a surface is rendering into the bar. */
  claimed: boolean;
  /** Declared by the owning surface; the shell, which owns the band, applies it. */
  tone: ContextTone | null;
  /**
   * Publishing and owning are one operation, so they are one call: a surface
   * registers when it has somewhere to publish and is publishing there, and the
   * tone travels with the registration rather than in a second effect that
   * could be left stale for a frame.
   */
  register: (id: string, tone: ContextTone | null) => void;
  unregister: (id: string) => void;
  /** The scroll policy the mounted archetype declares; `page` when none does. */
  scroll: ScrollPolicy;
  registerScroll: (id: string, policy: ScrollPolicy) => void;
  unregisterScroll: (id: string) => void;
};

const SurfaceSlotContext = createContext<SurfaceSlot | null>(null);

export function useSurfaceSlot(): SurfaceSlot | null {
  return useContext(SurfaceSlotContext);
}

/** What the shell needs in order to draw itself around the current surface. */
export type ShellSurface = {
  /** Attach to the shell's single Context Bar element. */
  attachContextBar: (element: HTMLElement | null) => void;
  /** True while a surface is publishing into the band. */
  claimed: boolean;
  tone: ContextTone | null;
  scroll: ScrollPolicy;
};

/**
 * A keyed register kept in the layout phase.
 *
 * Both of the shell's facts about the current surface — who owns the Context
 * Bar, and whether the page may scroll — are registered this way, through one
 * mechanism rather than two. They have the same failure mode if they are not:
 * a value that is a frame behind the surface it describes, or left stale after
 * the surface that set it has gone.
 */
function useRegister<T>(): [ReadonlyMap<string, T>, (id: string, value: T) => void, (id: string) => void] {
  const [entries, setEntries] = useState<ReadonlyMap<string, T>>(() => new Map());

  const add = useCallback((id: string, value: T) => {
    setEntries((current) => {
      if (current.has(id) && current.get(id) === value) return current;
      const next = new Map(current);
      // Deleting first keeps a re-registration at the end of the insertion
      // order, so "whichever surface holds this now" stays well defined rather
      // than depending on which key was written first.
      next.delete(id);
      next.set(id, value);
      return next;
    });
  }, []);

  const remove = useCallback((id: string) => {
    setEntries((current) => {
      if (!current.has(id)) return current;
      const next = new Map(current);
      next.delete(id);
      return next;
    });
  }, []);

  return [entries, add, remove];
}

/** The most recently registered value, which with one owner is simply its value. */
function latest<T>(entries: ReadonlyMap<string, T>, fallback: T): T {
  let last = fallback;
  for (const value of entries.values()) last = value;
  return last;
}

export function SurfaceSlotProvider({
  children,
}: {
  /** Receives everything the shell needs to draw itself around the surface. */
  children: (surface: ShellSurface) => ReactNode;
}) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [owners, register, unregister] = useRegister<ContextTone | null>();
  const [policies, registerScroll, unregisterScroll] = useRegister<ScrollPolicy>();

  // The band carries the tone of the surface that owns it, and the content
  // column the policy of the archetype mounted in it. With one of each — which
  // the architecture requires, and `workspace.test.tsx` asserts — both are
  // simply that surface's own value.
  const tone = useMemo(() => latest<ContextTone | null>(owners, null), [owners]);
  const scroll = useMemo(() => latest<ScrollPolicy>(policies, 'page'), [policies]);
  const claimed = owners.size > 0;

  const value = useMemo<SurfaceSlot>(
    () => ({ element, claimed, tone, register, unregister, scroll, registerScroll, unregisterScroll }),
    [element, claimed, tone, register, unregister, scroll, registerScroll, unregisterScroll],
  );

  return (
    <SurfaceSlotContext.Provider value={value}>
      {children({ attachContextBar: setElement, claimed, tone, scroll })}
    </SurfaceSlotContext.Provider>
  );
}

/**
 * An archetype declares how its surface scrolls.
 *
 * Called by the layout components in `layouts.tsx` and nowhere else: the policy
 * is a property of the archetype, so it is stated by the component that *is*
 * the archetype rather than passed in by the page that uses one. That is what
 * makes it something a page cannot opt out of.
 *
 * Registration is a layout effect for the same reason Context Bar ownership is:
 * a policy applied a frame late is a frame in which the wrong element could
 * scroll. Outside the shell — a layout rendered on its own in a test — there is
 * nothing to declare to, and this is inert.
 */
export function useScrollPolicy(policy: ScrollPolicy): void {
  const slot = useSurfaceSlot();
  const registerScroll = slot?.registerScroll;
  const unregisterScroll = slot?.unregisterScroll;
  const id = useId();

  useLayoutEffect(() => {
    if (!registerScroll || !unregisterScroll) return undefined;
    registerScroll(id, policy);
    return () => unregisterScroll(id);
  }, [registerScroll, unregisterScroll, id, policy]);
}
