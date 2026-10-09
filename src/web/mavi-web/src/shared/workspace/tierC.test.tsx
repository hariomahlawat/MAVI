import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import Button from '../components/Button';
import { SHELL_QUERIES } from '../overlay/useMediaQuery';
import { stubMatchMedia, stubMatchMediaLive } from '../../test/matchMedia';
import ContextBar from './ContextBar';
import { RecordLayout, WorkbenchLayout } from './layouts';
import Toolbar from './Toolbar';

/*
 * T2 (§25 Tier C, 390px ≤ width < 768px): the shared pieces the narrow
 * compositions are made of — each proven on its own, including across the
 * 767/768 crossing, where a resize must neither lose focus nor remount work.
 */

const tierC = (query: string) => query === SHELL_QUERIES.narrow || query === SHELL_QUERIES.compact;
const tierB = (query: string) => query === SHELL_QUERIES.compact;

let restore: () => void = () => {};
afterEach(() => restore());

function Filters() {
  const [text, setText] = useState('');
  return (
    <Toolbar label="Video filters" hint="4 of 4 videos" drawer={{ label: 'Filters and sort', active: text ? 1 : 0 }}>
      <label>Filter <input value={text} onChange={(event) => setText(event.target.value)} /></label>
    </Toolbar>
  );
}

describe('the Ledger filters drawer (§25 Tier C: "filters move into a drawer")', () => {
  it('keeps the controls in the band above Tier C, and behind a counted control in a full drawer at Tier C', async () => {
    const live = stubMatchMediaLive(tierB);
    restore = live.restore;
    const user = userEvent.setup();
    render(<Filters />);
    expect(screen.queryByRole('button', { name: /Filters and sort/ })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Filter'), 'gate');

    live.set(tierC);
    const toggle = screen.getByRole('button', { name: 'Filters and sort · 1' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    const drawer = screen.getByRole('dialog', { name: 'Filters and sort' });
    expect(drawer).toHaveAttribute('aria-modal', 'true');
    // The same control, its value kept: a resize remounts nothing.
    expect(within(drawer).getByLabelText('Filter')).toHaveValue('gate');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });

  it('moves focus to the control that opens the drawer when a resize shuts a focused filter away', async () => {
    const live = stubMatchMediaLive(tierB);
    restore = live.restore;
    render(<Filters />);
    screen.getByLabelText('Filter').focus();
    live.set(tierC);
    expect(screen.getByRole('button', { name: /Filters and sort/ })).toHaveFocus();
  });

  it('keeps focus in the controls when a resize returns them to the band from the open drawer', async () => {
    const live = stubMatchMediaLive(tierC);
    restore = live.restore;
    const user = userEvent.setup();
    render(<Filters />);
    await user.click(screen.getByRole('button', { name: /Filters and sort/ }));
    screen.getByLabelText('Filter').focus();
    live.set(tierB);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Filter')).toHaveFocus();
  });
});

describe('the Record facts order (§4.2, §25 Tier C)', () => {
  function Run({ identity }: { identity: boolean }) {
    return (
      <RecordLayout factsCarryIdentity={identity} facts={<section aria-label="Video facts">south-dock.mp4</section>}>
        <section aria-label="Run"><label>Note <input defaultValue="" /></label></section>
      </RecordLayout>
    );
  }
  const order = () => Array.from(document.querySelectorAll('.workspace__record-grid > *')).map((el) => el.className);

  it('puts identity-bearing facts first in the document at Tier C, and only there', () => {
    const live = stubMatchMediaLive(tierB);
    restore = live.restore;
    render(<Run identity />);
    expect(order()).toEqual(['workspace__record-primary', 'workspace__record-facts']);
    live.set(tierC);
    expect(order()).toEqual(['workspace__record-facts', 'workspace__record-primary']);
  });

  it('keeps facts that carry no identity below, and moves rather than remounts the regions', async () => {
    const live = stubMatchMediaLive(tierB);
    restore = live.restore;
    const user = userEvent.setup();
    const { rerender } = render(<Run identity={false} />);
    live.set(tierC);
    expect(order()).toEqual(['workspace__record-primary', 'workspace__record-facts']);
    rerender(<Run identity />);
    await user.type(screen.getByLabelText('Note'), 'kept');
    live.set(tierB);
    expect(screen.getByLabelText('Note')).toHaveValue('kept');
  });
});

describe('the Workbench unsupported state (§25 Tier C)', () => {
  function Scene() {
    return (
      <WorkbenchLayout
        stage={<canvas data-testid="canvas" />}
        inspector={<button type="button">Delete zone</button>}
        unsupported={{ statement: 'Editing a scene needs a display at least 768px wide.', summary: <dl aria-label="Scene summary"><dt>Zones</dt><dd>2</dd></dl> }}
      />
    );
  }

  it('renders no canvas, stage, inspector or editing control at Tier C — the statement and the summary instead', () => {
    restore = stubMatchMedia(tierC);
    render(<Scene />);
    expect(screen.queryByTestId('canvas')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete zone' })).not.toBeInTheDocument();
    expect(document.querySelector('.workspace__stage, .workspace__inspector')).toBeNull();
    expect(screen.getByText('Editing a scene needs a display at least 768px wide.')).toBeInTheDocument();
    expect(screen.getByRole('definition')).toHaveTextContent('2');
  });

  it('draws the editor again when the window crosses back to 768px', () => {
    const live = stubMatchMediaLive(tierC);
    restore = live.restore;
    render(<Scene />);
    live.set(tierB);
    expect(screen.getByTestId('canvas')).toBeInTheDocument();
    expect(screen.queryByText(/needs a display at least 768px/)).not.toBeInTheDocument();
  });
});

describe('the Context Bar at Tier C (§25: the primary keeps its icon and label)', () => {
  it('draws a secondary action with an icon icon-only, still named, and leaves the primary and an icon-less action as they are', () => {
    restore = stubMatchMedia(tierC);
    render(
      <ContextBar
        surface="overview"
        actions={(
          <>
            <Button icon="upload">Import video</Button>
            <Button variant="ghost">Scene configuration</Button>
            <Button variant="primary" icon="search">Search tracks</Button>
          </>
        )}
      />,
    );
    const secondary = screen.getByRole('button', { name: 'Import video' });
    expect(secondary).toHaveClass('btn--icon');
    expect(secondary.querySelector('.visually-hidden')).toHaveTextContent('Import video');
    expect(screen.getByRole('button', { name: 'Scene configuration' })).not.toHaveClass('btn--icon');
    const primary = screen.getByRole('button', { name: 'Search tracks' });
    expect(primary).not.toHaveClass('btn--icon');
    expect(primary.querySelector('.visually-hidden')).toBeNull();
  });

  it('keeps every action labelled above Tier C', () => {
    restore = stubMatchMedia(tierB);
    render(<ContextBar surface="overview" actions={<Button icon="upload">Import video</Button>} />);
    expect(screen.getByRole('button', { name: 'Import video' })).not.toHaveClass('btn--icon');
  });
});
