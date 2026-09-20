import { useEffect } from 'react';
import { useBlocker } from 'react-router-dom';

/**
 * Warns before unsaved scene edits are lost.
 *
 * Two exits need covering and they are covered differently: the router's own
 * blocker handles navigation inside the application, and `beforeunload` handles
 * closing or reloading the tab, which the router never sees. Neither traps the
 * operator: declining the prompt simply stays on the page.
 */
export function useUnsavedChangesGuard(dirty: boolean, message: string): void {
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    dirty && currentLocation.pathname !== nextLocation.pathname);

  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    // eslint-disable-next-line no-alert
    if (window.confirm(message)) blocker.proceed();
    else blocker.reset();
  }, [blocker, message]);

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
}
