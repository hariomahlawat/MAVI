import { useLayoutEffect, useState, type RefObject } from 'react';

/**
 * The rendered width of an element, kept in step with it, or null until it has
 * one. A width of zero is "not laid out" (a test environment, a hidden
 * subtree), never a measurement: a layout decision made from it would be made
 * from nothing.
 */
export function useElementWidth(ref: RefObject<HTMLElement | null>): number | null {
  const [width, setWidth] = useState<number | null>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const measure = (value: number) => setWidth(value > 0 ? value : null);
    measure(element.getBoundingClientRect().width);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (entry) measure(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}
