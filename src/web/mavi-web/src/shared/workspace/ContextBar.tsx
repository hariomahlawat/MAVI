import { useId, useLayoutEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useSurfaceSlot, type ContextTone } from './surfaceSlot';

/**
 * The Context Bar (§5).
 *
 * One shared implementation, rendered into the shell's single band. It carries
 * three things and nothing else: where the operator is, what state this surface
 * is in, and what they can do to it.
 *
 * §27.1 promotion: every archetype begins with this bar (§4), the semantics are
 * identical on each — identity, state, primary actions — the interaction
 * contract is the same (links navigate, actions act), and the accessibility
 * contract is the same (one banner landmark, a labelled breadcrumb). The
 * variation points are the three slots, which is what a structural primitive
 * should vary by.
 *
 * Deliberately absent: a page title block and a description sentence. §4 removes
 * those from the product; moving them into permanent chrome would be keeping
 * them under a new name.
 */

export type Crumb = {
  label: string;
  /** A crumb links to an ancestor surface; the last crumb is where you are. */
  to?: string;
};

export default function ContextBar({
  crumbs,
  status,
  actions,
  tone,
}: {
  /** `Section › Object › Sub-surface`. A child surface must name itself (§5). */
  crumbs: Crumb[];
  /** Key state badges for this surface. */
  status?: ReactNode;
  /** Primary actions for this surface. */
  actions?: ReactNode;
  /**
   * A state the whole surface is in, rather than one badge's worth of it.
   * §27.1 generalises the Scene Editor's read-only treatment: mistaking a past
   * revision for the live one is the expensive error, and a chip alone was
   * judged too quiet for it.
   */
  tone?: ContextTone;
}) {
  const slot = useSurfaceSlot();
  const register = slot?.register;
  const unregister = slot?.unregister;
  const element = slot?.element ?? null;
  const id = useId();

  // Owning the band and publishing into it are the same fact, so they are
  // decided by the same condition — there is somewhere to publish, and this
  // surface is publishing there — and registered in one call.
  //
  // This is a layout effect, not a passive one, and that is the whole point.
  // React flushes state updates scheduled during the layout phase before the
  // browser paints, so the commit where the shell still believes it owns the
  // band is never a painted frame. A passive effect carries no such guarantee,
  // which is how the band came to show two crumb trails on the way in and none
  // on the way out. The tone rides along rather than living in a second effect
  // that could be a frame behind the ownership it describes.
  useLayoutEffect(() => {
    if (!register || !unregister || !element) return undefined;
    register(id, tone ?? null);
    return () => unregister(id);
  }, [register, unregister, element, id, tone]);

  const content = (
    <>
      {/* §4 removes the large page title *block* from the product; it does not
          remove the document's heading, and a surface with no h1 is harder to
          orient in by keyboard, not simpler. So the trail is also stated once
          as the heading — where a screen-reader user jumps to ask "where am
          I?" — and takes no space on screen. */}
      <h1 className="visually-hidden">{crumbs.map((crumb) => crumb.label).join(' — ')}</h1>
      <Breadcrumbs crumbs={crumbs} />
      {status ? <div className="context-bar__status">{status}</div> : null}
      <div className="context-bar__spacer" />
      {actions ? <div className="context-bar__actions">{actions}</div> : null}
    </>
  );

  // Outside the shell there is no band to publish into, so the bar renders
  // itself. A surface must not lose its identity, state and actions merely
  // because of where it was mounted — which is also what keeps a page testable
  // on its own rather than only through the whole application.
  if (!slot) return <header className={barClass(tone)}>{content}</header>;

  // Inside the shell, the band is the shell's. Before it exists there is
  // nowhere to render; the shell shows its own fallback for that one frame.
  if (!slot.element) return null;
  return createPortal(content, slot.element);
}

/** The band's class, so the shell and the standalone case cannot diverge. */
export function barClass(tone: ContextTone | null | undefined): string {
  return tone ? `context-bar context-bar--${tone}` : 'context-bar';
}

export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="context-bar__crumbs" aria-label="Breadcrumb">
      <ol>
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={`${crumb.label}-${index}`}>
              {/* A crumb truncates rather than pushing the bar's controls off
                  the end, so the full text stays reachable on the title. */}
              {crumb.to && !last ? (
                <Link to={crumb.to} title={crumb.label}>{crumb.label}</Link>
              ) : (
                <span aria-current={last ? 'page' : undefined} title={crumb.label}>{crumb.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
