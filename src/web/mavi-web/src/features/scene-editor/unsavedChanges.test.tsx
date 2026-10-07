import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Link } from 'react-router-dom';
import { renderWithApp } from '../../test/renderWithApp';
import { useUnsavedChangesGuard } from './useUnsavedChangesGuard';

function Guarded({ dirty, busy = false }: { dirty: boolean; busy?: boolean }) {
  const dialog = useUnsavedChangesGuard(dirty, 'Your unsaved scene changes are discarded if you leave this page now.', busy);
  return (
    <div>
      {dialog}
      <p>{dirty ? 'dirty' : 'clean'}</p>
      <Link to="/elsewhere">Leave</Link>
      <Link to="/other">Other</Link>
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

function render(dirty: boolean, busy = false) {
  return renderWithApp(<Guarded dirty={dirty} busy={busy} />, {
    route: '/here',
    routePath: '*',
    dataRouter: true,
  });
}

describe('unsaved changes guard', () => {
  it('lets navigation through when there is nothing to lose', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm');
    const { router } = render(false);

    await user.click(screen.getByRole('link', { name: 'Leave' }));

    await waitFor(() => expect(router!.state.location.pathname).toBe('/elsewhere'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
  });

  it('asks in the product dialog before leaving with unsaved changes, and stays when refused', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm');
    const { router } = render(true);

    await user.click(screen.getByRole('link', { name: 'Leave' }));

    const dialog = await screen.findByRole('dialog', { name: 'Leave with unsaved changes?' });
    expect(dialog).toHaveTextContent('Your unsaved scene changes are discarded if you leave this page now.');
    expect(confirm).not.toHaveBeenCalled();
    // Blocked until the operator decides.
    expect(router!.state.location.pathname).toBe('/here');

    await user.click(within(dialog).getByRole('button', { name: 'Stay on this page' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(router!.state.location.pathname).toBe('/here');
    expect(screen.getByText('dirty')).toBeInTheDocument();
  });

  it('treats Escape as staying, never as leaving', async () => {
    const user = userEvent.setup();
    const { router } = render(true);

    await user.click(screen.getByRole('link', { name: 'Leave' }));
    await screen.findByRole('dialog');
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(router!.state.location.pathname).toBe('/here');
  });

  it('leaves once the operator confirms, so the guard is never a trap', async () => {
    const user = userEvent.setup();
    const { router } = render(true);

    await user.click(screen.getByRole('link', { name: 'Leave' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Leave and discard changes' }));

    await waitFor(() => expect(router!.state.location.pathname).toBe('/elsewhere'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens no second decision while another is open, and refuses the navigation', async () => {
    const user = userEvent.setup();
    const { router } = render(true, true);

    await user.click(screen.getByRole('link', { name: 'Leave' }));

    await waitFor(() => expect(router!.state.location.pathname).toBe('/here'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // Released, not held: the blocker is idle again.
    expect(router!.state.blockers.size === 0 || [...router!.state.blockers.values()].every((b) => b.state !== 'blocked')).toBe(true);
  });

  it('is never stuck: after staying, a later navigation asks again, once', async () => {
    const user = userEvent.setup();
    const { router } = render(true);

    await user.click(screen.getByRole('link', { name: 'Leave' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Stay on this page' }));

    await user.click(screen.getByRole('link', { name: 'Other' }));
    expect(await screen.findAllByRole('dialog')).toHaveLength(1);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Leave and discard changes' }));
    await waitFor(() => expect(router!.state.location.pathname).toBe('/other'));
  });

  it('arms the browser prompt only while there are unsaved changes', () => {
    const add = vi.spyOn(window, 'addEventListener');
    const remove = vi.spyOn(window, 'removeEventListener');

    const clean = render(false);
    expect(add.mock.calls.filter(([type]) => type === 'beforeunload')).toHaveLength(0);
    clean.unmount();

    const dirty = render(true);
    expect(add.mock.calls.filter(([type]) => type === 'beforeunload')).toHaveLength(1);
    dirty.unmount();
    expect(remove.mock.calls.filter(([type]) => type === 'beforeunload')).toHaveLength(1);
  });

  it('cancels the browser unload so the prompt actually appears', () => {
    const handlers: Array<(event: BeforeUnloadEvent) => void> = [];
    vi.spyOn(window, 'addEventListener').mockImplementation(((type: string, handler: EventListener) => {
      if (type === 'beforeunload') handlers.push(handler as (event: BeforeUnloadEvent) => void);
    }) as typeof window.addEventListener);

    render(true);

    expect(handlers).toHaveLength(1);
    const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent;
    handlers[0](event);
    expect(event.defaultPrevented).toBe(true);
  });
});
