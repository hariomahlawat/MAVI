import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import componentsCss from '../../styles/components.css?raw';
import EvidencePlaceholder from './EvidencePlaceholder';

/**
 * Evidence that cannot be shown (§27, §37.1 media): "matte at aspect, one
 * icon, one short label (`No image`), no prose" — at every frame size — and
 * nothing that reads as a broken image, a pending load or an error.
 */

/** The text actually painted inside the frame (the accessible name is separate). */
function paintedText(element: HTMLElement): string {
  return element.textContent ?? '';
}

describe('EvidencePlaceholder', () => {
  it('draws one icon and the visible word "No image", and nothing longer', () => {
    const { container } = render(<EvidencePlaceholder />);
    const placeholder = screen.getByRole('img', { name: 'No image' });
    expect(paintedText(placeholder)).toBe('No image');
    expect(placeholder.querySelector('.evidence-placeholder__label')).toBeVisible();
    expect(placeholder.querySelectorAll('svg')).toHaveLength(1);
    expect(container.querySelector('p')).toBeNull();
  });

  it('draws the same icon and visible "No image" in the dense frames (§37.1 has no icon-only form)', () => {
    render(<EvidencePlaceholder dense />);
    const placeholder = screen.getByRole('img', { name: 'No image' });
    expect(placeholder).toHaveClass('evidence-placeholder--dense');
    expect(paintedText(placeholder)).toBe('No image');
    expect(placeholder.querySelector('.evidence-placeholder__label')).toBeVisible();
    expect(placeholder.querySelectorAll('svg')).toHaveLength(1);
  });

  it('keeps the reason for assistive technology only, never painted in the frame', () => {
    for (const dense of [false, true]) {
      const { unmount } = render(<EvidencePlaceholder dense={dense} reason="no evidence image was persisted" />);
      const placeholder = screen.getByRole('img', { name: 'No image: no evidence image was persisted' });
      expect(paintedText(placeholder)).toBe('No image');
      expect(placeholder).not.toHaveTextContent(/persisted/);
      unmount();
    }
  });

  it('claims nothing while an image is still expected: matte only, no icon, no "No image", no spinner', () => {
    const { container } = render(<EvidencePlaceholder label="Loading image" pending />);
    const placeholder = screen.getByRole('img', { name: 'Loading image' });
    expect(placeholder).toHaveClass('evidence-placeholder--pending');
    expect(paintedText(placeholder)).toBe('');
    expect(placeholder.querySelector('svg')).toBeNull();
    expect(container).not.toHaveTextContent(/No image/);
    expect(container.querySelector('.spinner, [role="progressbar"]')).toBeNull();
  });

  it('is never a broken <img>, a spinner or a status alert, dense or not', () => {
    for (const dense of [false, true]) {
      const { container, unmount } = render(<EvidencePlaceholder dense={dense} />);
      expect(container.querySelector('img, .spinner')).toBeNull();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      unmount();
    }
  });

  it('fills the frame it replaces on the evidence matte, in no status hue', () => {
    const rule = componentsCss.match(/\.evidence-placeholder \{([^}]*)\}/)?.[1] ?? '';
    expect(rule).toMatch(/width:\s*100%/);
    expect(rule).toMatch(/height:\s*100%/);
    expect(rule).toContain('var(--evidence-matte)');
    expect(rule).not.toMatch(/--status-/);
  });

  it('lets dense change spacing and icon size only: never hides the label, never sizes the frame', () => {
    const rules = [...componentsCss.matchAll(/([^{}]*evidence-placeholder--dense[^{}]*)\{([^}]*)\}/g)];
    expect(rules.length).toBeGreaterThan(0);
    for (const [, selector, body] of rules) {
      // Nothing that removes, clips or recolours what is drawn.
      expect(body).not.toMatch(/display:\s*none|visibility:\s*hidden|clip|font-size:\s*0|aspect-ratio|--status-/);
      expect(selector).not.toMatch(/__label[^{]*$/);
      // The frame keeps the geometry of the image it replaces; only the icon may be resized.
      if (!/\.icon\s*$/.test(selector.trim())) expect(body).not.toMatch(/(^|[^-])(width|height):/);
    }
  });
});
