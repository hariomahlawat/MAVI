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
    // everything else the geometry of the inspector's Close button at 1920px.
    const rects = new Map<string, Partial<DOMRect>>([
      ['clip', { left: 216, right: 1920 }],
      ['tooltip', { left: 1812, right: 1936 }],
    ]);
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const key = this.classList.contains('tooltip') ? 'tooltip' : this.dataset.testid === 'clip' ? 'clip' : '';
      return { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...rects.get(key) } as DOMRect;
    });
    try {
      const { rerender } = render(
        <div data-testid="clip" style={{ overflow: 'hidden' }}>
          <Tooltip content="Close inspector · Esc"><button type="button">Close inspector</button></Tooltip>
        </div>,
      );
      await user.hover(screen.getByRole('button', { name: 'Close inspector' }));
      expect(await screen.findByRole('tooltip')).toHaveAttribute('data-align', 'end');

      // Room on both sides: centred, as everywhere else.
      await user.unhover(screen.getByRole('button', { name: 'Close inspector' }));
      rects.set('tooltip', { left: 900, right: 1024 });
      rerender(
        <div data-testid="clip" style={{ overflow: 'hidden' }}>
          <Tooltip content="Close inspector · Esc"><button type="button">Close inspector</button></Tooltip>
        </div>,
      );
      await user.hover(screen.getByRole('button', { name: 'Close inspector' }));
      expect(await screen.findByRole('tooltip')).not.toHaveAttribute('data-align');
    } finally {
      spy.mockRestore();
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
