import { useEffect, type ReactNode } from 'react';
import { useBlocker } from 'react-router-dom';
import Dialog from '../../shared/overlay/Dialog';

/**
 * Warns before unsaved scene edits are lost.
 *
 * Two exits need covering and they are covered differently: the router's own
 * blocker handles navigation inside the application, and `beforeunload` handles
 * closing or reloading the tab, which the router never sees. Neither traps the
 * operator: declining simply stays on the page.
 *
 * In-application navigation is decided in the product's own Dialog (§15), not
 * in `window.confirm`: a browser confirm cannot state the consequence in the
 * product's words, and a browser that offers to suppress further dialogs would
 * quietly remove the safeguard. The hook returns the dialog for the surface to
 * render; it is open exactly while the router holds a blocked navigation, so
 * there is never more than one, and either answer releases the blocker —
 * proceed or reset — so it can never be left stuck.
 */
export function useUnsavedChangesGuard(
  dirty: boolean,
  message: string,
  /**
   * Another decision is already open on this surface. One decision at a time:
   * a navigation attempted meanwhile (browser Back) is refused rather than
   * stacking a second dialog on the first.
   */
  busy = false,
): ReactNode {
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    dirty && currentLocation.pathname !== nextLocation.pathname);

  const blocked = blocker.state === 'blocked';
  useEffect(() => {
    if (busy && blocked) blocker.reset?.();
  }, [busy, blocked, blocker]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Browsers show their own wording; assigning returnValue is what arms it.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [dirty]);

  return (
    <Dialog
      open={blocked && !busy}
      title="Leave with unsaved changes?"
      confirmLabel="Leave and discard changes"
      cancelLabel="Stay on this page"
      destructive
      onConfirm={() => blocker.proceed?.()}
      onCancel={() => blocker.reset?.()}
    >
      {message}
    </Dialog>
  );
}
