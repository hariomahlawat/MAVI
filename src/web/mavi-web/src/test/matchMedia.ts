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
