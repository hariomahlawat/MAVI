import { render, screen } from '@testing-library/react';
import { createRoot } from 'react-dom/client';
import { StrictMode, useState, type ReactNode } from 'react';
import { flushSync } from 'react-dom';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import ContextBar, { Breadcrumbs, barClass } from './ContextBar';
import {
  InvestigationLayout,
  LedgerLayout,
  LedgerSummaryLayout,
  RecordLayout,
  ReviewLayout,
  WorkbenchLayout,
} from './layouts';
import { SurfaceSlotProvider } from './surfaceSlot';

/**
 * Context Bar ownership, observed at the commit boundary.
 *
 * The invariant is about frames, not about settled output: there must never be
 * a painted frame in which the shell's fallback and a surface's published
 * content are both in the band, or in which neither is, because ownership is
 * waiting for an effect to catch up. A test that renders and then asserts on
 * the final DOM cannot see either state — it only ever looks after everything
 * has settled, which is precisely when the bug is invisible.
 *
 * So these commit the update with `flushSync` and read the DOM immediately.
 * `flushSync` renders, commits and runs layout effects synchronously, and
 * deliberately does *not* run passive effects — so what is in the DOM when it
 * returns is what the browser would have painted. Against the original
 * passive-effect ownership these fail: two crumb trails going in, none coming
 * out. That is the mutation proof, and re-introducing `useEffect` in
 * `ContextBar` reproduces it.
 */

/** Commit the update and stop: layout effects run, passive effects do not. */
function commitOnly(update: () => void) {
  const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
  const prior = env.IS_REACT_ACT_ENVIRONMENT;
  // `act` exists to flush everything, which is the one thing this must not do.
  env.IS_REACT_ACT_ENVIRONMENT = false;
  try {
    flushSync(update);
  } finally {
    env.IS_REACT_ACT_ENVIRONMENT = prior;
  }
}

/** The shell, reduced to the two things it decides about the current surface. */
function Shell({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <SurfaceSlotProvider>
        {({ attachContextBar, claimed, tone, scroll }) => (
          <div>
            <header className={barClass(tone)} ref={attachContextBar} data-testid="band">
              {claimed ? null : <Breadcrumbs crumbs={[{ label: 'Section' }]} />}
            </header>
            <main className="main" data-scroll={scroll} data-testid="main">{children}</main>
          </div>
        )}
      </SurfaceSlotProvider>
    </MemoryRouter>
  );
}

type Surface = 'plain' | 'scene' | 'other' | 'historical';

function surfaceFor(surface: Surface) {
  switch (surface) {
    case 'scene':
      return <ContextBar crumbs={[{ label: 'Cameras' }, { label: 'CAM-01' }, { label: 'Scene' }]} />;
    case 'historical':
      return <ContextBar tone="caution" crumbs={[{ label: 'Cameras' }, { label: 'CAM-01' }, { label: 'Revision 3' }]} />;
    case 'other':
      return <ContextBar crumbs={[{ label: 'Videos' }, { label: 'Gate clip' }]} />;
    default:
      return <p>an unmigrated page</p>;
  }
}

/** Renders a shell whose surface can be swapped in a single commit. */
function mountShell(initial: Surface, { strict = false }: { strict?: boolean } = {}) {
  let go: (to: Surface) => void = () => {};
  function App() {
    const [surface, setSurface] = useState<Surface>(initial);
    go = setSurface;
    return <Shell>{surfaceFor(surface)}</Shell>;
  }
  render(strict ? <StrictMode><App /></StrictMode> : <App />);
  return { go: (to: Surface) => commitOnly(() => go(to)) };
}

const band = () => screen.getByTestId('band');
/** How many crumb trails are in the band — the thing that must always be one. */
const trails = () => band().querySelectorAll('nav[aria-label="Breadcrumb"]').length;

describe('Context Bar ownership at the commit boundary', () => {
  it('hands the band over without ever showing two trails', () => {
    const shell = mountShell('plain');
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Section');

    shell.go('scene');

    // Before this was a layout effect, the published content arrived in one
    // commit and the fallback left in the next, so this read two.
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Scene');
    expect(band()).not.toHaveTextContent('Section');
  });

  it('takes the band back without ever showing an empty one', () => {
    const shell = mountShell('scene');
    expect(band()).toHaveTextContent('Scene');

    shell.go('plain');

    // Before this was a layout effect, the portal emptied in one commit and
    // ownership was released in the next, so this read zero.
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Section');
  });

  it('passes the band between two migrated surfaces in one commit', () => {
    const shell = mountShell('scene');

    shell.go('other');

    // The outgoing surface's cleanup and the incoming one's registration are
    // both layout-phase work in the same commit, so the band is never
    // unowned in between — and never doubly owned either.
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Gate clip');
    expect(band()).not.toHaveTextContent('Scene');
    expect(band()).not.toHaveTextContent('Section');
  });

  it('drops a surface tone in the same commit that drops the surface', () => {
    const shell = mountShell('historical');
    expect(band()).toHaveClass('context-bar--caution');

    shell.go('scene');

    // The tone is registered with the ownership rather than in an effect of
    // its own, so a live scene cannot paint under a past revision's warning.
    expect(band()).not.toHaveClass('context-bar--caution');
    expect(band()).toHaveTextContent('Scene');

    shell.go('plain');
    expect(band()).not.toHaveClass('context-bar--caution');
    expect(band()).toHaveTextContent('Section');
  });

  it('survives StrictMode double invocation without corrupting ownership', () => {
    // The application mounts under StrictMode, so every effect here runs
    // mount, unmount, mount in development. A keyed register is idempotent
    // under that; a counter would have had to balance.
    const shell = mountShell('plain', { strict: true });
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Section');

    shell.go('scene');
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Scene');

    shell.go('plain');
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Section');

    // And again, to catch a register that only balances once.
    shell.go('scene');
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Scene');
  });

  it('is settled on the very first commit, not one commit later', () => {
    // Landing directly on a migrated surface is the case the other tests
    // cannot see, because they arrive at it from somewhere else. Here the
    // shell, the band element and the surface all appear in one mount, and
    // this mounts a real root outside `act` so that nothing flushes the
    // passive effects on its behalf.
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    try {
      commitOnly(() => {
        root.render(
          <Shell>
            <ContextBar crumbs={[{ label: 'Cameras' }, { label: 'CAM-01' }, { label: 'Scene' }]} />
          </Shell>,
        );
      });

      const mounted = host.querySelector('[data-testid="band"]') as HTMLElement;
      expect(mounted.querySelectorAll('nav[aria-label="Breadcrumb"]')).toHaveLength(1);
      expect(mounted.textContent).toContain('Scene');
      expect(mounted.textContent).not.toContain('Section');
    } finally {
      commitOnly(() => root.unmount());
      host.remove();
    }
  });

  it('still renders itself when there is no shell to publish into', () => {
    // The standalone path takes no part in registration, and must not start
    // depending on it.
    render(
      <MemoryRouter>
        <ContextBar tone="caution" crumbs={[{ label: 'Cameras' }, { label: 'Scene' }]} />
      </MemoryRouter>,
    );
    expect(screen.getAllByRole('navigation', { name: 'Breadcrumb' })).toHaveLength(1);
  });
});

/**
 * The shell's other fact about the current surface: whether its content column
 * may scroll.
 *
 * §4 freezes a scroll owner per archetype, and for the Workbench (§4.3.2) it
 * freezes that the page must not scroll at all. `workspace.css` already said
 * which element *inside* the archetype scrolls, but the shell's `.main` stayed
 * `overflow: auto` for every surface — so the Workbench rule held only while
 * its content happened to fit. These assert the other half: that the archetype
 * declares the policy and the shell applies it, that the five archetypes have
 * not been homogenised into one, and that nothing is left behind on the way
 * out.
 */
const main = () => screen.getByTestId('main');
const policy = () => main().getAttribute('data-scroll');

function renderShell(children: ReactNode) {
  render(<Shell>{children}</Shell>);
}

describe('shell scroll policy', () => {
  it('lets the Workbench forbid page scrolling, as §4.3.2 requires', () => {
    renderShell(<WorkbenchLayout stage={<canvas />} inspector={<p>inspector</p>} />);
    expect(policy()).toBe('contain');
  });

  it('keeps page scrolling on Record and Review, which need it', () => {
    // §4.2 and §4.5.1: these two scroll the page on purpose, and a shell policy
    // that homogenised them would put provenance below an unreachable fold.
    renderShell(<RecordLayout facts={<p>facts</p>}><p>record</p></RecordLayout>);
    expect(policy()).toBe('page');

    screen.getByText('record');
    renderShell(<ReviewLayout player={<div>player</div>} rail={<p>rail</p>} />);
    expect(screen.getAllByTestId('main').at(-1)).toHaveAttribute('data-scroll', 'page');
  });

  it('contains Ledger and Investigation, whose own regions scroll', () => {
    renderShell(<LedgerLayout><table><tbody /></table></LedgerLayout>);
    expect(policy()).toBe('contain');

    renderShell(<InvestigationLayout rail={<p>rail</p>}><p>results</p></InvestigationLayout>);
    expect(screen.getAllByTestId('main').at(-1)).toHaveAttribute('data-scroll', 'contain');
  });

  it('holds the Overview summary variant to the Ledger scroll grammar', () => {
    // §4's scroll-ownership table is frozen and lists Overview under Ledger;
    // §4.1.1 grants this variant a *width* exception and nothing else. So the
    // page must not scroll, and the variant's own body is what does — the
    // centred width is the exception, not the scrolling.
    const { container } = render(<Shell><LedgerSummaryLayout><p>summary</p></LedgerSummaryLayout></Shell>);
    expect(policy()).toBe('contain');
    const summary = container.querySelector('.workspace--ledger-summary');
    expect(summary?.querySelector('.workspace__body--scroll')).toBeInTheDocument();
    // The width exception survives the correction.
    expect(summary).toHaveClass('workspace--ledger-summary');
  });

  it('applies and withdraws the policy in the commit that changes the surface', () => {
    let go: (to: 'plain' | 'workbench') => void = () => {};
    function App() {
      const [where, setWhere] = useState<'plain' | 'workbench'>('plain');
      go = setWhere;
      return (
        <Shell>
          {where === 'workbench'
            ? <WorkbenchLayout stage={<canvas />} inspector={<p>inspector</p>} />
            : <p>an unmigrated page</p>}
        </Shell>
      );
    }
    render(<App />);
    expect(policy()).toBe('page');

    // A policy applied a frame late is a frame in which the wrong element can
    // scroll, so this is read at the commit boundary like ownership is.
    commitOnly(() => go('workbench'));
    expect(policy()).toBe('contain');

    commitOnly(() => go('plain'));
    expect(policy()).toBe('page');
  });
});

describe('the shell returns to its fallback state on the way out', () => {
  it('leaves no ownership, tone or scroll policy behind after a round trip', () => {
    // The route transition the §6 interaction check names: an ordinary page,
    // into the Workbench, and back out to an ordinary page. Both of the shell's
    // facts about a surface must be gone, not merely overwritten.
    let go: (to: 'plain' | 'scene' | 'other') => void = () => {};
    function App() {
      const [where, setWhere] = useState<'plain' | 'scene' | 'other'>('plain');
      go = setWhere;
      return (
        <Shell>
          {where === 'scene' ? (
            <>
              <ContextBar tone="caution" crumbs={[{ label: 'Cameras' }, { label: 'CAM-01' }, { label: 'Revision 3' }]} />
              <WorkbenchLayout stage={<canvas />} inspector={<p>inspector</p>} />
            </>
          ) : (
            <p>{where === 'other' ? 'another ordinary page' : 'an unmigrated page'}</p>
          )}
        </Shell>
      );
    }
    render(<App />);

    commitOnly(() => go('scene'));
    expect(policy()).toBe('contain');
    expect(band()).toHaveClass('context-bar--caution');
    expect(band()).toHaveTextContent('Revision 3');

    commitOnly(() => go('other'));
    // No stale claim: the fallback is back, exactly once.
    expect(trails()).toBe(1);
    expect(band()).toHaveTextContent('Section');
    // No stale tone.
    expect(band()).not.toHaveClass('context-bar--caution');
    // No stale scroll policy.
    expect(policy()).toBe('page');
  });
});
