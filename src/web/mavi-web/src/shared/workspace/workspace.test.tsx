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
        {({ attachContextBar, claimed, tone }) => (
          <div>
            <header className={barClass(tone)} ref={attachContextBar}>
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

  it('makes the Workbench inspector a drawer that can actually be shut', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <WorkbenchLayout stage={<canvas />} inspector={<p>inspector</p>} inspectorLabel="Scene inspector" />,
    );
    const workbench = container.querySelector('.workspace--workbench') as HTMLElement;
    const toggle = screen.getByRole('button', { name: 'Scene inspector' });

    // Between 1101 and 1149 the inspector covers the stage (§4.3.1). It starts
    // shut, because a drawer parked open over the canvas is the thing that rule
    // exists to prevent.
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveAttribute('aria-controls', container.querySelector('.workspace__inspector')?.id);
    expect(workbench).not.toHaveClass('has-open-drawer');

    await user.click(toggle);
    expect(workbench).toHaveClass('has-open-drawer');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    await user.click(screen.getByRole('button', { name: 'Close scene inspector' }));
    expect(workbench).not.toHaveClass('has-open-drawer');
  });

  it('lets Escape shut the drawer, and only while it is open', async () => {
    const user = userEvent.setup();
    const onEscape = vi.fn();
    window.addEventListener('keydown', onEscape);
    try {
      const { container } = render(<WorkbenchLayout stage={<canvas />} inspector={<p>inspector</p>} />);
      const workbench = container.querySelector('.workspace--workbench') as HTMLElement;

      // Shut, Escape is the surface's own: cancelling a drawing, clearing a
      // selection. The drawer must not eat it.
      await user.keyboard('{Escape}');
      expect(onEscape).toHaveBeenCalledTimes(1);

      await user.click(screen.getByRole('button', { name: 'Inspector' }));
      expect(workbench).toHaveClass('has-open-drawer');

      // Open, closing what covers the canvas is what the operator meant, so the
      // drawer takes it first and the surface never sees it.
      await user.keyboard('{Escape}');
      expect(workbench).not.toHaveClass('has-open-drawer');
      expect(onEscape).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener('keydown', onEscape);
    }
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

/**
 * Tests are not implementations. A test that names an archetype class in a
 * selector is asserting on the one implementation, not adding another, so the
 * scans below look at what ships rather than at what checks it.
 */
const isTest = (path: string) => /\.test\.tsx?$/.test(path);

describe('the archetype set is closed', () => {
  it('has exactly one implementation of each archetype', () => {
    const offenders: string[] = [];
    for (const klass of ARCHETYPE_CLASSES) {
      const implementers = Object.entries(SOURCES)
        .filter(([path]) => !isTest(path))
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
      .filter(([path]) => !isTest(path) && !path.includes('/shared/workspace/'))
      .filter(([, source]) => /\bLedgerSummaryLayout\b/.test(withoutComments(source)))
      .map(([path]) => path);
    expect(importers.filter((path) => !path.includes('/features/overview/'))).toEqual([]);
  });

  it('releases every contained archetype where the layout stacks', () => {
    // §4's shared rule: below 1100 all archetypes stack to a single column and
    // the page scrolls. The shell lifts its containment there, and each
    // archetype has to let go of the height and internal overflow that held it
    // — including the Overview summary variant, which is contained above that
    // width like every other Ledger.
    const css = SHEETS['/src/styles/workspace.css'];
    const stacking = css.slice(css.indexOf('@media (max-width: 1100px)'));
    for (const archetype of ['workspace--ledger', 'workspace--ledger-summary', 'workspace--workbench', 'workspace--investigation']) {
      expect(stacking).toContain(archetype);
    }
    expect(stacking).toContain('.workspace--ledger-summary .workspace__body--scroll');
  });

  it('lets only the archetypes declare how a surface scrolls', () => {
    // §4's scroll ownership is a property of the archetype, so the archetype
    // states it. If a page could call this, a page could opt out of the rule —
    // which is the whole thing the declaration exists to prevent.
    const callers = Object.entries(SOURCES)
      .filter(([path]) => !isTest(path) && path !== '/src/shared/workspace/surfaceSlot.tsx')
      .filter(([, source]) => /\buseScrollPolicy\s*\(/.test(withoutComments(source)))
      .map(([path]) => path);
    expect(callers).toEqual(['/src/shared/workspace/layouts.tsx']);
  });

  it('caps the Investigation results column whether or not a Track is selected', () => {
    // §4.4 caps the results column at approximately 900px and gives the surplus
    // to the inspector. The cap is not conditional on there being an inspector:
    // an Investigation with nothing selected is still a scan surface, and an
    // uncapped column on a 2560px display is a 2000px result row either way.
    //
    // Asserted on the stylesheet because the rule is a grid template, and jsdom
    // computes no layout to measure. The rendered geometry is measured by the
    // §26 harness at real viewports, which is the half this cannot do.
    const css = SHEETS['/src/styles/workspace.css'].replace(/\/\*[\s\S]*?\*\//g, '');
    const base = css.slice(css.indexOf('.workspace__investigation-grid {'));
    const unselected = base.slice(0, base.indexOf('}'));
    expect(unselected).toContain('var(--c-results-max)');
    // Without the third column the cap has to be a cap rather than a floor:
    // `stretch` would hand the surplus straight back to the results.
    expect(unselected).toContain('justify-content: start');
  });

  it('contains the Investigation rail without giving the form a second scroll owner', () => {
    // §11: a border marks a scroll boundary or an editable region. The rail
    // column is both — it owns the rail's only scroll and it holds the filter
    // form — so one border there satisfies the rule, and a second one around
    // the form would be the card-inside-card §11 calls a defect.
    const css = SHEETS['/src/styles/workspace.css'].replace(/\/\*[\s\S]*?\*\//g, '');
    const rail = css.slice(css.indexOf('.workspace__rail {'));
    const block = rail.slice(0, rail.indexOf('}'));
    expect(block).toMatch(/border:\s*var\(--stroke-hair\)/);
    expect(block).toContain('overflow-y: auto');

    // And the form itself must not scroll. Two scroll owners in one column is
    // the defect UI-4 removed; a border is not a licence to bring it back.
    const features = SHEETS['/src/styles/features.css'].replace(/\/\*[\s\S]*?\*\//g, '');
    const form = features.slice(features.indexOf('.filter-rail {'));
    expect(form.slice(0, form.indexOf('}'))).not.toMatch(/overflow/);
    expect(features).not.toMatch(/\.filter-rail[^{]*\{[^}]*overflow-y:\s*(auto|scroll)/);
    // Nor be stuck to the column's edge, which is how it came to sit on the
    // last field at 1366 when the rail was tall enough to scroll.
    const actions = features.slice(features.indexOf('.filter-rail__actions {'));
    expect(actions.slice(0, actions.indexOf('}'))).not.toContain('position: sticky');
  });

  it('declares which inspector shape is in force rather than leaving it implied', () => {
    // Open decision 3 is a number the §26 harness has to check the layout
    // against, and a harness carrying the number itself can only confirm its
    // own assumption. The archetype publishes its placement as a custom
    // property beside the media query that decides it, so moving the threshold
    // is an edit here and nowhere else — as UI-4 did, from 1500 to 1600.
    const css = SHEETS['/src/styles/workspace.css'].replace(/\/\*[\s\S]*?\*\//g, '');
    expect(css).toMatch(/\.workspace--investigation\s*\{[^}]*--inspector-placement:\s*drawer/);
    const threshold = css.slice(css.indexOf('@media (min-width: 1600px)'));
    expect(threshold.slice(0, threshold.indexOf('@media', 1)))
      .toMatch(/--inspector-placement:\s*in-place/);
  });

  it('gives the in-place Investigation inspector a floor the results yield to', () => {
    // Open decision 3's second half. §4.4 gives the *surplus* to the inspector,
    // which says nothing about what happens when there is none: a grid that
    // grants the results their 900px cap first measured 60px of inspector at
    // 1500 and 160px at 1600 — in place by the letter of the rule and unusable.
    // The floor is what makes the results yield instead.
    const css = SHEETS['/src/styles/workspace.css'].replace(/\/\*[\s\S]*?\*\//g, '');
    const threshold = css.slice(css.indexOf('@media (min-width: 1600px)'));
    const inPlace = threshold.slice(0, threshold.indexOf('@media', 1));
    expect(inPlace).toContain('minmax(var(--c-inspector-min-w), 1fr)');
    expect(SHEETS['/src/styles/tokens.css']).toContain('--c-inspector-min-w');
  });

  it('gives every surface one Context Bar implementation', () => {
    // The band's markup belongs to the shell and the primitive. A feature that
    // wrote its own `.context-bar` would produce the two-bar page §5 forbids,
    // and every other assertion here would still pass.
    const offenders = Object.entries(SOURCES)
      .filter(([path]) => !isTest(path) && !path.includes('/shared/workspace/') && path !== '/src/app/AppShell.tsx')
      .filter(([, source]) => /className=["'`][^"'`]*\bcontext-bar\b/.test(withoutComments(source)))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
