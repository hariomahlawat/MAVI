import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import Button from '../components/Button';
import { containTab, makeInert, restoreFocus } from './focus';

/**
 * A consequential decision the operator has to make before anything else
 * (specification §15).
 *
 * It exists for the rare question that genuinely blocks the workspace — leaving
 * with unsaved work, discarding an edit — and replaces `window.confirm`, which
 * cannot state a consequence in product language and which browsers offer to
 * suppress, silently removing the safeguard. Routine editing never opens one.
 *
 * The contract, all of it asserted in `Dialog.test.tsx`:
 * - the title states the consequence, the body says what happens, and the
 *   confirm button is named for the action ("Discard changes"), never "OK";
 * - focus moves in on open — to Cancel, the safe choice — and Tab and
 *   Shift+Tab stay inside;
 * - Escape cancels; it never confirms;
 * - everything behind it is inert while it is open, so nothing can be clicked
 *   or focused through it;
 * - focus returns to the control that opened it.
 *
 * It is deliberately small: one title, one body, one decision. Not a modal
 * framework.
 */
export default function Dialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  /** The consequence, stated as the decision ("Discard your unsaved scene changes?"). */
  title: string;
  /** What happens if the operator confirms, in product language. */
  children: ReactNode;
  /** Named for the action it performs. */
  confirmLabel: string;
  cancelLabel?: string;
  /** The confirm action loses work: it is drawn as the danger action, never as the primary. */
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const bodyId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const invokerRef = useRef<Element | null>(null);
  // The latest callbacks without re-running the open effect when a parent
  // re-renders with new closures.
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;

  useEffect(() => {
    if (!open) return undefined;
    const panel = panelRef.current;
    const host = panel?.closest<HTMLElement>('.dialog-host') ?? null;
    invokerRef.current = document.activeElement;

    // Everything in the document except this dialog's own host.
    const siblings = Array.from(document.body.children).filter(
      (element): element is HTMLElement => element instanceof HTMLElement && element !== host,
    );
    const release = makeInert(siblings);
    cancelRef.current?.focus();

    // At the window, in the capture phase, so every key is the dialog's while
    // it is open: a surface's own shortcuts (Delete removing a scene object,
    // Enter closing a zone) must not act on the work behind the decision.
    // Stopping propagation does not cancel the browser's default action, so
    // Enter and Space still activate the dialog's own buttons.
    const onKeyDown = (event: KeyboardEvent) => {
      if (!panel) return;
      event.stopPropagation();
      if (event.key === 'Escape') {
        // Escape means "not this"; it never confirms.
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      containTab(event, panel);
    };
    window.addEventListener('keydown', onKeyDown, true);

    return () => {
      window.removeEventListener('keydown', onKeyDown, true);
      release();
      restoreFocus(invokerRef.current);
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className="dialog-host">
      <div className="dialog-backdrop" aria-hidden="true" />
      <div
        ref={panelRef}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
      >
        <h2 className="dialog__title" id={titleId}>{title}</h2>
        <div className="dialog__body" id={bodyId}>{children}</div>
        <div className="dialog__actions">
          <Button ref={cancelRef} onClick={onCancel}>{cancelLabel}</Button>
          <Button variant={destructive ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
