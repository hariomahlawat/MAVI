import { useEffect, type RefObject } from 'react';
import Button from '../shared/components/Button';
import Drawer from '../shared/overlay/Drawer';
import { DESTINATIONS, type SurfaceId } from '../shared/workspace';
import { SEARCH_SHORTCUTS } from '../features/visual-search/searchShortcuts';

/** Keys a surface implements itself, listed while that surface is open (§17, §22). */
const SURFACE_SHORTCUTS: Partial<Record<SurfaceId, { title: string; keys: typeof SEARCH_SHORTCUTS }>> = {
  search: { title: 'Search results', keys: SEARCH_SHORTCUTS },
};

/**
 * The `?` shortcut sheet (§5, §22).
 *
 * Composed from the shared Drawer rather than built as a new overlay: §11
 * allows one drawer style, and the sheet's contract is exactly the drawer's —
 * an overlay that takes focus to its heading, keeps Tab inside, closes on
 * Escape, makes what it covers inert and gives focus back. It is deliberately
 * not the Dialog, whose semantics (§15) are a consequence to decide.
 *
 * It names the keys the shell implements, reading the destination letters from
 * the IA map, and — while a surface that has its own keys is open — that
 * surface's keys, from the list the surface itself owns (Search's `j`/`k`,
 * §17: the legend lives here, not in standing header chrome). So the sheet
 * cannot advertise a key that does nothing where it is opened.
 */
export default function ShortcutSheet({
  onClose,
  covers,
  surface,
}: {
  onClose: () => void;
  /** The surface the sheet was opened over, whose own keys it lists. */
  surface?: SurfaceId;
  /** The rail and the workspace: inert while the sheet is open. */
  covers: readonly RefObject<HTMLElement | null>[];
}) {
  // No surface shortcut acts behind the sheet. Every key is stopped at the
  // window in the capture phase — after the Drawer, whose capture listener is
  // registered first, has taken Escape and Tab — so it reaches no surface
  // handler wherever focus is: the heading, a row, or the panel itself after a
  // click on plain text. Stopping propagation does not cancel a key's default
  // action, so Enter and Space still press the sheet's own button.
  useEffect(() => {
    const swallow = (event: globalThis.KeyboardEvent) => event.stopPropagation();
    window.addEventListener('keydown', swallow, true);
    return () => window.removeEventListener('keydown', swallow, true);
  }, []);

  return (
    <Drawer open overlay onClose={onClose} covers={covers} className="shortcut-sheet">
      <div className="shortcut-sheet__body">
        <div className="shortcut-sheet__head">
          <h2>Keyboard shortcuts</h2>
          <Button size="sm" variant="ghost" icon="x" iconOnly onClick={onClose}>Close keyboard shortcuts</Button>
        </div>
        <p className="shortcut-sheet__note">Shortcuts do nothing while you are typing in a field.</p>
        {surface && SURFACE_SHORTCUTS[surface] ? (
          <>
            <h3>{SURFACE_SHORTCUTS[surface]!.title}</h3>
            <dl className="shortcut-list">
              {SURFACE_SHORTCUTS[surface]!.keys.map((shortcut) => (
                <div className="shortcut-list__row" key={shortcut.description}>
                  <dt>
                    {shortcut.keys.map((key, index) => (
                      <span key={key}>{index > 0 ? ' or ' : null}<kbd>{key}</kbd></span>
                    ))}
                  </dt>
                  <dd>{shortcut.description}</dd>
                </div>
              ))}
            </dl>
          </>
        ) : null}
        <h3>Go to</h3>
        <dl className="shortcut-list">
          {DESTINATIONS.map((destination) => (
            <div className="shortcut-list__row" key={destination.id}>
              <dt><kbd>g</kbd> <kbd>{destination.key}</kbd></dt>
              <dd>{destination.label}</dd>
            </div>
          ))}
        </dl>
        <h3>This sheet</h3>
        <dl className="shortcut-list">
          <div className="shortcut-list__row">
            <dt><kbd>?</kbd></dt>
            <dd>Show keyboard shortcuts</dd>
          </div>
          <div className="shortcut-list__row">
            <dt><kbd>Esc</kbd></dt>
            <dd>Close this sheet</dd>
          </div>
        </dl>
      </div>
    </Drawer>
  );
}
