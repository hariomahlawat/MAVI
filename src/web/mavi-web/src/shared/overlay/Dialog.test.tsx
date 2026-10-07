import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import Dialog from './Dialog';

/** A surface with a control behind the dialog and the button that opens it. */
function Harness({ onConfirm = () => {}, onCancel = () => {} }: { onConfirm?: () => void; onCancel?: () => void }) {
  const [open, setOpen] = useState(false);
  const [discarded, setDiscarded] = useState(false);
  return (
    <div>
      <button type="button">Behind</button>
      <button type="button" onClick={() => setOpen(true)}>Reset</button>
      <p>{discarded ? 'discarded' : 'kept'}</p>
      <Dialog
        open={open}
        title="Discard your unsaved scene changes?"
        confirmLabel="Discard changes"
        destructive
        onConfirm={() => {
          onConfirm();
          setDiscarded(true);
          setOpen(false);
        }}
        onCancel={() => {
          onCancel();
          setOpen(false);
        }}
      >
        Your unsaved edits are discarded.
      </Dialog>
    </div>
  );
}

async function openDialog() {
  const user = userEvent.setup();
  const utils = render(<Harness />);
  const invoker = screen.getByRole('button', { name: 'Reset' });
  await user.click(invoker);
  return { user, invoker, ...utils };
}

describe('Dialog', () => {
  it('is a named, described modal dialog with a named consequence and a secondary Cancel', async () => {
    await openDialog();
    const dialog = screen.getByRole('dialog', { name: 'Discard your unsaved scene changes?' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleDescription('Your unsaved edits are discarded.');
    const buttons = Array.from(dialog.querySelectorAll('button'));
    expect(buttons.map((button) => button.textContent)).toEqual(['Cancel', 'Discard changes']);
    expect(buttons[1]).toHaveClass('btn--danger');
  });

  it('moves focus in, onto Cancel, when it opens', async () => {
    await openDialog();
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
  });

  it('keeps Tab and Shift+Tab inside, wrapping at both ends', async () => {
    const { user } = await openDialog();
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    const confirm = screen.getByRole('button', { name: 'Discard changes' });
    await user.tab();
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();
    await user.tab({ shift: true });
    expect(cancel).toHaveFocus();
  });

  it('cancels on Escape, without confirming, and the Escape reaches nothing underneath', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const underneath = vi.fn();
    window.addEventListener('keydown', underneath);
    try {
      const user = userEvent.setup();
      render(<Harness onConfirm={onConfirm} onCancel={onCancel} />);
      await user.click(screen.getByRole('button', { name: 'Reset' }));
      await user.keyboard('{Escape}');
      expect(onCancel).toHaveBeenCalledTimes(1);
      expect(onConfirm).not.toHaveBeenCalled();
      expect(underneath).not.toHaveBeenCalled();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(screen.getByText('kept')).toBeInTheDocument();
    } finally {
      window.removeEventListener('keydown', underneath);
    }
  });

  it('keeps every key from the surface behind it, while Enter still activates its own buttons', async () => {
    const behind = vi.fn();
    window.addEventListener('keydown', behind);
    try {
      const onConfirm = vi.fn();
      const user = userEvent.setup();
      render(<Harness onConfirm={onConfirm} />);
      await user.click(screen.getByRole('button', { name: 'Reset' }));
      behind.mockClear();
      // A surface's shortcuts (Delete removes the selected object, arrows
      // nudge a vertex, Enter closes a zone) must not act on the work behind
      // the decision.
      await user.keyboard('{Delete}{ArrowLeft}{Backspace}j');
      expect(behind).not.toHaveBeenCalled();
      await user.tab();
      await user.keyboard('{Enter}');
      expect(behind).not.toHaveBeenCalled();
      expect(onConfirm).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener('keydown', behind);
    }
  });

  it('treats Cancel as non-destructive', async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(<Harness onConfirm={onConfirm} />);
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText('kept')).toBeInTheDocument();
  });

  it('runs the confirmed action exactly once', async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(<Harness onConfirm={onConfirm} />);
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    await user.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.getByText('discarded')).toBeInTheDocument();
  });

  it('makes everything behind it inert while open, and gives it back on close', async () => {
    const { user, container } = await openDialog();
    // The page root is a body child other than the dialog host.
    expect(container).toHaveAttribute('inert');
    expect(screen.getByRole('dialog').closest('[inert]')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(container).not.toHaveAttribute('inert');
  });

  it('does not release inert it did not set', async () => {
    const other = document.createElement('div');
    other.setAttribute('inert', '');
    document.body.appendChild(other);
    try {
      const { user } = await openDialog();
      await user.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(other).toHaveAttribute('inert');
    } finally {
      other.remove();
    }
  });

  it('returns focus to the control that opened it, on cancel and on confirm', async () => {
    const { user, invoker } = await openDialog();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(invoker).toHaveFocus();
    await user.click(invoker);
    await user.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(invoker).toHaveFocus();
  });

  it('does not try to focus an invoker that has gone', async () => {
    function Vanishing() {
      const [open, setOpen] = useState(false);
      return (
        <div>
          {open ? null : <button type="button" onClick={() => setOpen(true)}>Open</button>}
          <Dialog open={open} title="Leave?" confirmLabel="Leave" onConfirm={() => setOpen(false)} onCancel={() => setOpen(false)}>
            Body
          </Dialog>
        </div>
      );
    }
    const user = userEvent.setup();
    render(<Vanishing />);
    const original = screen.getByRole('button', { name: 'Open' });
    await user.click(original);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(original.isConnected).toBe(false);
    expect(document.activeElement).not.toBe(original);
  });

  it('renders nothing while closed', () => {
    render(<Harness />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.querySelector('.dialog-host')).toBeNull();
  });
});
