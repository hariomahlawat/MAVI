import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import Drawer from '../overlay/Drawer';
import { OVERLAY_QUERIES, SHELL_QUERIES } from '../overlay/useMediaQuery';
import { LedgerSortSelect, useLedgerSort } from '../table';
import { stubMatchMedia } from '../../test/matchMedia';
import { stubElementWidth } from '../../test/resizeObserver';
import { InvestigationLayout, InvestigationRailToggle, LedgerLayout, LedgerTable, WORKBENCH_SIDE_BY_SIDE_MIN, WorkbenchLayout } from './layouts';
import { LedgerFoldedValue, LedgerPrimary } from './LedgerFold';

/** Every Workbench states its §25 Tier C fallback; these tests are above Tier C. */
const TEST_UNSUPPORTED = { statement: 'Needs a display at least 768px wide.', summary: null };

/*
 * T1 (§25 Tier B): the shared pieces the compact compositions are made of —
 * each proven here on its own, so a surface that uses one inherits a contract
 * rather than re-proving it.
 */

let unstub: () => void = () => {};
afterEach(() => unstub());

function Search() {
  return (
    <InvestigationLayout rail={<label>Camera<select><option>All</option></select></label>}>
      <section aria-label="Search results">
        <div className="results__head"><strong>6 Tracks</strong><InvestigationRailToggle /></div>
        <button type="button">A result</button>
      </section>
    </InvestigationLayout>
  );
}

describe('Investigation stacked (§25 Tier B, 768-1100)', () => {
  it('moves focus from the in-place rail to the Filters control when the window narrows into the stacked composition', () => {
    // A matchMedia stand-in whose answer the test changes, notifying listeners
    // as a resized window does.
    const original = window.matchMedia;
    let stacked = false;
    const listeners = new Set<() => void>();
    window.matchMedia = ((query: string) => ({
      get matches() { return stacked && (query === OVERLAY_QUERIES.investigationStacked || query === OVERLAY_QUERIES.investigation); },
      media: query, onchange: null,
      addEventListener: (_: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    try {
      render(<Search />);
      screen.getByRole('combobox', { name: 'Camera' }).focus();
      act(() => {
        stacked = true;
        for (const listener of Array.from(listeners)) listener();
      });
      expect(screen.getByRole('button', { name: 'Filters' })).toHaveFocus();
    } finally {
      window.matchMedia = original;
    }
  });

  it('puts the filters behind a control in the results header, opens them as a named modal drawer, and returns focus on Escape', async () => {
    unstub = stubMatchMedia((query) => query === OVERLAY_QUERIES.investigationStacked || query === OVERLAY_QUERIES.investigation);
    const user = userEvent.setup();
    const { container } = render(<Search />);

    const results = screen.getByRole('region', { name: 'Search results' });
    const toggle = within(results).getByRole('button', { name: 'Filters' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(container.querySelector('.workspace--investigation')).toHaveClass('is-stacked');
    expect(container.querySelector('.workspace--investigation')).not.toHaveClass('has-open-rail');

    await user.click(toggle);
    const drawer = screen.getByRole('dialog', { name: 'Filters' });
    expect(drawer).toHaveAttribute('aria-modal', 'true');
    expect(drawer).toContainElement(screen.getByLabelText('Camera'));
    // The results it covers are inert while it is open.
    expect(container.querySelector('.workspace__results')).toHaveAttribute('inert');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Filters' })).not.toBeInTheDocument();
    expect(container.querySelector('.workspace__results')).not.toHaveAttribute('inert');
    expect(within(results).getByRole('button', { name: 'Filters' })).toHaveFocus();
  });

  it('closes from its own named control too', async () => {
    unstub = stubMatchMedia((query) => query === OVERLAY_QUERIES.investigationStacked);
    const user = userEvent.setup();
    render(<Search />);
    await user.click(screen.getByRole('button', { name: 'Filters' }));
    await user.click(screen.getByRole('button', { name: 'Close filters' }));
    expect(screen.queryByRole('dialog', { name: 'Filters' })).not.toBeInTheDocument();
  });

  it('keeps the rail in place, with no toggle and no modality, above the stacking threshold', () => {
    unstub = stubMatchMedia((query) => query === OVERLAY_QUERIES.investigation);
    render(<Search />);
    expect(screen.queryByRole('button', { name: 'Filters' })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Camera')).toBeVisible();
  });
});

function Viewport() {
  const [open, setOpen] = useState(false);
  const ownRef = useRef<HTMLDivElement | null>(null);
  return (
    <div>
      <nav data-testid="shell-rail"><a href="#x">Overview</a></nav>
      <div data-testid="context-bar"><button type="button">Save</button></div>
      <div data-testid="column">
        <button type="button" onClick={() => setOpen(true)}>Open</button>
        <Drawer open={open} overlay onClose={() => setOpen(false)} covers={[ownRef]} coversViewport className="drawer">
          <h2>Inspector</h2>
          <button type="button" onClick={() => setOpen(false)}>Close</button>
        </Drawer>
      </div>
    </div>
  );
}

describe('a Drawer drawn over the viewport (§20, §25 Tier B)', () => {
  it('makes everything outside it inert — the shell and the Context Bar included — but keeps its scrim live', async () => {
    const user = userEvent.setup();
    const { container } = render(<Viewport />);
    await user.click(screen.getByRole('button', { name: 'Open' }));

    expect(screen.getByTestId('shell-rail')).toHaveAttribute('inert');
    expect(screen.getByTestId('context-bar')).toHaveAttribute('inert');
    expect(screen.getByRole('button', { name: 'Open', hidden: true })).toHaveAttribute('inert');
    expect(container.querySelector('.drawer-scrim')).not.toHaveAttribute('inert');
    expect(screen.getByRole('dialog', { name: 'Inspector' })).not.toHaveAttribute('inert');

    await user.click(container.querySelector('.drawer-scrim') as HTMLElement);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    for (const id of ['shell-rail', 'context-bar']) expect(screen.getByTestId(id)).not.toHaveAttribute('inert');
  });
});

function Sorted() {
  const sort = useLedgerSort<'recorded' | 'file'>({ column: 'recorded', direction: 'desc' });
  return (
    <>
      <LedgerSortSelect
        sort={sort}
        options={[
          { column: 'recorded', label: 'Recorded', ascending: 'oldest first', descending: 'newest first' },
          { column: 'file', label: 'File', ascending: 'A to Z', descending: 'Z to A' },
        ]}
      />
      <output>{`${sort.state.column}:${sort.state.direction}`}</output>
    </>
  );
}

describe('folded Ledger columns (§25 Tier B)', () => {
  it('keep every sort reachable through one select while their headers are folded', async () => {
    const user = userEvent.setup();
    render(<Sorted />);
    const select = screen.getByLabelText('Sort');
    expect(select).toHaveValue('recorded:desc');
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Recorded, oldest first', 'Recorded, newest first', 'File, A to Z', 'File, Z to A',
    ]);
    await user.selectOptions(select, 'file:asc');
    expect(screen.getByRole('status')).toHaveTextContent('file:asc');
  });

  it('name each folded value for assistive technology, since its header is gone', () => {
    render(
      <table><tbody><tr><td>
        <LedgerPrimary
          identity={<span>clip.mp4</span>}
          folded={<><LedgerFoldedValue name="Recorded">14 Sept, 08:35</LedgerFoldedValue><LedgerFoldedValue name="Duration">10m 00s</LedgerFoldedValue></>}
        />
      </td></tr></tbody></table>,
    );
    expect(screen.getByRole('cell')).toHaveTextContent('clip.mp4Recorded 14 Sept, 08:35Duration 10m 00s');
  });

  // jsdom lays nothing out, so the table's rendered width is stated: the
  // frame holds `frame` pixels of a table `table` pixels wide.
  function measuredLedger(frame: number, table: number) {
    const own = (name: 'scrollWidth' | 'clientWidth', value: number) =>
      Object.getOwnPropertyDescriptor(HTMLElement.prototype, name) ?? { configurable: true, get: () => value };
    const restore = [own('scrollWidth', 0), own('clientWidth', 0)];
    Object.defineProperty(HTMLElement.prototype, 'scrollWidth', { configurable: true, get() { return this.classList.contains('ledger-table') ? table : 0; } });
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return this.classList.contains('ledger-table') ? frame : 0; } });
    return () => {
      Object.defineProperty(HTMLElement.prototype, 'scrollWidth', restore[0]);
      Object.defineProperty(HTMLElement.prototype, 'clientWidth', restore[1]);
    };
  }
  const Cameras = () => (
    <main>
      <LedgerLayout>
        <LedgerTable caption="Cameras" fold="cameras">
          <thead><tr><th>Name</th><th className="ledger-fold">Timezone</th></tr></thead>
          <tbody><tr><td>Gate 4 - a long camera name</td><td className="ledger-fold">Asia/Kolkata</td></tr></tbody>
        </LedgerTable>
      </LedgerLayout>
    </main>
  );

  it('fold wherever the rendered table does not fit its frame in the compact shell, not only below the base inventory width', () => {
    const unmeasure = measuredLedger(926, 1010);
    unstub = stubMatchMedia((query) => query === SHELL_QUERIES.compact);
    try {
      const { container } = render(<Cameras />);
      expect(container.querySelector('.workspace--ledger')).toHaveAttribute('data-fold', 'overflow');
    } finally {
      unmeasure();
    }
  });

  it('stay unfolded where the table fits, and at Tier A, where every column shows and the body scrolls (§4.1)', () => {
    let unmeasure = measuredLedger(926, 900);
    unstub = stubMatchMedia((query) => query === SHELL_QUERIES.compact);
    try {
      const { container, unmount } = render(<Cameras />);
      expect(container.querySelector('.workspace--ledger')).not.toHaveAttribute('data-fold');
      unmount();
    } finally {
      unmeasure();
      unstub();
    }
    unmeasure = measuredLedger(926, 1010);
    unstub = stubMatchMedia(() => false);
    try {
      const { container } = render(<Cameras />);
      expect(container.querySelector('.workspace--ledger')).not.toHaveAttribute('data-fold');
    } finally {
      unmeasure();
    }
  });
});

describe('the Workbench drawer: the frozen 1101-1149 band and the §4.3.1 floor, two obligations', () => {
  const drawerAt = (width: number) => {
    unstub = stubElementWidth(width);
    const { container, unmount } = render(<WorkbenchLayout unsupported={TEST_UNSUPPORTED} stage={<canvas />} inspector={<p>inspector</p>} />);
    const drawer = container.querySelector('.workspace--workbench')?.classList.contains('is-drawer');
    unmount();
    unstub();
    return drawer;
  };

  it('keeps the inspector beside the stage wherever the stage holds 65% beside it, and is a drawer only below that', () => {
    // (300 + 12) / 0.35: the working width the floor needs.
    expect(WORKBENCH_SIDE_BY_SIDE_MIN).toBeCloseTo(891.43, 1);
    // 1101px under the Tier B shell (56px rail, 40px gutters): side by side.
    expect(drawerAt(1005)).toBe(false);
    expect(drawerAt(892)).toBe(false);
    expect(drawerAt(891)).toBe(true);
    expect(drawerAt(850)).toBe(true);
  });

  it('moves focus from the in-flow inspector to the drawer toggle when the window enters the drawer composition', () => {
    // A ResizeObserver stand-in the test drives: the working width shrinks
    // under the floor while focus is in the side-by-side inspector.
    const original = globalThis.ResizeObserver;
    let resize: (width: number) => void = () => {};
    globalThis.ResizeObserver = class {
      private readonly callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) { this.callback = callback; }
      observe(target: Element) {
        resize = (width) => this.callback([{ target, contentRect: { width } as DOMRectReadOnly } as ResizeObserverEntry], this as unknown as ResizeObserver);
        resize(1005);
      }
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    try {
      render(<WorkbenchLayout unsupported={TEST_UNSUPPORTED} stage={<canvas />} inspector={<button type="button">Loading bay</button>} inspectorLabel="Scene inspector" />);
      screen.getByRole('button', { name: 'Loading bay' }).focus();
      act(() => resize(850));
      expect(screen.getByRole('button', { name: 'Scene inspector' })).toHaveFocus();
    } finally {
      globalThis.ResizeObserver = original;
    }
  });

  it('is a drawer throughout the frozen 1101-1149 band even where the floor alone would allow side by side (§25 Tier B)', () => {
    // 1101px under the Tier B shell: about 1005px of working width.
    const restore = stubMatchMedia((query) => query === OVERLAY_QUERIES.workbenchDrawerBand);
    try {
      expect(drawerAt(1005)).toBe(true);
    } finally {
      restore();
    }
    // Stacked (≤1100) wins over the band: the inspector is below the stage, not a drawer.
    const stacked = stubMatchMedia((query) => query === OVERLAY_QUERIES.workbenchDrawerBand || query === OVERLAY_QUERIES.workbenchStacked);
    try {
      expect(drawerAt(1005)).toBe(false);
    } finally {
      stacked();
    }
  });
});
