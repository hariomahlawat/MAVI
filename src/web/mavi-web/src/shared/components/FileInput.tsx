import { useEffect, useId, useRef } from 'react';
import Icon from './Icon';

/**
 * A single-file chooser drawn in the control system (§27, §36.1), with the
 * native `<input type="file">` as the control the operator actually operates.
 *
 * The native input is not replaced or simulated. It is laid over the whole
 * frame, transparent, so a pointer anywhere on the frame presses it, Tab
 * reaches it, Enter and Space open the platform picker, and assistive
 * technology meets a real file input with its own semantics. What the frame
 * adds is presentation only: the control-height box every input in a row
 * shares (a native control at native height beside a 32px button is a defect,
 * §36.1), a visible choose affordance, and the chosen file's name — or a plain
 * statement that none is chosen — as text that is always on screen, never only
 * in a tooltip.
 *
 * Focus is drawn on the frame with `:focus-within`, not `:focus-visible`, on
 * purpose: when a refused submit moves focus here (`useFocusFirstInvalid`,
 * §12) the browser may not treat that programmatic focus as keyboard focus, and
 * a ring that only keyboard focus draws would leave the operator unable to see
 * where they were taken.
 *
 * It is labelled by the caller's `Field`, whose id, `aria-invalid` and
 * `aria-describedby` it passes to the native input; the visible file name is
 * added to that description so the choice is announced with the field. It
 * validates nothing: what is acceptable is the caller's decision (§21).
 */
export default function FileInput({
  id,
  file,
  onChange,
  accept,
  disabled = false,
  chooseLabel = 'Choose file',
  emptyLabel = 'No file selected',
  'aria-invalid': ariaInvalid,
  'aria-describedby': ariaDescribedBy,
}: {
  /** From `Field`: binds the field's label to the native input. */
  id?: string;
  /** The chosen file, owned by the caller. `null` clears the native input too. */
  file: File | null;
  onChange: (file: File | null) => void;
  /** Passed to the native input unchanged; the platform picker filters by it. */
  accept?: string;
  disabled?: boolean;
  chooseLabel?: string;
  emptyLabel?: string;
  'aria-invalid'?: boolean | 'true' | 'false';
  'aria-describedby'?: string;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const nameId = `${useId()}-name`;
  const invalid = ariaInvalid === true || ariaInvalid === 'true';

  // The native input keeps its own selection; when the caller clears the file
  // (a successful import, a reset) the input must forget it as well, or the
  // same file chosen again would raise no change.
  useEffect(() => {
    if (!file && inputRef.current) inputRef.current.value = '';
  }, [file]);

  return (
    <div
      className="file-input"
      data-invalid={invalid || undefined}
      data-disabled={disabled || undefined}
    >
      <input
        ref={inputRef}
        id={id}
        className="file-input__native"
        type="file"
        accept={accept}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-describedby={[ariaDescribedBy, nameId].filter(Boolean).join(' ')}
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      <span className="file-input__choose" aria-hidden="true">
        <Icon name="upload" size="sm" />
        {chooseLabel}
      </span>
      <span className="file-input__name" id={nameId} data-empty={file ? undefined : true}>
        {file ? file.name : emptyLabel}
      </span>
    </div>
  );
}
