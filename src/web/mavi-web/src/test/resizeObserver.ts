/**
 * A stand-in for `ResizeObserver` in jsdom, which has none and lays nothing
 * out: every observed element reports `width`. Returns the function that
 * removes the stub.
 */
export function stubElementWidth(width: number): () => void {
  const original = globalThis.ResizeObserver;
  class FakeResizeObserver {
    private readonly callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }
    observe(target: Element) {
      this.callback([{ target, contentRect: { width } as DOMRectReadOnly } as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = FakeResizeObserver as unknown as typeof ResizeObserver;
  return () => {
    globalThis.ResizeObserver = original;
  };
}
