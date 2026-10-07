import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Field from './Field';

/**
 * The shared Field's validation contract (specification v2.0 sections 12, 21
 * and 23): the refusal is stated in the attribute, in an associated message and
 * in the boundary, and the message is text, so the state is never carried by
 * colour alone. The boundary's hue is asserted against the stylesheet in
 * `styles/tokens.test.ts`.
 */
describe('Field', () => {
  it('binds the label to the control', () => {
    render(<Field label="Camera code">{(control) => <input {...control} />}</Field>);
    expect(screen.getByLabelText('Camera code')).toBeInTheDocument();
  });

  it('marks a refused value with aria-invalid and an associated message', () => {
    render(
      <Field label="Camera code" error="Enter a camera code.">
        {(control) => <input {...control} />}
      </Field>,
    );
    const input = screen.getByLabelText('Camera code');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription('Enter a camera code.');
    expect(screen.getByText('Enter a camera code.')).toHaveClass('field__error');
  });

  it('names the error before the help, and drops aria-invalid when the value is accepted', () => {
    const { rerender } = render(
      <Field label="Code" error="Required." help="Letters and digits.">
        {(control) => <input {...control} />}
      </Field>,
    );
    expect(screen.getByLabelText('Code')).toHaveAccessibleDescription('Required. Letters and digits.');
    rerender(<Field label="Code" help="Letters and digits.">{(control) => <input {...control} />}</Field>);
    const input = screen.getByLabelText('Code');
    expect(input).not.toHaveAttribute('aria-invalid');
    expect(input).toHaveAccessibleDescription('Letters and digits.');
  });

  it('marks optional fields and never required ones (section 21)', () => {
    render(<Field label="Name" optional>{(control) => <input {...control} />}</Field>);
    expect(screen.getByText('(optional)')).toHaveClass('field__optional');
  });
});
