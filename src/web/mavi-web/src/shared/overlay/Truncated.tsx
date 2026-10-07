import { useCallback, useLayoutEffect, useState, type ReactNode } from 'react';
import Tooltip from './Tooltip';

/**
 * Whether an element's text is currently cut off by its own width.
 *
 * Measured, not assumed: whether a camera name truncates depends on the name,
 * the column cap and the viewport, so the answer is read from the rendered
 * box and re-read whenever that box changes size.
 */
export function useIsTruncated<T extends HTMLElement>(content: unknown): [(element: T | null) => void, boolean] {
  const [element, setElement] = useState<T | null>(null);
  const [truncated, setTruncated] = useState(false);
  const attach = useCallback((node: T | null) => setElement(node), []);

  useLayoutEffect(() => {
    if (!element) return undefined;
    const measure = () => setTruncated(element.scrollWidth > element.clientWidth + 0.5);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, content]);

  return [attach, truncated];
}

/**
 * A value that may be cut off, with its full text reachable by pointer and
 * keyboard (§16, §36.2 truncation; §27 Tooltip).
 *
 * `title` alone is pointer-only, which §16 forbids. So while — and only while —
 * the value is actually truncated it joins the tab order and carries the full
 * text as a tooltip on hover and focus; a value that fits is plain text, adds
 * no tab stop and repeats nothing. A Ledger row therefore gains a stop only
 * for the cells an operator could not otherwise read.
 */
export default function TruncatedText({
  text,
  className,
  children,
}: {
  /** The full value. */
  text: string;
  /** The column cap (`cap-sm`, `cap-md`, `cap-lg`) or other sizing class. */
  className?: string;
  /** What is drawn, when richer than the plain value (a bold code beside a name). */
  children?: ReactNode;
}) {
  const [attach, truncated] = useIsTruncated<HTMLSpanElement>(text);
  return (
    <Tooltip content={text} enabled={truncated}>
      <span
        ref={attach}
        className={['truncate', className].filter(Boolean).join(' ')}
        tabIndex={truncated ? 0 : undefined}
      >
        {children ?? text}
      </span>
    </Tooltip>
  );
}
