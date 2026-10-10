import {
  createContext,
  isValidElement,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

/**
 * One polite live region per slot, mounted before it has anything to say.
 *
 * A live region announces what *changes* inside it. A status presentation that
 * arrives already holding its sentence — the empty state a query resolves to,
 * the warning a failed refresh adds above retained rows — is an insertion, and
 * most screen readers say nothing about it (§23). So a slot renders its one
 * announcer from its first render, visually hidden and empty, and the
 * presentations that appear inside the slot report their text to it rather than
 * carrying `role="status"` of their own: the sentence then lands in a region
 * that was already there, as a change, once.
 *
 * Only polite statuses route this way. A failure (`Alert` tone `error`) keeps
 * `role="alert"`, which announces on insertion by definition, and nothing is
 * said twice.
 *
 * The store is per slot and outside React state on purpose: a reported sentence
 * re-renders the announcer span and nothing else, so a slot around a whole
 * stage costs its content nothing.
 */

type Listener = () => void;

type SlotStore = {
  /** The sentence on the announcer, or empty. `by` names the presentation that set it. */
  current: { by: symbol; text: string } | null;
  listeners: Set<Listener>;
  set(by: symbol, text: string): void;
  clear(by: symbol): void;
  subscribe(listener: Listener): () => void;
};

function createStore(): SlotStore {
  const store: SlotStore = {
    current: null,
    listeners: new Set(),
    set(by, text) {
      store.current = { by, text };
      store.listeners.forEach((listener) => listener());
    },
    clear(by) {
      // A presentation leaving must not erase what a later one just said.
      if (store.current?.by !== by) return;
      store.current = null;
      store.listeners.forEach((listener) => listener());
    },
    subscribe(listener) {
      store.listeners.add(listener);
      return () => store.listeners.delete(listener);
    },
  };
  return store;
}

const SlotContext = createContext<SlotStore | null>(null);

/** The plain text of a status node: what the announcer says. Controls are never copied. */
export function statusText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(statusText).join('');
  if (isValidElement<{ children?: ReactNode }>(node)) return statusText(node.props.children);
  return '';
}

/**
 * Reports a presentation's sentence to the nearest slot while it is shown.
 * Returns whether a slot took it: when none did (the presentation stands on
 * its own, outside any slot) the caller keeps its own live role.
 */
export function useStatusReport(
  text: string,
  active: boolean,
  /**
   * What the announcer says, read once the presentation is rendered, where
   * that differs from `text`: a sentence built from components that render
   * from their own props (a formatted time, a truncated value) reads fully
   * from the DOM where `text`, derived from the children, would not. `text`
   * remains the key on which a changed sentence is re-reported.
   */
  spoken?: () => string | null | undefined,
): boolean {
  const store = useContext(SlotContext);
  const by = useRef<symbol | null>(null);
  if (by.current === null) by.current = Symbol('status');
  const routed = store !== null && active;
  const latest = useRef(spoken);
  latest.current = spoken;
  useEffect(() => {
    if (!routed) return undefined;
    const id = by.current!;
    // In a later rendering frame than the commit that mounted the
    // presentation — and, on a slot's first render, the announcer itself.
    // Chromium updates the accessibility tree once per frame, and a region
    // that appears with its text in one frame is an insertion to that tree,
    // not a change; a frame later it is a change in a region that was already
    // there (§23). After the next frame, then one task on.
    let handle: number | undefined;
    const raf = typeof window.requestAnimationFrame === 'function'
      ? window.requestAnimationFrame.bind(window)
      : (callback: FrameRequestCallback) => window.setTimeout(() => callback(performance.now()), 16);
    const frame = raf(() => {
      handle = window.setTimeout(() => store.set(id, (latest.current?.() ?? '').trim() || text), 0);
    });
    return () => {
      if (typeof window.cancelAnimationFrame === 'function') window.cancelAnimationFrame(frame); else window.clearTimeout(frame);
      if (handle !== undefined) window.clearTimeout(handle);
      store.clear(id);
    };
  }, [store, routed, text]);
  return routed;
}

function Announcer({ store }: { store: SlotStore }) {
  const text = useSyncExternalStore(store.subscribe, () => store.current?.text ?? '');
  return <span className="visually-hidden status-slot__announcer" role="status">{text}</span>;
}

/**
 * The slot. Its announcer is its first child so it precedes, in reading order,
 * the presentation it speaks for.
 */
export default function StatusSlot({ children }: { children: ReactNode }) {
  const [store] = useState(createStore);
  return (
    <SlotContext.Provider value={store}>
      <Announcer store={store} />
      {children}
    </SlotContext.Provider>
  );
}
