import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState, type ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import ContextBar, { barClass, Breadcrumbs } from './ContextBar';
import Inspector from './Inspector';
import Segmented from './Segmented';
import { SurfaceSlotProvider } from './surfaceSlot';
import Toolbar from './Toolbar';
import { LedgerLayout, WorkbenchLayout } from './layouts';

/**
 * The workspace grammar's own tests.
 *
 * Two kinds of assertion live here, and they are different in kind. The first
 * are behavioural: what the shared primitives render and how they behave. The
 * second are structural — that there is exactly one implementation of each
 * archetype, that scroll ownership is declared in one place, and that the
 * Overview exception cannot be reached from anywhere else. Those cannot be
 * expressed as a rendered assertion, because the defect they catch is a second
 * implementation appearing somewhere else in the tree, which by definition no
 * test of the first implementation can see.
 */

/** The shell, reduced to the part that owns the Context Bar band. */
function Shell({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <SurfaceSlotProvider>
        {(attach, claimed, tone) => (
          <div>
            <header className={barClass(tone)} ref={attach}>
              {claimed ? null : <Breadcrumbs crumbs={[{ label: 'Section' }]} />}
            </header>
            <main>{children}</main>
          </div>
        )}
      </SurfaceSlotProvider>
    </MemoryRouter>
  );
}

describe('Context Bar', () => {
  it('fills the shell band rather than adding a second one', () => {
    const { container } = render(
      <Shell>
        <ContextBar crumbs={[{ label: 'Cameras', to: '/cameras' }, { label: 'CAM-01' }, { label: 'Scene' }]} />
      </Shell>,
    );

    // §5: the topbar *becomes* the Context Bar. One band, whoever fills it.
    expect(container.querySelectorAll('.context-bar')).toHaveLength(1);
    const bar = container.querySelector('.context-bar') as HTMLElement;
    expect(within(bar).getByText('CAM-01')).toBeInTheDocument();
    // The title block is gone, but the surface still has a document heading:
    // §4 removes the block, not the ability to ask "where am I?".
    expect(within(bar).getByRole('heading', { level: 1 })).toHaveTextContent('Cameras — CAM-01 — Scene');
    // The shell's fallback is gone, not rendered underneath the surface's own.
    expect(within(bar).queryByText('Section')).not.toBeInTheDocument();
  });

  it('leaves the shell its section name while a surface publishes nothing', () => {
    const { container } = render(<Shell><p>An unmigrated surface</p></Shell>);
    const bar = container.querySelector('.context-bar') as HTMLElement;
    expect(within(bar).getByText('Section')).toBeInTheDocument();
  });

  it('gives the band back when the surface unmounts', () => {
    function Host() {
      const [open, setOpen] = useState(true);
      return (
        <Shell>
          <button type="button" onClick={() => setOpen(false)}>leave</button>
          {open ? <ContextBar crumbs={[{ label: 'Cameras' }]} /> : null}
        </Shell>
      );
    }
    const { container } = render(<Host />);
    const bar = () => container.querySelector('.context-bar') as HTMLElement;
    expect(within(bar()).queryByText('Section')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'leave' }));
    expect(within(bar()).getByText('Section')).toBeInTheDocument();
  });

  it('lets a surface state that it is not the live thing, and takes it back', () => {
    function Host() {
      const [past, setPast] = useState(true);
      return (
        <Shell>
          <button type="button" onClick={() => setPast(false)}>return</button>
          <ContextBar crumbs={[{ label: 'Scene' }]} tone={past ? 'caution' : undefined} />
        </Shell>
      );
    }
    const { container } = render(<Host />);
    const bar = () => container.querySelector('.context-bar') as HTMLElement;
    // §27.1 generalises the Scene Editor's read-only treatment: the whole bar
    // says it, because mistaking a past revision for the live one is the
    // expensive error.
    expect(bar()).toHaveClass('context-bar--caution');

    fireEvent.click(screen.getByRole('button', { name: 'return' }));
    expect(bar()).not.toHaveClass('context-bar--caution');
  });

  it('renders itself when there is no shell to publish into', () => {
    // A page must not lose its identity, state and actions because of where it
    // was mounted — which is also what keeps a surface testable on its own.
    const { container } = render(
      <MemoryRouter>
        <ContextBar crumbs={[{ label: 'Cameras' }, { label: 'Scene' }]} status={<span>Saved</span>} />
      </MemoryRouter>,
    );
    expect(container.querySelectorAll('.context-bar')).toHaveLength(1);
    expect(screen.getByText('Saved')).toBeInTheDocument();
  });

  it('names where you are, and links only to where you have been', () => {
    render(
      <MemoryRouter>
        <Breadcrumbs crumbs={[{ label: 'Cameras', to: '/cameras' }, { label: 'CAM-01' }, { label: 'Scene', to: '/x' }]} />
      </MemoryRouter>,
    );
    const nav = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(nav).getByRole('link', { name: 'Cameras' })).toHaveAttribute('href', '/cameras');
    // A crumb without a destination names an object; it is not a dead link.
    expect(within(nav).queryByRole('link', { name: 'CAM-01' })).not.toBeInTheDocument();
    // The last crumb is where you are, so it never navigates, `to` or not.
    expect(within(nav).queryByRole('link', { name: 'Scene' })).not.toBeInTheDocument();
    expect(within(nav).getByText('Scene')).toHaveAttribute('aria-current', 'page');
  });
});

describe('Segmented', () => {
  it('states one pressed option in a named group, and is not a tablist', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        label="Drawing tools"
        value="zone"
        options={[{ value: 'select', label: 'Select' }, { value: 'zone', label: 'Zone' }]}
        onChange={onChange}
      />,
    );

    const group = screen.getByRole('group', { name: 'Drawing tools' });
    expect(within(group).getByRole('button', { name: 'Zone' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: 'Select' })).toHaveAttribute('aria-pressed', 'false');
    // Nothing here controls a tabpanel, and claiming the role would promise
    // arrow-key navigation between panels that does not exist.
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
    expect(screen.queryAllByRole('tablist')).toHaveLength(0);

    await user.click(within(group).getByRole('button', { name: 'Select' }));
    expect(onChange).toHaveBeenCalledWith('select');
  });
});

describe('Toolbar', () => {
  it('is a named band carrying controls, one line of text, and actions', () => {
    render(
      <Toolbar label="Scene tools" hint="Click to add a vertex" actions={<button type="button">Revisions</button>}>
        <button type="button">Select</button>
      </Toolbar>,
    );
    const band = screen.getByRole('group', { name: 'Scene tools' });
    expect(within(band).getByRole('button', { name: 'Select' })).toBeInTheDocument();
    expect(within(band).getByRole('button', { name: 'Revisions' })).toBeInTheDocument();
    expect(within(band).getByText('Click to add a vertex')).toBeInTheDocument();
  });
});

describe('Inspector', () => {
  it('is a labelled region whose body owns the scroll', () => {
    const { container } = render(<Inspector label="Properties" title="Properties">content</Inspector>);
    expect(screen.getByRole('complementary', { name: 'Properties' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Properties' })).toBeInTheDocument();
    // The scroll owner is a structural fact about the shell, not a page's
    // choice: §4.3 gives the Workbench exactly one, and this is it.
    expect(container.querySelector('.inspector__body')).toBeInTheDocument();
  });

  it('shows the workspace summary rather than going blank', () => {
    render(<Inspector label="Properties" isEmpty summary={<p>3 zones, 1 trip line</p>}><p>Gate</p></Inspector>);
    // §4.3: "Shows a workspace summary when nothing is selected; never blank."
    expect(screen.getByText('3 zones, 1 trip line')).toBeInTheDocument();
    expect(screen.queryByText('Gate')).not.toBeInTheDocument();
  });
});

describe('archetypes', () => {
  it('carries scroll ownership on the archetype, not on the page', () => {
    const { container } = render(
      <LedgerLayout toolbar={<div>filters</div>}><table><tbody /></table></LedgerLayout>,
    );
    // A Ledger's body scrolls and its page does not, and a page cannot opt out
    // of that because it never declares it.
    expect(container.querySelector('.workspace--ledger .workspace__body--scroll')).toBeInTheDocument();
  });

  it('gives the Workbench a stage and an inspector that are not interchangeable', () => {
    const { container } = render(
      <WorkbenchLayout stage={<canvas />} inspector={<p>inspector</p>} modes={<div>modes</div>} />,
    );
    const grid = container.querySelector('.workspace__stage-grid') as HTMLElement;
    expect(grid.querySelector('.workspace__stage canvas')).toBeInTheDocument();
    expect(grid.querySelector('.workspace__inspector')).toHaveTextContent('inspector');
    // The stage comes first in the DOM as well as visually: reading order is
    // not a styling concern.
    expect(grid.children[0]).toHaveClass('workspace__stage');
  });
});

/**
 * Structural invariants.
 *
 * `import.meta.glob` reads the sources as the bundler sees them, which is how
 * these assertions can be about the whole tree rather than about the module
 * under test.
 */
// Rooted at the project, so the keys are stable paths rather than paths
// relative to this file.
const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const SHEETS = import.meta.glob('/src/styles/*.css', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

const ARCHETYPE_CLASSES = [
  'workspace--ledger',
  'workspace--ledger-summary',
  'workspace--record',
  'workspace--workbench',
  'workspace--investigation',
  'workspace--review',
];

/** Comments talk about archetypes; only code declares one. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

const isThisTest = (path: string) => path.endsWith('workspace.test.tsx');

describe('the archetype set is closed', () => {
  it('has exactly one implementation of each archetype', () => {
    const offenders: string[] = [];
    for (const klass of ARCHETYPE_CLASSES) {
      const implementers = Object.entries(SOURCES)
        .filter(([path]) => !isThisTest(path))
        .filter(([, source]) => withoutComments(source).includes(klass))
        .map(([path]) => path);
      // §4 freezes the set at five archetypes and a named Overview exception.
      // A second implementation of one is how a sixth gets invented.
      if (implementers.length !== 1 || implementers[0] !== '/src/shared/workspace/layouts.tsx') {
        offenders.push(`${klass}: ${implementers.join(', ') || 'no implementation'}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('declares the archetypes\' layout and scroll ownership in one stylesheet', () => {
    const offenders: string[] = [];
    for (const [path, css] of Object.entries(SHEETS)) {
      if (path.endsWith('workspace.css')) continue;
      for (const klass of [...ARCHETYPE_CLASSES, 'workspace__']) {
        if (css.replace(/\/\*[\s\S]*?\*\//g, '').includes(klass)) offenders.push(`${path}: ${klass}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('keeps the Overview exception reachable only from Overview', () => {
    // §4.1.1 lets Overview alone stay centred. It is a separate component
    // rather than a prop precisely so that using it means importing something
    // that says Overview on the tin — and so that this can be asserted.
    const importers = Object.entries(SOURCES)
      .filter(([path]) => !isThisTest(path) && !path.includes('/shared/workspace/'))
      .filter(([, source]) => /\bLedgerSummaryLayout\b/.test(withoutComments(source)))
      .map(([path]) => path);
    expect(importers.filter((path) => !path.includes('/features/overview/'))).toEqual([]);
  });

  it('gives every surface one Context Bar implementation', () => {
    // The band's markup belongs to the shell and the primitive. A feature that
    // wrote its own `.context-bar` would produce the two-bar page §5 forbids,
    // and every other assertion here would still pass.
    const offenders = Object.entries(SOURCES)
      .filter(([path]) => !isThisTest(path) && !path.includes('/shared/workspace/') && path !== '/src/app/AppShell.tsx')
      .filter(([, source]) => /className=["'`][^"'`]*\bcontext-bar\b/.test(withoutComments(source)))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
