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
    expect(screen.getByRole('tooltip')).toHaveTextContent('Next result · j or ↓');
    expect(trigger).toHaveFocus();
  });

  it('opens on pointer hover and closes when the pointer leaves', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Next result' });
    await user.hover(trigger);
    expect(screen.getByRole('tooltip')).toBeVisible();
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
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.tab({ shift: true });
    await user.tab();
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
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
