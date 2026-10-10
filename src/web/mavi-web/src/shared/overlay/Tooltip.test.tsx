import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Tooltip from './Tooltip';

function Harness() {
  return (
    <div>
      <button type="button">Before</button>
      <Tooltip content="Next result · j or ↓">
        <button type="button" aria-label="Next result">›</button>
      </Tooltip>
    </div>
  );
}

describe('Tooltip', () => {
  it('is hidden until asked for', () => {
    render(<Harness />);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('opens on keyboard focus without taking focus', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.tab();
    await user.tab();
    const trigger = screen.getByRole('button', { name: 'Next result' });
    expect(trigger).toHaveFocus();
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Next result · j or ↓');
    expect(trigger).toHaveFocus();
  });

  it('opens on pointer hover and closes when the pointer leaves', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Next result' });
    await user.hover(trigger);
    expect(await screen.findByRole('tooltip')).toBeVisible();
    await user.unhover(trigger);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('is the description, never the name: the control keeps its own accessible name', () => {
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Next result' });
    expect(trigger).toHaveAccessibleName('Next result');
    expect(trigger).toHaveAccessibleDescription('Next result · j or ↓');
  });

  it('keeps an existing description alongside its own', () => {
    render(
      <div>
        <p id="hint">Already described</p>
        <Tooltip content="Shortcut: k">
          <button type="button" aria-describedby="hint">Previous</button>
        </Tooltip>
      </div>,
    );
    expect(screen.getByRole('button', { name: 'Previous' })).toHaveAccessibleDescription('Already described Shortcut: k');
  });

  it('closes on Escape without moving focus, and on blur', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.tab();
    await user.tab();
    const trigger = screen.getByRole('button', { name: 'Next result' });
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.tab({ shift: true });
    await user.tab();
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();
    await user.tab({ shift: true });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('never appears on a disabled control, and does not describe one (§36.3)', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <Tooltip content="Previous result · k or ↑">
        <button type="button" disabled>Previous</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole('button', { name: 'Previous' });
    await user.hover(trigger.parentElement!);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(trigger).not.toHaveAttribute('aria-describedby');

    rerender(
      <Tooltip content="Previous result · k or ↑">
        <button type="button" aria-disabled="true">Previous</button>
      </Tooltip>,
    );
    trigger.focus();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    // Enabled again: the same element, now with its hint.
    rerender(
      <Tooltip content="Previous result · k or ↑">
        <button type="button">Previous</button>
      </Tooltip>,
    );
    expect(screen.getByRole('button', { name: 'Previous' })).toBe(trigger);
    expect(trigger).toHaveAccessibleDescription('Previous result · k or ↑');
  });

  it('stays open while either channel holds it: leaving the pointer keeps a focused hint, blurring keeps a hovered one', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Next result' });

    // Focus, then hover, then the pointer leaves: focus still holds it.
    await user.tab();
    await user.tab();
    await user.hover(trigger);
    await user.unhover(trigger);
    expect(trigger).toHaveFocus();
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();

    // Hover, then focus leaves: the pointer still holds it.
    await user.hover(trigger);
    await user.tab({ shift: true });
    expect(trigger).not.toHaveFocus();
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();

    // Both gone: closed.
    await user.unhover(trigger);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('waits one motion-token delay before showing, and never shows for a pointer that only crosses', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Next result' });

    // Crossing: in and out within the delay — no hint at all.
    await user.hover(trigger);
    await user.unhover(trigger);
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    // Resting: not on the same update, then after the delay.
    await user.hover(trigger);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();
  });

  it('aligns to the edge of what clips it instead of being cut off, and stays centred where it fits', async () => {
    const user = userEvent.setup();
    // jsdom does no layout: give the clipping column, the trigger's hint and
    // everything else the geometry of the inspector's Close button in
    // jsdom's 1024px viewport.
    // (jsdom does not expand the `overflow` shorthand either: the clipping
    // columns here set the longhands clippingBounds reads.)
    const rects = new Map<string, Partial<DOMRect>>([
      ['clip', { left: 216, right: 1024 }],
      ['tooltip', { left: 900, right: 1040 }],
      ['anchor', { left: 960, right: 1004 }],
    ]);
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const key = this.classList.contains('tooltip') ? 'tooltip' : this.classList.contains('tooltip-anchor') ? 'anchor' : this.dataset.testid === 'clip' ? 'clip' : '';
      return { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...rects.get(key) } as DOMRect;
    });
    try {
      const { rerender } = render(
        <div data-testid="clip" style={{ overflowX: 'hidden', overflowY: 'hidden' }}>
          <Tooltip content="Close inspector · Esc"><button type="button">Close inspector</button></Tooltip>
        </div>,
      );
      await user.hover(screen.getByRole('button', { name: 'Close inspector' }));
      expect(await screen.findByRole('tooltip')).toHaveAttribute('data-align', 'end');

      // Room on both sides: centred, as everywhere else.
      await user.unhover(screen.getByRole('button', { name: 'Close inspector' }));
      rects.set('tooltip', { left: 700, right: 840 });
      rerender(
        <div data-testid="clip" style={{ overflowX: 'hidden', overflowY: 'hidden' }}>
          <Tooltip content="Close inspector · Esc"><button type="button">Close inspector</button></Tooltip>
        </div>,
      );
      await user.hover(screen.getByRole('button', { name: 'Close inspector' }));
      expect(await screen.findByRole('tooltip')).not.toHaveAttribute('data-align');
    } finally {
      spy.mockRestore();
    }
  });

  it('floats a hint too wide for what clips it, wrapped and placed in the viewport, so the whole value reads (§16)', async () => {
    const user = userEvent.setup();
    const long = 'north-perimeter-vehicle-gate-'.repeat(8) + '.mp4';
    // A Ledger frame 684px wide; the hint, unwrapped, is far wider than that.
    const rects = new Map<string, Partial<DOMRect>>([
      ['clip', { left: 236, right: 920, top: 100, bottom: 400 }],
      ['tooltip', { left: 100, right: 1900, top: 160, bottom: 180 }],
      ['anchor', { left: 300, right: 500, top: 130, bottom: 156 }],
    ]);
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const key = this.classList.contains('tooltip')
        ? (this.hasAttribute('data-float') ? 'floated' : 'tooltip')
        : this.classList.contains('tooltip-anchor') ? 'anchor' : this.dataset.testid === 'clip' ? 'clip' : '';
      const floated = { left: 0, right: 600, top: 0, bottom: 60 };
      return { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...(key === 'floated' ? floated : rects.get(key)) } as DOMRect;
    });
    try {
      render(
        <div data-testid="clip" style={{ overflowX: 'auto', overflowY: 'auto' }}>
          <Tooltip content={long}><span tabIndex={0}>north-perimeter…</span></Tooltip>
        </div>,
      );
      await user.tab();
      const tip = await screen.findByRole('tooltip');
      expect(tip).toHaveTextContent(long);
      expect(tip).toHaveAttribute('data-float');
      expect(tip).not.toHaveAttribute('data-align');
      // Inside the frame it belongs to (centred on its trigger would start at
      // 100, left of the frame's 236) and below the trigger (156 + 4).
      expect(tip.style.left).toBe('236px');
      expect(tip.style.top).toBe('160px');
    } finally {
      spy.mockRestore();
    }
  });

  it('floats a hint whose trigger is scrolled partly out of its frame, so the whole hint is inside the frame and hoverable (1.4.13)', async () => {
    const user = userEvent.setup();
    // A Ledger frame from 56 to 760; the name cell scrolled so that it starts
    // 166px left of the viewport and only its last 150px show; the hint, aligned
    // to the cell's start, would be cut off with it.
    const rects = new Map<string, Partial<DOMRect>>([
      ['clip', { left: 56, right: 760, top: 100, bottom: 700 }],
      ['tooltip', { left: -166, right: 200, top: 331, bottom: 358 }],
      ['anchor', { left: -166, right: 94, top: 308, bottom: 327 }],
    ]);
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const key = this.classList.contains('tooltip')
        ? (this.hasAttribute('data-float') ? 'floated' : 'tooltip')
        : this.classList.contains('tooltip-anchor') ? 'anchor' : this.dataset.testid === 'clip' ? 'clip' : '';
      const floated = { left: 0, right: 366, top: 0, bottom: 27 };
      return { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...(key === 'floated' ? floated : rects.get(key)) } as DOMRect;
    });
    try {
      render(
        <div data-testid="clip" style={{ overflowX: 'auto', overflowY: 'auto' }}>
          <Tooltip content="north-gate-0900-very-long-original-file-name.mp4"><span tabIndex={0}>north-gate-0900-very…</span></Tooltip>
        </div>,
      );
      await user.tab();
      const tip = await screen.findByRole('tooltip');
      expect(tip).toHaveAttribute('data-float');
      expect(tip).not.toHaveAttribute('data-align');
      // At the frame's left edge (centred on the trigger would start at −219), below the trigger.
      expect(tip.style.left).toBe('56px');
      expect(tip.style.top).toBe('331px');
    } finally {
      spy.mockRestore();
    }
  });

  it('is dismissed by Escape even when an open overlay takes the key at the window and stops it (1.4.13)', async () => {
    // A Drawer listens for Escape at the window in the capture phase and stops
    // propagation; a hint over the shell's navigation toggle beside it must
    // still go away on the same key.
    const stopper = (event: KeyboardEvent) => { if (event.key === 'Escape') event.stopPropagation(); };
    window.addEventListener('keydown', stopper, true);
    try {
      const user = userEvent.setup();
      render(<Harness />);
      await user.hover(screen.getByRole('button', { name: 'Next result' }));
      expect(await screen.findByRole('tooltip')).toBeInTheDocument();
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    } finally {
      window.removeEventListener('keydown', stopper, true);
    }
  });

  it('does not swallow Escape: the surface still hears it', async () => {
    const onEscape = vi.fn();
    window.addEventListener('keydown', onEscape);
    try {
      const user = userEvent.setup();
      render(<Harness />);
      await user.hover(screen.getByRole('button', { name: 'Next result' }));
      await user.keyboard('{Escape}');
      expect(onEscape).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener('keydown', onEscape);
    }
  });
});
