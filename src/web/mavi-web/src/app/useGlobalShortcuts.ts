import { useEffect, useRef } from 'react';
import { destinationForKey } from '../shared/workspace';

/** How long `g` waits for its letter before it stops meaning anything (§22). */
export const CHORD_TIMEOUT_MS = 1500;

/** A text-entry context, where a letter is typing and never a shortcut (§22, §23). */
export function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  // `isContentEditable` is the platform's answer; the attribute check covers
  // environments that do not compute it and editable ancestors alike.
  if (target.isContentEditable || target.closest('[contenteditable]:not([contenteditable="false"])')) return true;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  const type = (target as HTMLInputElement).type;
  // A checkbox, radio or button takes no text; every other input does.
  return !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image'].includes(type);
}

/**
 * The shell's global keys (§5, §22): `g` then a letter opens a primary
 * destination, and `?` opens the shortcut sheet.
 *
 * - Never from a text-entry context, and never with Ctrl, Alt or Meta held —
 *   those are the browser's and the platform's.
 * - Never while a modal overlay holds the workspace (a Dialog, an overlay
 *   Drawer, the sheet itself): what is behind it is not the operator's target.
 * - `g` arms the chord for a short time only, and any next key disarms it; a
 *   key that is not a destination navigates nowhere.
 * - Navigation is ordinary router navigation, as a rail click is.
 *
 * The destination letters live with the destinations in the IA map, so this
 * hook holds no table of its own.
 */
export function useGlobalShortcuts({
  enabled,
  onNavigate,
  onOpenSheet,
}: {
  enabled: boolean;
  onNavigate: (to: string) => void;
  onOpenSheet: () => void;
}): void {
  const armedUntil = useRef(0);
  const navigateRef = useRef(onNavigate);
  const openRef = useRef(onOpenSheet);
  navigateRef.current = onNavigate;
  openRef.current = onOpenSheet;

  useEffect(() => {
    if (!enabled) {
      armedUntil.current = 0;
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      // Any key a surface consumed, or one with a modifier, still spends the
      // chord: `g`, then Search's `j`, then `v` must not open Videos.
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) {
        armedUntil.current = 0;
        return;
      }
      if (isTextEntry(event.target)) {
        armedUntil.current = 0;
        return;
      }
      if (document.querySelector('[aria-modal="true"]')) {
        armedUntil.current = 0;
        return;
      }

      const armed = armedUntil.current > Date.now();
      armedUntil.current = 0;

      if (armed) {
        const target = destinationForKey(event.key);
        if (target) {
          event.preventDefault();
          navigateRef.current(target.to);
        }
        return;
      }
      if (event.key === '?') {
        event.preventDefault();
        openRef.current();
        return;
      }
      if (event.key === 'g' && !event.shiftKey) {
        armedUntil.current = Date.now() + CHORD_TIMEOUT_MS;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled]);
}
