import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Link } from 'react-router-dom';
import { renderWithApp } from '../../test/renderWithApp';
import { useUnsavedChangesGuard } from './useUnsavedChangesGuard';

function Guarded({ dirty }: { dirty: boolean }) {
  useUnsavedChangesGuard(dirty, 'You have unsaved scene changes. Leave without saving?');
  return (
    <div>
      <p>{dirty ? 'dirty' : 'clean'}</p>
      <Link to="/elsewhere">Leave</Link>
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

function render(dirty: boolean) {
  return renderWithApp(<Guarded dirty={dirty} />, {
    route: '/here',
    routePath: '*',
    dataRouter: true,
  });
}

describe('unsaved changes guard', () => {
  it('lets navigation through when there is nothing to lose', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { router } = render(false);

    await user.click(screen.getByRole('link', { name: 'Leave' }));

    await waitFor(() => expect(router!.state.location.pathname).toBe('/elsewhere'));
    expect(confirm).not.toHaveBeenCalled();
  });

  it('asks before leaving with unsaved changes and stays when refused', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { router } = render(true);

    await user.click(screen.getByRole('link', { name: 'Leave' }));

    expect(confirm).toHaveBeenCalledWith('You have unsaved scene changes. Leave without saving?');
    await waitFor(() => expect(router!.state.location.pathname).toBe('/here'));
  });

  it('leaves once the operator confirms, so the guard is never a trap', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { router } = render(true);

    await user.click(screen.getByRole('link', { name: 'Leave' }));

    await waitFor(() => expect(router!.state.location.pathname).toBe('/elsewhere'));
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
