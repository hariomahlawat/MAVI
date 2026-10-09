import { act } from '@testing-library/react';

/**
 * A stand-in for `window.matchMedia` in jsdom, which has none. `matches`
 * decides each query; the returned function removes the stub.
 */
export function stubMatchMedia(matches: (query: string) => boolean): () => void {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({
    matches: matches(query),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  return () => {
    window.matchMedia = original;
  };
}

/**
 * A `window.matchMedia` stand-in whose answers the test changes mid-test, as
 * a resized window does: `set` swaps the decision and notifies every listener
 * the page subscribed (inside `act`, so React has committed when it returns).
 */
export function stubMatchMediaLive(initial: (query: string) => boolean): {
  set: (next: (query: string) => boolean) => void;
  restore: () => void;
} {
  let decide = initial;
  const listeners = new Map<string, Set<() => void>>();
  const listen = (query: string, listener: () => void) => {
    if (!listeners.has(query)) listeners.set(query, new Set());
    listeners.get(query)!.add(listener);
  };
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({
    get matches() {
      return decide(query);
    },
    media: query,
    onchange: null,
    addEventListener: (_type: string, listener: () => void) => listen(query, listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.get(query)?.delete(listener),
    addListener: (listener: () => void) => listen(query, listener),
    removeListener: (listener: () => void) => listeners.get(query)?.delete(listener),
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  return {
    set(next) {
      decide = next;
      act(() => {
        for (const set of listeners.values()) for (const listener of Array.from(set)) listener();
      });
    },
    restore() {
      window.matchMedia = original;
    },
  };
}
