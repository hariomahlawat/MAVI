import { useId, type ReactNode } from 'react';

/**
 * A labelled form control with inline, field-level validation (§21).
 *
 * §27.1 promotion: every form in the product owes the same four things — a
 * label bound to the control, `aria-invalid` when the value is refused, an
 * error message associated through `aria-describedby`, and help text that is
 * associated rather than merely adjacent. That contract is identical on
 * Cameras and on Import, it is frozen by §21 and §23 rather than left to each
 * surface, and there is nothing about it that the two are expected to pull
 * apart on. What differs is the control itself, which is why the control is
 * the caller's and arrives through a render prop: this component never knows
 * whether it is wrapping a text box, a select or a file input.
 *
 * It is deliberately not a form framework. It holds no value, runs no
 * validation, and submits nothing (§6 of the UI-3 brief): the feature decides
 * what is invalid and when, and passes the message in.
 */
export default function Field({
  label,
  error,
  help,
  optional = false,
  children,
}: {
  label: string;
  /** The message for a refused value. Its presence is what makes the field invalid. */
  error?: string | null;
  /** Format, authority or constraint the operator needs while filling the field. */
  help?: ReactNode;
  /** §21: optional fields are marked; required fields are not. */
  optional?: boolean;
  children: (control: {
    id: string;
    'aria-invalid'?: true;
    'aria-describedby'?: string;
  }) => ReactNode;
}) {
  const base = useId();
  const helpId = help ? `${base}-help` : null;
  const errorId = error ? `${base}-error` : null;
  // The error is named first: it is the thing the operator has to act on, and
  // a screen reader reads the description in the order it is given.
  const describedBy = [errorId, helpId].filter(Boolean).join(' ');

  return (
    <div className="field">
      <label className="field__label" htmlFor={base}>
        {label}
        {optional ? <span className="field__optional"> (optional)</span> : null}
      </label>
      {children({
        id: base,
        ...(error ? { 'aria-invalid': true as const } : {}),
        ...(describedBy ? { 'aria-describedby': describedBy } : {}),
      })}
      {error ? <p className="field__error" id={errorId ?? undefined}>{error}</p> : null}
      {help ? <div className="field__help" id={helpId ?? undefined}>{help}</div> : null}
    </div>
  );
}
