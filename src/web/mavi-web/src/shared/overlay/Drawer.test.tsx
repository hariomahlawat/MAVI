import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import Dialog from './Dialog';
import Drawer from './Drawer';

let toggleWidth: () => void = () => {};
let showNotice: () => void = () => {};

function Harness({ overlay: initialOverlay = true }: { overlay?: boolean }) {
  const [open, setOpen] = useState(false);
  const [overlay, setOverlay] = useState(initialOverlay);
  const [confirming, setConfirming] = useState(false);
  const coveredRef = useRef<HTMLDivElement | null>(null);
  toggleWidth = () => setOverlay((value) => !value);
  const [notice, setNotice] = useState(false);
  showNotice = () => setNotice(true);
  const noticeRef = useRef<HTMLDivElement | null>(null);
  return (
    <div>
      {notice ? (
        <div ref={noticeRef} data-testid="late-notice"><button type="button">Retry</button></div>
      ) : null}
      <div ref={coveredRef} data-testid="covered">
        <button type="button" onClick={() => setOpen(true)}>Inspect</button>
        <button type="button">Covered action</button>
      </div>
      <Drawer open={open} overlay={overlay} onClose={() => setOpen(false)} covers={[coveredRef, noticeRef]} className="inspector">
        <h2>Track 42</h2>
        <p>Plain detail text</p>
        <label>
          Note
          <input defaultValue="" />
        </label>
        <button type="button" onClick={() => setConfirming(true)}>Discard</button>
        <button type="button" onClick={() => setOpen(false)}>Close</button>
      </Drawer>
      <Dialog open={confirming} title="Discard?" confirmLabel="Discard now" onConfirm={() => setConfirming(false)} onCancel={() => setConfirming(false)}>
        Gone.
      </Dialog>
    </div>
  );
}

async function openDrawer(overlay = true) {
  const user = userEvent.setup();
  render(<Harness overlay={overlay} />);
  const invoker = screen.getByRole('button', { name: 'Inspect' });
  await user.click(invoker);
  return { user, invoker };
}

describe('Drawer', () => {
  it('moves focus to its heading, which names it, when it opens as an overlay', async () => {
    await openDrawer();
    const heading = screen.getByRole('heading', { name: 'Track 42' });
    expect(heading).toHaveFocus();
    const drawer = screen.getByRole('dialog', { name: 'Track 42' });
    expect(drawer).toHaveAttribute('aria-modal', 'true');
    // The heading is focusable by script only: it never joins the Tab sequence.
    expect(heading).toHaveAttribute('tabindex', '-1');
  });

  it('keeps Tab inside in both directions: nothing behind it is reachable', async () => {
    const { user } = await openDrawer();
    const drawer = screen.getByRole('dialog');
    for (let i = 0; i < 7; i += 1) {
      await user.tab();
      expect(drawer.contains(document.activeElement)).toBe(true);
    }
    for (let i = 0; i < 7; i += 1) {
      await user.tab({ shift: true });
      expect(drawer.contains(document.activeElement)).toBe(true);
    }
  });

  it('keeps Shift+Tab inside from the heading it focused on opening, before any of its controls (T1, PR #199)', async () => {
    const { user } = await openDrawer();
    expect(screen.getByRole('heading', { name: 'Track 42' })).toHaveFocus();
    // Reverse from the heading: no control precedes it, so the step wraps to
    // the last control — never to "Covered action" behind the drawer.
    await user.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
  });

  it('steps from a focused heading by document order, forward and back, when controls surround it', async () => {
    const user = userEvent.setup();
    function Surrounded() {
      const [open, setOpen] = useState(false);
      const coveredRef = useRef<HTMLDivElement | null>(null);
      return (
        <div>
          <div ref={coveredRef}><button type="button" onClick={() => setOpen(true)}>Inspect</button></div>
          <Drawer open={open} overlay onClose={() => setOpen(false)} covers={[coveredRef]} className="inspector">
            <button type="button" onClick={() => setOpen(false)}>Close inspector</button>
            <h2>Scene objects</h2>
            <button type="button">Zone A</button>
            <button type="button">Zone B</button>
          </Drawer>
        </div>
      );
    }
    render(<Surrounded />);
    await user.click(screen.getByRole('button', { name: 'Inspect' }));
    expect(screen.getByRole('heading', { name: 'Scene objects' })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Close inspector' })).toHaveFocus();
    screen.getByRole('heading', { name: 'Scene objects' }).focus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Zone A' })).toHaveFocus();
  });

  it('keeps focus in a panel that stays in place when the window leaves the overlay range and takes the invoker with it', async () => {
    // The Investigation filters at ≤1100: the invoker lives in the results
    // header only while the rail is a drawer, and the drawer's head (its
    // heading, which holds focus on opening) only while it is one.
    const user = userEvent.setup();
    let widen: () => void = () => {};
    function Filters() {
      const [stacked, setStacked] = useState(true);
      const [open, setOpen] = useState(false);
      widen = () => setStacked(false);
      const resultsRef = useRef<HTMLDivElement | null>(null);
      return (
        <div>
          <div ref={resultsRef}>{stacked ? <button type="button" onClick={() => setOpen(true)}>Filters</button> : null}</div>
          <Drawer open={open || !stacked} overlay={stacked} onClose={() => setOpen(false)} covers={[resultsRef]} className="rail">
            {stacked ? <h2>Filters</h2> : null}
            <label>Camera<select><option>Any camera</option></select></label>
          </Drawer>
        </div>
      );
    }
    render(<Filters />);
    await user.click(screen.getByRole('button', { name: 'Filters' }));
    expect(screen.getByRole('heading', { name: 'Filters' })).toHaveFocus();
    act(() => widen());
    expect(screen.getByRole('combobox', { name: 'Camera' })).toHaveFocus();
  });

  it('closes on Escape and returns focus to the invoker', async () => {
    const { user, invoker } = await openDrawer();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(invoker).toHaveFocus();
  });

  it('returns focus to the invoker when closed from its own control', async () => {
    const { user, invoker } = await openDrawer();
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(invoker).toHaveFocus();
  });

  it('makes the covered region inert while open, and gives it back', async () => {
    const { user } = await openDrawer();
    const covered = screen.getByTestId('covered');
    expect(covered).toHaveAttribute('inert');
    await user.keyboard('{Escape}');
    expect(covered).not.toHaveAttribute('inert');
  });

  it('makes a covered region that mounts while it is open inert too, and releases it on close', async () => {
    const { user } = await openDrawer();
    act(() => showNotice());
    const notice = screen.getByTestId('late-notice');
    expect(notice).toHaveAttribute('inert');
    expect(screen.getByTestId('covered')).toHaveAttribute('inert');
    await user.keyboard('{Escape}');
    expect(notice).not.toHaveAttribute('inert');
    expect(screen.getByTestId('covered')).not.toHaveAttribute('inert');
  });

  it('closes when the scrim over the covered region is clicked', async () => {
    const { user } = await openDrawer();
    const scrim = document.querySelector<HTMLElement>('.drawer-scrim');
    expect(scrim).toHaveAttribute('aria-hidden', 'true');
    await user.click(scrim!);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('claims no drawer semantics in place: no dialog, no trap, nothing inert, no focus move', async () => {
    const onEscape = vi.fn();
    window.addEventListener('keydown', onEscape);
    try {
      const { user, invoker } = await openDrawer(false);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(document.querySelector('[aria-modal]')).toBeNull();
      expect(document.querySelector('[inert]')).toBeNull();
      expect(document.querySelector('.drawer-scrim')).toBeNull();
      expect(invoker).toHaveFocus();
      // Escape is the surface's own, untouched.
      await user.keyboard('{Escape}');
      expect(onEscape).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('heading', { name: 'Track 42' })).toBeInTheDocument();
    } finally {
      window.removeEventListener('keydown', onEscape);
    }
  });

  it('keeps its content when the presentation switches under it', async () => {
    const { user } = await openDrawer();
    const input = screen.getByRole('textbox', { name: 'Note' });
    await user.type(input, 'kept');

    act(() => toggleWidth()); // overlay -> in place
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('covered')).not.toHaveAttribute('inert');
    expect(document.querySelector('.drawer-scrim')).toBeNull();
    expect(screen.getByRole('textbox', { name: 'Note' })).toBe(input);
    expect(input).toHaveValue('kept');

    act(() => toggleWidth()); // in place -> overlay
    expect(screen.getByRole('dialog', { name: 'Track 42' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Note' })).toBe(input);
    expect(input).toHaveValue('kept');
  });

  it('closes on Escape from a field inside it too (§20: the way out never depends on focus)', async () => {
    const { user, invoker } = await openDrawer();
    await user.click(screen.getByRole('textbox', { name: 'Note' }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(invoker).toHaveFocus();
  });

  it('takes focus itself, not the document, when plain text inside it is clicked', async () => {
    const { user } = await openDrawer();
    const drawer = screen.getByRole('dialog');
    await user.click(screen.getByText('Plain detail text'));
    expect(drawer).toHaveFocus();
    // And it is not in the Tab sequence.
    expect(drawer).toHaveAttribute('tabindex', '-1');
  });

  it('lets a dialog over it own Escape: the dialog cancels and the drawer stays open', async () => {
    const { user } = await openDrawer();
    await user.click(screen.getByRole('button', { name: 'Discard' }));
    expect(screen.getByRole('dialog', { name: 'Discard?' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Discard?' })).not.toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Track 42' })).toBeInTheDocument();
    // Focus came back into the drawer, and the covered region is still inert.
    expect(screen.getByRole('button', { name: 'Discard' })).toHaveFocus();
    expect(screen.getByTestId('covered')).toHaveAttribute('inert');
  });
});
