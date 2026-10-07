import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ContextBar } from '../workspace';
import TruncatedText from './Truncated';

/** jsdom lays nothing out: give elements whose text is longer than 20 characters a cut-off box. */
function layoutWhereLongTextOverflows() {
  const scroll = vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (this: HTMLElement) {
    return (this.textContent ?? '').length * 8;
  });
  const client = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => 160);
  return () => {
    scroll.mockRestore();
    client.mockRestore();
  };
}

let restoreLayout: () => void = () => {};
afterEach(() => restoreLayout());

describe('TruncatedText (§16, §36.2 truncation)', () => {
  it('makes a cut-off value reachable by keyboard and pointer, with its full text as a tooltip', async () => {
    restoreLayout = layoutWhereLongTextOverflows();
    const user = userEvent.setup();
    const name = 'North perimeter vehicle entrance, outer gate';
    render(<TruncatedText text={name} className="cap-lg" />);

    const value = screen.getByText(name, { selector: '.truncate' });
    expect(value).toHaveAttribute('tabindex', '0');
    await user.tab();
    expect(value).toHaveFocus();
    expect(await screen.findByRole('tooltip')).toHaveTextContent(name);
    expect(value).toHaveAccessibleDescription(name);
  });

  it('adds no tab stop and no hint for a value that fits', async () => {
    restoreLayout = layoutWhereLongTextOverflows();
    render(<TruncatedText text="Gate" />);
    const value = screen.getByText('Gate');
    expect(value).not.toHaveAttribute('tabindex');
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
    expect(value).not.toHaveAttribute('aria-describedby');
  });
});

describe('Context Bar long identity (§37.1 long names)', () => {
  it('lets a truncated crumb be reached and read in full, ancestors and the current crumb alike', async () => {
    restoreLayout = layoutWhereLongTextOverflows();
    const user = userEvent.setup();
    const camera = 'NORTH-PERIMETER-GATE-CAM-00042 · North perimeter vehicle entrance, outer gate';
    render(
      <MemoryRouter>
        <ContextBar surface="analytics" object={{ label: camera, to: '/cameras/x/scene' }} actions={<button type="button">Act</button>} />
      </MemoryRouter>,
    );
    // The camera crumb is a link: focusable already, and described while cut off.
    const link = screen.getByRole('link', { name: camera });
    await user.click(document.body);
    await user.tab(); // Cameras
    await user.tab(); // the camera
    expect(link).toHaveFocus();
    expect(await screen.findByRole('tooltip')).toHaveTextContent(camera);
    // The actions are still there, after the identity.
    await user.tab();
    expect(screen.getByRole('button', { name: 'Act' })).toHaveFocus();
    // The full trail is the heading too, whatever the bar shows.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(`Cameras — ${camera} — Analytics`);
  });
});
