import type { ReactNode } from 'react';

/**
 * A segmented control: one choice, several options, exactly one pressed.
 *
 * §27.1 promotion: the Scene Editor's mode strip and any future mode choice
 * mean the same thing (which mode is armed), behave the same way (click sets
 * it), and carry the same accessibility contract. The semantics are deliberately
 * `role="group"` plus `aria-pressed`, **not** tabs: nothing here controls a
 * tabpanel, and claiming the tab role would promise arrow-key navigation
 * between panels that does not exist.
 *
 * The pressed style comes from `.btn[aria-pressed="true"]` in the UI-1 layer,
 * so a control that carries the attribute can never be left without the style.
 */

export type SegmentedOption<T extends string> = {
  value: T;
  label: ReactNode;
  /** Distinguishes options whose visible label is an icon or is ambiguous. */
  accessibleName?: string;
};

export default function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  size = 'md',
}: {
  /** Names the group for assistive technology; there is no visible legend. */
  label: string;
  value: T;
  options: ReadonlyArray<SegmentedOption<T>>;
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
}) {
  return (
    <div className={`segmented${size === 'sm' ? ' segmented--sm' : ''}`} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`segmented__item${option.value === value ? ' is-active' : ''}`}
          aria-pressed={option.value === value}
          aria-label={option.accessibleName}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
