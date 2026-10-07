import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import componentsCss from '../../styles/components.css?raw';
import EvidencePlaceholder from './EvidencePlaceholder';

/**
 * Evidence that cannot be shown (§27, §37.1 media): one canonical word, one
 * icon, the frame's own geometry, the evidence matte — and nothing that reads
 * as a broken image, a pending load or an error.
 */
describe('EvidencePlaceholder', () => {
  it('says "No image" and nothing longer inside the frame', () => {
    const { container } = render(<EvidencePlaceholder reason="no evidence image was persisted" />);
    const placeholder = screen.getByRole('img', { name: 'No image: no evidence image was persisted' });
    expect(placeholder).toHaveTextContent(/^No image$/);
    expect(container.querySelector('p')).toBeNull();
  });

  it('is never a broken <img>, a spinner or a status alert', () => {
    const { container } = render(<EvidencePlaceholder />);
    expect(container.querySelector('img, .spinner')).toBeNull();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('keeps its accessible name in a frame too small for the word', () => {
    render(<EvidencePlaceholder dense />);
    const placeholder = screen.getByRole('img', { name: 'No image' });
    expect(placeholder).toHaveTextContent('');
  });

  it('fills the frame it replaces on the evidence matte, in no status hue', () => {
    const rule = componentsCss.match(/\.evidence-placeholder \{([^}]*)\}/)?.[1] ?? '';
    expect(rule).toMatch(/width:\s*100%/);
    expect(rule).toMatch(/height:\s*100%/);
    expect(rule).toContain('var(--evidence-matte)');
    expect(rule).not.toMatch(/--status-/);
  });
});
