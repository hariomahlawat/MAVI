import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import Button, { ButtonLink } from './Button';

/**
 * The shared Button's state contract (specification v2.0 section 12). How a
 * state is *painted* is asserted against the stylesheet in
 * `styles/tokens.test.ts`; this file asserts what the component itself owes:
 * native semantics, one class per state, and nothing that would let a page
 * fake a state the stylesheet cannot see.
 */
describe('Button', () => {
  it('is a plain button by default, never an accidental submit', () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('type', 'button');
  });

  it('renders each variant and size as its own class and nothing else', () => {
    const { rerender } = render(<Button variant="primary">Go</Button>);
    expect(screen.getByRole('button')).toHaveClass('btn', 'btn--primary');
    rerender(<Button>Go</Button>);
    expect(screen.getByRole('button').className).toBe('btn');
    rerender(<Button variant="ghost" size="sm">Go</Button>);
    expect(screen.getByRole('button')).toHaveClass('btn', 'btn--ghost', 'btn--sm');
    rerender(<Button variant="danger">Go</Button>);
    expect(screen.getByRole('button')).toHaveClass('btn--danger');
  });

  it('keeps native disabled semantics and takes no inline style for it', async () => {
    const onClick = vi.fn();
    render(<Button variant="primary" disabled onClick={onClick}>Save revision</Button>);
    const button = screen.getByRole('button', { name: 'Save revision' });
    expect(button).toBeDisabled();
    // The disabled surface comes from `.btn:disabled` in the stylesheet, by
    // tokens; the component adds no opacity, no extra class and no inline
    // style, so a page cannot end up with a second disabled treatment.
    expect(button).not.toHaveAttribute('style');
    expect(button.className).toBe('btn btn--primary');
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('carries a pressed state as aria-pressed so the stylesheet can paint it', () => {
    render(<Button aria-pressed="true">Zones</Button>);
    expect(screen.getByRole('button', { name: 'Zones', pressed: true })).toBeInTheDocument();
  });

  it('names an icon-only button for assistive technology', () => {
    render(<Button icon="close" iconOnly>Close</Button>);
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
  });

  it('renders ButtonLink with the same classes as Button', () => {
    render(
      <MemoryRouter>
        <ButtonLink to="/import" variant="primary" size="sm">Import</ButtonLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Import' })).toHaveClass('btn', 'btn--primary', 'btn--sm');
  });
});
